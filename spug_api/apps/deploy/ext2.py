# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf import settings
from libs.utils import AttrDict, render_str, human_seconds_time
from libs.executor import Executor
from apps.host.models import Host
from apps.deploy.helper import SpugError, normalize_script as _normalize_script
from concurrent import futures
from contextlib import nullcontext
import fnmatch
import json
import posixpath
import shlex
import tarfile
import time
import os

REPOS_DIR = settings.REPOS_DIR


def ext2_deploy(req, helper, env, with_local):
    flag = time.time()
    extend, step = req.deploy.extend_obj, 1
    host_actions = json.loads(extend.host_actions)
    server_actions = json.loads(extend.server_actions)
    env.update({'SPUG_RELEASE': req.version})
    if req.version:
        for index, value in enumerate(req.version.split()):
            env.update({f'SPUG_RELEASE_{index + 1}': value})

    transfer_action = None
    for action in host_actions:
        if action.get('type') == 'transfer':
            action['src'] = render_str(action.get('src', '').strip().rstrip('/'), env)
            action['dst'] = render_str(action['dst'].strip().rstrip('/'), env)
            if action.get('src_mode') == '1':  # upload when publish
                if not req.extra:
                    helper.send_error('local', '\r\n未找到上传的文件信息，请尝试新建发布申请')
                extra = json.loads(req.extra)
                if 'name' in extra:
                    action['name'] = extra['name']
            else:
                transfer_action = action
            break

    if with_local:
        # 只有存在「服务端动作」时才需要 bash 执行器；纯数据传输打包走纯 Python，
        # 这样 Windows 上没有 bash 也能正常发布
        executor_ctx = Executor(env) if server_actions else nullcontext(None)
        with executor_ctx as et:
            if et is not None:
                helper.save_pid(et.pid, 'local')
            helper.set_deploy_process('local')
            helper.send_success('local', '', status='doing')
            if server_actions or transfer_action:
                helper.send_clear('local')
            for action in server_actions:
                helper.send_info('local', f'{action["title"]}...\r\n')
                helper.local(et, f'cd /tmp && {_normalize_script(action["data"])}')
                step += 1
            if transfer_action:
                action = transfer_action
                action['src'] = action['src'].rstrip('/ ')
                action['dst'] = action['dst'].rstrip('/ ')
                if not action['src'] or not action['dst']:
                    helper.send_error('local', f'Invalid path for transfer, src: {action["src"]} dst: {action["dst"]}')
                if not os.path.exists(action['src']):
                    helper.send_error('local', f'No such file or directory: {action["src"]}')
                is_dir = os.path.isdir(action['src'])
                sp_dir, sd_dst = os.path.split(action['src'])
                if not is_dir:
                    # 单文件直接上传，不需要打包（也就没有中间归档这一层）
                    helper.send_info('local', f'来源为单个文件，跳过打包：{sd_dst}\r\n')
                else:
                    helper.send_info('local', '检测到来源为本地路径的数据传输动作，执行打包...   \r\n')
                    # the tarball is picked up from here again by _deploy_ext2_host
                    tar_gz_dir = os.path.join(REPOS_DIR, env.SPUG_DEPLOY_ID)
                    os.makedirs(tar_gz_dir, exist_ok=True)
                    tar_gz_file = os.path.join(tar_gz_dir, f'{req.spug_version}.tar.gz')
                    _pack_transfer_source(action, is_dir, sd_dst, tar_gz_file, env, helper)
                    helper.send_info('local', '打包完成\r\n')
            helper.set_cross_env(req.spug_version, et.get_envs() if et is not None else {})
            helper.set_deploy_success('local')
            human_time = human_seconds_time(time.time() - flag)
            helper.send_success('local', f'\r\n** 执行完成，耗时：{human_time} **', status='success')

    if host_actions:
        env.update(helper.get_cross_env(req.spug_version))
        if req.deploy.is_parallel:
            threads, latest_exception = [], None
            max_workers = max(10, os.cpu_count() * 5)
            with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                for h_id in sorted(helper.deploy_host_ids, reverse=True):
                    new_env = AttrDict(env.items())
                    t = executor.submit(_deploy_ext2_host, helper, h_id, host_actions, new_env, req.spug_version)
                    t.h_id = h_id
                    threads.append(t)
                for t in futures.as_completed(threads):
                    exception = t.exception()
                    if exception:
                        helper.set_deploy_fail(t.h_id)
                        latest_exception = exception
                        if not isinstance(exception, SpugError):
                            helper.send_error(t.h_id, f'Exception: {exception}', with_break=False)
                    else:
                        helper.set_deploy_success(t.h_id)
            if latest_exception:
                raise latest_exception
        else:
            host_ids = sorted(helper.deploy_host_ids)
            while host_ids:
                h_id = host_ids.pop()
                new_env = AttrDict(env.items())
                try:
                    _deploy_ext2_host(helper, h_id, host_actions, new_env, req.spug_version)
                    helper.set_deploy_success(h_id)
                except Exception as e:
                    helper.set_deploy_fail(h_id)
                    if not isinstance(e, SpugError):
                        helper.send_error(h_id, f'Exception: {e}', with_break=False)
                    for h_id in host_ids:
                        helper.set_deploy_fail(h_id)
                        helper.send_clear(h_id)
                        helper.send_error(h_id, '串行模式，终止发布', with_break=False)
                    raise e


def _pack_transfer_source(action, is_dir, sd_dst, tar_gz_file, env, helper):
    """把「数据传输」的本地来源打成 tar.gz。

    原实现调用 `tar -zcf`，Windows 上没有 bash/tar，命令失败后打包产物不存在，
    主机阶段上传就会报 WinError 3。这里改为纯 Python tarfile，跨平台一致。
    归档内的顶层名字固定为来源的 basename，主机端解包后按同名 mv。
    """
    src = action['src']
    files = []
    if action['mode'] != '0' and is_dir:
        files = helper.parse_filter_rule(action['rule'], ',', env)

    with tarfile.open(tar_gz_file, 'w:gz') as tar:
        if not is_dir:
            tar.add(src, arcname=sd_dst)
            return
        if action['mode'] == '1' and files:
            for item in files:
                rel = item.lstrip('/')
                path = os.path.join(src, *rel.split('/'))
                if os.path.exists(path):
                    tar.add(path, arcname=f'{sd_dst}/{rel}')
            return

        excludes = [x.lstrip('/') for x in files] if action['mode'] == '2' else []

        def _filter(member):
            rel = member.name
            if rel.startswith(sd_dst + '/'):
                rel = rel[len(sd_dst) + 1:]
            elif rel == sd_dst:
                return member
            for pattern in excludes:
                if (rel == pattern or rel.startswith(pattern.rstrip('/') + '/')
                        or fnmatch.fnmatch(rel, pattern)):
                    return None
            return member

        tar.add(src, arcname=sd_dst, filter=_filter)


def _assert_safe_dst(dst):
    """数据传输会用 `rm -rf dst` 覆盖目标，必须拦住系统目录。

    例如把目标路径写成 `/tmp/`，原逻辑会执行 `rm -rf /tmp`，把刚解包的内容
    连同系统临时目录一起删掉，随后 mv 必然失败。
    """
    normalized = posixpath.normpath(dst or '/')
    protected = {
        '/', '/tmp', '/var', '/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64',
        '/boot', '/root', '/home', '/opt', '/srv', '/mnt', '/media', '/proc',
        '/sys', '/dev', '/run', '/data',
    }
    if normalized in protected or normalized.count('/') < 2:
        raise SpugError(
            f'目标路径 {dst!r} 不安全：数据传输会先删除该目录再放入新内容，'
            f'请填写具体落地路径（例如 /tmp/app 或 /data/app），不要填写系统目录或其父目录')


def _deploy_ext2_host(helper, h_id, actions, env, spug_version):
    flag = time.time()
    helper.set_deploy_process(h_id)
    host = Host.objects.filter(pk=h_id).first()
    if not host:
        helper.send_error(h_id, 'no such host')
    env.update({'SPUG_HOST_ID': h_id, 'SPUG_HOST_NAME': host.hostname})
    with host.get_ssh(default_env=env) as ssh:
        helper.send_clear(h_id)
        pid = ssh.get_pid()
        if pid:
            helper.save_pid(pid, h_id)
        helper.send_success(h_id, '', status='doing')
        for index, action in enumerate(actions, start=1):
            if action.get('type') == 'transfer':
                helper.send_info(h_id, f'{action["title"]}...')
                if action.get('src_mode') == '1':
                    try:
                        dst = action['dst']
                        command = f'[ -e {dst} ] || mkdir -p $(dirname {dst}); [ -d {dst} ]'
                        code, _ = ssh.exec_command_raw(command)
                        if code == 0:  # is dir
                            if not action.get('name'):
                                raise RuntimeError('internal error 1002')
                            dst = dst.rstrip('/') + '/' + action['name']
                        callback = helper.progress_callback(host.id)
                        ssh.put_file(os.path.join(REPOS_DIR, env.SPUG_DEPLOY_ID, spug_version), dst, callback)
                    except Exception as e:
                        helper.send_error(host.id, f'\r\nException: {e}')
                    helper.send_success(host.id, '完成√\r\n')
                else:
                    _, sd_dst = os.path.split(action['src'])
                    is_file_src = os.path.isfile(action['src'])
                    # 只有「目录来源」才会先 rm -rf 目标再整体替换，单文件只是写一个文件，
                    # 对 /tmp 这类目录本身是安全的，不应套用同一套拦截规则
                    if not is_file_src:
                        _assert_safe_dst(action['dst'])
                    tar_gz_file = f'{spug_version}.tar.gz'
                    src_file = os.path.join(REPOS_DIR, env.SPUG_DEPLOY_ID, tar_gz_file)
                    try:
                        callback = helper.progress_callback(host.id)
                        if is_file_src:
                            # 单文件：直接 SFTP 上传到目标路径，无需 tar/解包/覆盖删除
                            dst = action['dst']
                            # 目标以 / 结尾即视为目录，无论其当前是否存在；随后统一建目录，
                            # 避免 SFTP 因父目录缺失报 [Errno 2] No such file
                            as_dir = dst.endswith('/')
                            if not as_dir:
                                code, _ = ssh.exec_command_raw(f'[ -d {shlex.quote(dst)} ]')
                                as_dir = code == 0
                            if as_dir:
                                dst = dst.rstrip('/') + '/' + sd_dst
                                parent = posixpath.dirname(dst)
                                if parent:
                                    ssh.exec_command_raw(f'mkdir -p {shlex.quote(parent)}')
                            ssh.put_file(action['src'], dst, callback)
                            # 上传后立刻校验并回显真实路径，便于排查“文件明明在却找不到”
                            try:
                                st = ssh.sftp_stat(dst)
                            except Exception:
                                raise SpugError(f'上传后校验失败：{dst} 不存在')
                            helper.send_success(
                                host.id, f'\r\n已上传: {dst}（{st.st_size} 字节）\r\n')
                        else:
                            ssh.put_file(src_file, f'/tmp/{tar_gz_file}', callback)
                    except Exception as e:
                        helper.send_error(host.id, f'\r\nException: {e}')
                    helper.send_success(host.id, '完成√\r\n')
                    if not is_file_src:
                        # 目录：远端解包后按顶层目录名落地
                        command = f'mkdir -p /tmp/{spug_version} '
                        command += f'&& tar xf /tmp/{tar_gz_file} -C /tmp/{spug_version}/ '
                        command += f'&& rm -rf {action["dst"]} && mv /tmp/{spug_version}/{sd_dst} {action["dst"]} '
                        command += f'&& rm -rf /tmp/{spug_version}*'
                        helper.remote(host.id, ssh, command)
                        code, _ = ssh.exec_command_raw(
                            f'[ -e {shlex.quote(action["dst"])} ]')
                        if code == 0:
                            helper.send_success(host.id, f'已落地: {action["dst"]}\r\n')
                        else:
                            helper.send_error(
                                host.id, f'目标路径不存在: {action["dst"]}\r\n')
            else:
                helper.send_info(h_id, f'{action["title"]}...\r\n')
                command = f'cd /tmp && {_normalize_script(action["data"])}'
                helper.remote(host.id, ssh, command)
    human_time = human_seconds_time(time.time() - flag)
    helper.send_success(h_id, f'\r\n** 发布成功，耗时：{human_time} **', status='success')
