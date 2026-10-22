# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""流水线通用制品拉取节点（方案 A：只消费，不做上传/浏览）。

已实现：raw 文件源、rpm 源（写 repo 配置 + pyinfra pkg 安装）、
deb 源（写 apt 源 + pyinfra pkg 安装）；OCI 镜像源保留分支待迭代。
约束：远端只用系统原生命令，不依赖 Python；凭据不写入日志、
不进命令行参数（sudo 密码走 SSH stdin）。
"""
import base64
import shlex
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from libs.utils import SpugError
from apps.host.models import Host
from apps.ops.context import get_merged_context, render_jinja


def _render(node, host_id, pipeline_id, field, default=''):
    value = node.get(field, default)
    if value in (None, ''):
        return ''
    context, _, _ = get_merged_context(pipeline_id, host_id)
    return render_jinja(value, context)


def _build_url(node, host_id, pipeline_id):
    base = _render(node, host_id, pipeline_id, 'base_url').rstrip('/')
    if not base:
        raise SpugError('制品源地址不能为空')
    parts = [base]
    for field in ('repo_name', 'package', 'version'):
        value = _render(node, host_id, pipeline_id, field).strip('/')
        if value:
            parts.append(value)
    return '/'.join(parts)


def _auth_headers(node):
    auth_type = node.get('auth_type') or 'none'
    if auth_type == 'none':
        return {}, '无认证'
    from apps.credential.models import Credential
    credential = Credential.objects.filter(pk=node.get('credential_id')).first()
    if credential is None:
        raise SpugError('未找到所选认证凭据')
    if auth_type == 'bearer':
        return {'Authorization': f'Bearer {credential.secret}'}, 'Bearer Token'
    if auth_type == 'basic':
        raw = f'{credential.username}:{credential.secret}'.encode()
        return {'Authorization': 'Basic ' + base64.b64encode(raw).decode()}, 'Basic Auth'
    raise SpugError(f'不支持的认证方式: {auth_type}')


def _target_path(node, host_id, pipeline_id, url):
    path = _render(node, host_id, pipeline_id, 'dest_path')
    if not path:
        raise SpugError('目标路径不能为空')
    if path.endswith('/'):
        name = urlparse(url).path.rstrip('/').split('/')[-1] or 'artifact'
        path = path + name
    return path


def _head_probe(url, headers):
    try:
        resp = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
        return resp.status_code, resp.headers.get('Content-Length')
    except requests.RequestException as e:
        raise SpugError(f'访问制品地址失败: {e.__class__.__name__}')


def _download_script(url, dest, headers, overwrite):
    header_args = ' '.join(f"-H {shlex.quote(f'{k}: {v}')}" for k, v in headers.items())
    overwrite_flag = '1' if overwrite else '0'
    return f'''
set -e
url={shlex.quote(url)}
dest={shlex.quote(dest)}
mkdir -p "$(dirname "$dest")"
if [ -f "$dest" ]; then
  local_size=$(stat -c %s "$dest" 2>/dev/null || wc -c < "$dest")
  remote_size=$(curl -fsSI {header_args} "$url" | awk 'tolower($1)=="content-length:"{{print $2}}' | tr -d '\\r' | tail -1)
  if [ -n "$remote_size" ] && [ "$local_size" = "$remote_size" ]; then
    echo "__SPUG_UNCHANGED__"
    exit 0
  fi
  if [ "{overwrite_flag}" != "1" ]; then
    echo "__SPUG_UNCHANGED_EXISTS__"
    exit 0
  fi
fi
tmp="$dest.spug-tmp.$$"
curl -fsSL --retry 2 {header_args} -o "$tmp" "$url"
mv -f "$tmp" "$dest"
echo "__SPUG_CHANGED__"
'''


def _build_repo_url(node, host_id, pipeline_id):
    base = _render(node, host_id, pipeline_id, 'base_url').rstrip('/')
    if not base:
        raise SpugError('制品源地址不能为空')
    repo = _render(node, host_id, pipeline_id, 'repo_name').strip('/')
    return f'{base}/{repo}' if repo else base


def _credential_of(node):
    auth_type = node.get('auth_type') or 'none'
    if auth_type == 'none':
        return None, '无认证'
    from apps.credential.models import Credential
    credential = Credential.objects.filter(pk=node.get('credential_id')).first()
    if credential is None:
        raise SpugError('未找到所选认证凭据')
    return credential, {'bearer': 'Bearer Token', 'basic': 'Basic Auth'}[auth_type]


def _pkg_name(node, host_id, pipeline_id, source_type):
    name = _render(node, host_id, pipeline_id, 'package').strip()
    version = _render(node, host_id, pipeline_id, 'version').strip()
    if not name:
        raise SpugError('包名不能为空')
    if version:
        return f'{name}-{version}' if source_type == 'rpm' else f'{name}={version}'
    return name


def _rpm_repo_content(node, repo_url, credential, auth_type):
    lines = [
        '[spug-artifact]',
        f'name=Spug Artifact {repo_url.split("/")[-1]}',
        f'baseurl={repo_url}',
        'enabled=1',
        'gpgcheck=0',
        'repo_gpgcheck=0',
    ]
    if auth_type == 'basic' and credential:
        lines.append(f'username={credential.username}')
        lines.append(f'password={credential.secret}')
    elif auth_type == 'bearer' and credential:
        lines.append(f'http_headers=Authorization: Bearer {credential.secret}')
    return '\n'.join(lines) + '\n'


def _deb_repo_content(node, repo_url, credential, auth_type, host_id, pipeline_id):
    if auth_type == 'bearer':
        raise SpugError('deb 源暂不支持 Bearer Token（apt 限制），请改用 Basic Auth 或无认证')
    url = repo_url
    if auth_type == 'basic' and credential:
        # apt 仅支持 URL 内嵌 Basic 凭据，凭据只写进源配置文件
        if '://' in url:
            scheme, rest = url.split('://', 1)
            url = f'{scheme}://{credential.username}:{credential.secret}@{rest}'
    suite = (_render(node, host_id, pipeline_id, 'suite') or '').strip() or './'
    component = (_render(node, host_id, pipeline_id, 'component') or '').strip() or 'main'
    return f'deb [trusted=yes] {url} {suite} {component}\n'


def _source_already_configured(host, url):
    """远端是否已配置相同源地址（避免与系统既有源产生 Trusted 等冲突）。"""
    try:
        with host.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(
                f"grep -rls -- {shlex.quote(url)} /etc/apt/sources.list "
                f"/etc/apt/sources.list.d /etc/yum.repos.d 2>/dev/null || true")
        return bool((out or '').strip())
    except Exception:
        return False


def _write_remote_file(host, path, content, key, helper):
    """通过 SSH stdin 写入远端文件（凭据不出现在命令行参数，也不落本地磁盘）。"""
    is_root = (host.username or '').lower() == 'root'
    if is_root:
        command = f"cat > {path}"
        stdin = content
    else:
        command = f"sudo -S -p '' sh -c 'cat > {path}'"
        stdin = (host.password or '') + '\n' + content
        if not host.password:
            raise SpugError('该主机非 root 且未保存登录密码，无法使用 sudo 写入系统目录')
    with host.get_ssh() as ssh:
        code, out = ssh.exec_command_stdin(command, stdin)
    if code != 0:
        raise SpugError(f'写入 {path} 失败: {(out or "").strip()[:200]}')
    helper.send_info(key, f'已写入源配置: {path}（凭据已隐藏）')


def _host_family(host):
    """优先读缓存 Facts；没有缓存时用 /etc/os-release 实时判定（不写入缓存）。"""
    from apps.ops.kernel import facts as facts_kernel
    values = facts_kernel.load(host.id)
    if values.get('os_family'):
        return values['os_family'], values
    try:
        with host.get_ssh() as ssh:
            code, out = ssh.exec_command_raw('cat /etc/os-release 2>/dev/null || true')
        if code == 0 and out:
            fake = {'os_release': _parse_os_release(out)}
            return facts_kernel.family_of(fake), values
    except Exception:
        pass
    return None, values


def _parse_os_release(text):
    result = {}
    for line in (text or '').splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            # 统一小写键，兼容 family_of 的 id / id_like 取值
            result[key.strip().lower()] = value.strip().strip('"')
    return result


def _do_pkg_source(node_executor, node, host, dry_run, source_type):
    """rpm/deb：写远端源配置 + 调用 pyinfra pkg 模块安装（复用原生幂等/dry-run）。"""
    key = f'{node.id}.{host.id}'
    helper = node_executor.helper
    pipeline_id = getattr(node_executor, 'pipeline_id', None)
    family, facts = _host_family(host)
    want = 'RedHat' if source_type == 'rpm' else 'Debian'
    if family is None:
        helper.send_error(key, '无法识别主机系统类型（缺少 Facts 缓存且 /etc/os-release 不可读），'
                              '请先执行「刷新Facts」节点')
        return False, True
    if family != want:
        helper.send_error(key, f'{source_type} 源仅支持 {want} 系主机，当前为 {family}')
        return False, True

    try:
        repo_url = _build_repo_url(node, host.id, pipeline_id)
        credential, auth_label = _credential_of(node)
        package = _pkg_name(node, host.id, pipeline_id, source_type)
        if source_type == 'rpm':
            path = f'/etc/yum.repos.d/spug-artifact-{node.id}.repo'
            content = _rpm_repo_content(node, repo_url, credential, node.get('auth_type') or 'none')
        else:
            path = f'/etc/apt/sources.list.d/spug-artifact-{node.id}.list'
            content = _deb_repo_content(node, repo_url, credential,
                                        node.get('auth_type') or 'none', host.id, pipeline_id)
        helper.send_info(key, f'制品仓库: {repo_url}\r\n安装包: {package}\r\n认证方式: {auth_label}\r\n', 'processing')

        if not dry_run:
            if _source_already_configured(host, repo_url):
                # 系统已配置相同源（例如整机已指向该仓库）：跳过写入，
                # 否则 apt/yum 会因 Trusted/gpgcheck 等选项冲突而报错
                helper.send_info(key, '系统已存在相同源配置，跳过写入')
            else:
                _write_remote_file(host, path, content, key, helper)

        from apps.ops.kernel.runner import StateRunner
        params = {'packages': [package], 'present': True}
        if source_type == 'deb':
            # cache_time 让 pyinfra 在更新戳记较新时跳过 apt-get update，
            # 否则每次执行都会因 update 被判定为 changed（不幂等）
            params['update'] = True
            params['cache_time'] = 600
        summary = StateRunner(
            [host], 'pkg', params,
            dry_run=dry_run,
            on_event=lambda hid, kind, msg: helper.send(f'{key}.{hid}', f'{msg}\r\n'),
            record=not dry_run,
            source='pipeline',
            source_id=node_executor.history_id,
            operator=node_executor.operator,
            sudo=(host.username or '').lower() != 'root',
            sudo_password=host.password,
        ).run()
        item = summary.results[0] if summary.results else None
        if item is None:
            helper.send_error(key, '未获取到安装结果')
            return False, True
        if item.failed:
            helper.send_error(key, item.msg or '安装失败')
            return False, True
        if item.changed:
            helper.send_success(key, f'{package} 安装完成（{"Dry-run 预览" if dry_run else "已变更"}）')
            return True, False
        helper.send_success(key, f'{package} 已安装，无需变更')
        return False, False
    except SpugError as e:
        helper.send_error(key, str(e))
        return False, True
    except Exception as e:
        helper.send_error(key, f'制品安装异常: {e.__class__.__name__}')
        return False, True


def _do_host(node_executor, node, host, dry_run):
    key = f'{node.id}.{host.id}'
    helper = node_executor.helper
    pipeline_id = getattr(node_executor, 'pipeline_id', None)
    source_type = node.get('source_type') or 'raw'
    if source_type == 'rpm':
        return _do_pkg_source(node_executor, node, host, dry_run, 'rpm')
    if source_type == 'deb':
        return _do_pkg_source(node_executor, node, host, dry_run, 'deb')
    if source_type != 'raw':
        helper.send_error(key, f'暂不支持的制品源类型: {source_type}')
        return False, True
    try:
        url = _build_url(node, host.id, pipeline_id)
        headers, auth_label = _auth_headers(node)
        dest = _target_path(node, host.id, pipeline_id, url)
        overwrite = bool(node.get('overwrite'))
        helper.send_info(key, f'制品地址: {url}\r\n认证方式: {auth_label}\r\n', 'processing')

        if dry_run:
            status, length = _head_probe(url, headers)
            if 200 <= status < 400:
                helper.send_success(key, f'Dry-run: 资源可访问（HTTP {status}，大小 {length or "未知"}）')
                return False, False
            helper.send_error(key, f'Dry-run: 资源不可访问（HTTP {status}）')
            return False, True

        script = _download_script(url, dest, headers, overwrite)
        with host.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(script)
        if code != 0:
            helper.send_error(key, f'下载失败（exit {code}）: {(out or "").strip()[:500]}')
            return False, True
        if '__SPUG_UNCHANGED__' in out:
            helper.send_success(key, '文件已是最新，跳过下载（大小一致）')
            return False, False
        if '__SPUG_UNCHANGED_EXISTS__' in out:
            helper.send_success(key, '目标文件已存在且未开启覆盖，跳过下载')
            return False, False
        if '__SPUG_CHANGED__' in out:
            helper.send_success(key, f'下载完成: {dest}')
            return True, False
        helper.send_success(key, '下载完成')
        return True, False
    except SpugError as e:
        helper.send_error(key, str(e))
        return False, True
    except Exception as e:
        helper.send_error(key, f'制品拉取异常: {e.__class__.__name__}')
        return False, True


def execute(node_executor, node):
    targets = node.get('targets') or []
    hosts = list(Host.objects.filter(id__in=targets))
    if not hosts:
        node_executor.helper.send_error(node.id, '制品节点未配置目标主机')
        return node_executor.run(node, 'error')

    dry_run = bool(node.get('dry_run')) or bool(getattr(node_executor, 'dry_run', False))
    node_executor.helper.send_status(node.id, 'processing')
    changed = failed = False
    with ThreadPoolExecutor(max_workers=min(10, len(hosts))) as pool:
        futures = [pool.submit(_do_host, node_executor, node, host, dry_run) for host in hosts]
        for future in as_completed(futures):
            try:
                item_changed, item_failed = future.result()
                changed = changed or item_changed
                failed = failed or item_failed
            except Exception:
                failed = True

    state = 'error' if failed else ('changed' if changed else 'success')
    node_executor.helper.send_status(node.id, 'error' if failed else 'success')
    return node_executor.run(node, state)
