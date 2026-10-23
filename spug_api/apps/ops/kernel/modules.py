# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一状态模块注册表（对标 Ansible Module）。

每个模块向 UI 暴露一份字段描述（MODULE_SCHEMA），并负责把表单参数翻译成
pyinfra 原生 operation。禁止 subprocess / CLI，全部同进程调用。
"""
import json
import os
import posixpath
import re
from io import StringIO

from pyinfra import host
from pyinfra.api import operation
from pyinfra.api.command import QuoteString, StringCommand
from pyinfra.api.exceptions import OperationError
from pyinfra.facts.files import Sha256File
from pyinfra.operations import (apk, apt, crontab, dnf, files, git, pip, server,
                                systemd, sysvinit, yum)

# 供前端渲染可视化表单；type: text/textarea/number/boolean/select/template
MODULE_SCHEMA = {
    'pkg': {
        'title': '软件包',
        'desc': '安装/卸载软件包，自动识别 Debian/RedHat/Alpine 系',
        'fields': [
            {'name': 'packages', 'label': '软件包', 'type': 'text', 'required': True,
             'placeholder': 'nginx, curl（逗号或换行分隔）'},
            {'name': 'present', 'label': '目标状态', 'type': 'select', 'default': True,
             'options': [{'label': '安装', 'value': True}, {'label': '卸载', 'value': False}]},
            {'name': 'latest', 'label': '升级到最新', 'type': 'boolean', 'default': False},
        ],
    },
    'file': {
        'title': '文件',
        'desc': '文件存在性 / 内容 / 权限管理，内容可来自 Jinja2 模板',
        'fields': [
            {'name': 'path', 'label': '目标路径', 'type': 'text', 'required': True, 'placeholder': '/etc/nginx/nginx.conf'},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'content', 'label': '文件内容', 'type': 'textarea', 'placeholder': '留空表示只管理存在性/权限'},
            {'name': 'template_id', 'label': '使用模板', 'type': 'template', 'placeholder': '可选，选择后覆盖内容'},
            {'name': 'mode', 'label': '权限', 'type': 'text', 'placeholder': '0644'},
            {'name': 'owner', 'label': '属主', 'type': 'text'},
            {'name': 'group', 'label': '属组', 'type': 'text'},
        ],
    },
    'directory': {
        'title': '目录',
        'desc': '目录存在性 / 权限 / 递归创建',
        'fields': [
            {'name': 'path', 'label': '目录路径', 'type': 'text', 'required': True},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'mode', 'label': '权限', 'type': 'text', 'placeholder': '0755'},
            {'name': 'owner', 'label': '属主', 'type': 'text'},
            {'name': 'group', 'label': '属组', 'type': 'text'},
            {'name': 'recursive', 'label': '递归设置', 'type': 'boolean', 'default': False},
        ],
    },
    'service': {
        'title': '服务',
        'desc': '服务启停 / 开机自启，自动选择 systemd 或 sysvinit',
        'fields': [
            {'name': 'name', 'label': '服务名', 'type': 'text', 'required': True, 'placeholder': 'nginx'},
            {'name': 'running', 'label': '运行中', 'type': 'boolean', 'default': True},
            {'name': 'enabled', 'label': '开机自启', 'type': 'boolean', 'default': True},
            {'name': 'restarted', 'label': '重启服务', 'type': 'boolean', 'default': False},
        ],
    },
    'user': {
        'title': '用户',
        'desc': '系统用户创建 / 删除 / 属性管理',
        'fields': [
            {'name': 'username', 'label': '用户名', 'type': 'text', 'required': True},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'home', 'label': '家目录', 'type': 'text'},
            {'name': 'shell', 'label': 'Shell', 'type': 'text', 'placeholder': '/bin/bash'},
            {'name': 'groups', 'label': '附加组', 'type': 'text', 'placeholder': 'sudo, docker'},
            {'name': 'password', 'label': '密码', 'type': 'password', 'secret': True,
             'placeholder': '留空表示不修改'},
        ],
    },
    'group': {
        'title': '用户组',
        'desc': '系统用户组创建 / 删除',
        'fields': [
            {'name': 'group', 'label': '组名', 'type': 'text', 'required': True},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'system', 'label': '系统组', 'type': 'boolean', 'default': False},
        ],
    },
    'command': {
        'title': '原生命令',
        'desc': '在目标主机执行 shell 命令（幂等由命令自身保证）',
        'fields': [
            {'name': 'commands', 'label': '命令内容', 'type': 'textarea', 'required': True,
             'placeholder': '多条命令每行一条，例如：\nmkdir -p /data/app\nchown www:www /data/app'},
        ],
    },
    'line': {
        'title': '配置行',
        'desc': '管理文件中的某一行（增/删/替换），适合开关类配置',
        'fields': [
            {'name': 'path', 'label': '文件路径', 'type': 'text', 'required': True,
             'placeholder': '/etc/sysconfig/selinux'},
            {'name': 'line', 'label': '行内容', 'type': 'text', 'required': True,
             'placeholder': 'SELINUX=disabled'},
            {'name': 'present', 'label': '存在该行', 'type': 'boolean', 'default': True},
            {'name': 'replace', 'label': '替换匹配（正则）', 'type': 'text',
             'placeholder': '^SELINUX=.*（留空则按整行匹配）'},
        ],
    },
    'block': {
        'title': '配置块',
        'desc': '用标记管理文件中的一段内容，适合 hosts/ssh_config 等',
        'fields': [
            {'name': 'path', 'label': '文件路径', 'type': 'text', 'required': True},
            {'name': 'content', 'label': '块内容', 'type': 'textarea', 'required': True},
            {'name': 'present', 'label': '存在该块', 'type': 'boolean', 'default': True},
            {'name': 'marker', 'label': '标记名', 'type': 'text',
             'placeholder': '留空自动生成（如 # {marker} spug）'},
        ],
    },
    'sysctl': {
        'title': '内核参数',
        'desc': 'sysctl 参数设置与持久化',
        'fields': [
            {'name': 'key', 'label': '参数名', 'type': 'text', 'required': True,
             'placeholder': 'net.ipv4.ip_forward'},
            {'name': 'value', 'label': '参数值', 'type': 'text', 'required': True,
             'placeholder': '1'},
            {'name': 'persist', 'label': '写入配置文件', 'type': 'boolean', 'default': True},
        ],
    },
    'crontab': {
        'title': '定时任务',
        'desc': '远端 crontab 条目管理（按名称幂等）',
        'fields': [
            {'name': 'command', 'label': '执行命令', 'type': 'text', 'required': True,
             'placeholder': '/data/backup.sh'},
            {'name': 'cron_name', 'label': '条目名称', 'type': 'text', 'required': True,
             'placeholder': 'spug-backup'},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'minute', 'label': '分钟', 'type': 'text', 'placeholder': '0'},
            {'name': 'hour', 'label': '小时', 'type': 'text', 'placeholder': '2'},
            {'name': 'day_of_month', 'label': '日', 'type': 'text', 'placeholder': '*'},
            {'name': 'month', 'label': '月', 'type': 'text', 'placeholder': '*'},
            {'name': 'day_of_week', 'label': '周', 'type': 'text', 'placeholder': '*'},
            {'name': 'user', 'label': '以哪个用户', 'type': 'text', 'placeholder': 'root',
             'help': '管理其他用户的 crontab 需要 root 权限，将自动使用 sudo'},
        ],
    },
    'download': {
        'title': '远端下载',
        'desc': '在目标主机上用 curl/wget 下载 URL 文件',
        'fields': [
            {'name': 'src', 'label': '下载地址', 'type': 'text', 'required': True,
             'placeholder': 'https://example.com/app.tar.gz'},
            {'name': 'dest', 'label': '保存路径', 'type': 'text', 'required': True,
             'placeholder': '/tmp/app.tar.gz'},
            {'name': 'md5sum', 'label': 'MD5 校验', 'type': 'text',
             'placeholder': '留空不校验'},
            {'name': 'force', 'label': '强制重新下载', 'type': 'boolean', 'default': False},
        ],
    },
    # ---------------- 以下对标 Ansible 高频模块 ----------------
    'link': {
        'title': '软链接',
        'desc': '创建/删除符号链接（对标 file state=link）',
        'fields': [
            {'name': 'path', 'label': '链接路径', 'type': 'text', 'required': True,
             'placeholder': '/usr/bin/app'},
            {'name': 'target', 'label': '指向目标', 'type': 'text', 'required': True,
             'placeholder': '/opt/app/bin/app'},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'force', 'label': '覆盖已存在', 'type': 'boolean', 'default': False},
            {'name': 'owner', 'label': '属主', 'type': 'text'},
            {'name': 'group', 'label': '属组', 'type': 'text'},
        ],
    },
    'unarchive': {
        'title': '解压',
        'desc': '解压 tar/tar.gz/tar.bz2/tar.xz 到目标目录（对标 unarchive）',
        'fields': [
            {'name': 'src', 'label': '压缩包路径', 'type': 'text', 'required': True,
             'placeholder': '/tmp/app.tar.gz（远端路径）'},
            {'name': 'dest', 'label': '解压到', 'type': 'text', 'required': True,
             'placeholder': '/opt/app'},
            {'name': 'remote_src', 'label': '压缩包已在远端', 'type': 'boolean', 'default': True},
            {'name': 'strip_components', 'label': '剥离层级', 'type': 'number',
             'placeholder': '0，解压 app-1.0/ 内容时可填 1'},
            {'name': 'creates', 'label': '幂等标记路径', 'type': 'text',
             'placeholder': '该路径已存在时跳过解压（如 /opt/app/app.jar）'},
        ],
    },
    'copy': {
        'title': '复制/移动',
        'desc': '主机内复制或移动文件/目录（对标 copy / move）',
        'fields': [
            {'name': 'src', 'label': '源路径', 'type': 'text', 'required': True},
            {'name': 'dest', 'label': '目标路径', 'type': 'text', 'required': True},
            {'name': 'move', 'label': '移动而非复制', 'type': 'boolean', 'default': False},
            {'name': 'owner', 'label': '属主', 'type': 'text'},
            {'name': 'group', 'label': '属组', 'type': 'text'},
            {'name': 'mode', 'label': '权限', 'type': 'text', 'placeholder': '0644'},
        ],
    },
    'replace': {
        'title': '内容替换',
        'desc': '按正则替换文件内容（对标 replace）',
        'fields': [
            {'name': 'path', 'label': '文件路径', 'type': 'text', 'required': True},
            {'name': 'match', 'label': '匹配正则', 'type': 'text', 'required': True,
             'placeholder': '^(\\s*)Listen\\s+80'},
            {'name': 'replace', 'label': '替换为', 'type': 'text', 'required': True,
             'placeholder': '\\1Listen 8080'},
            {'name': 'flags', 'label': '正则选项', 'type': 'text',
             'placeholder': 'MULTILINE / IGNORECASE'},
        ],
    },
    'fetch': {
        'title': '拉取文件',
        'desc': '把远端文件下载到 Spug 服务端（对标 fetch）',
        'fields': [
            {'name': 'src', 'label': '远端路径', 'type': 'text', 'required': True},
            {'name': 'dest', 'label': '服务端保存目录', 'type': 'text', 'required': True,
             'placeholder': '留空则用数据目录下的 downloads'},
        ],
    },
    'mount': {
        'title': '挂载',
        'desc': '挂载文件系统并写入 fstab（对标 mount）',
        'fields': [
            {'name': 'path', 'label': '挂载点', 'type': 'text', 'required': True,
             'placeholder': '/data'},
            {'name': 'device', 'label': '设备/远端', 'type': 'text', 'required': True,
             'placeholder': '/dev/sdb1 或 10.0.0.1:/export'},
            {'name': 'fstype', 'label': '文件系统类型', 'type': 'text',
             'placeholder': 'ext4 / nfs / xfs'},
            {'name': 'present', 'label': '挂载', 'type': 'boolean', 'default': True},
            {'name': 'options', 'label': '挂载选项', 'type': 'text',
             'placeholder': 'defaults,noatime'},
        ],
    },
    'timezone': {
        'title': '时区',
        'desc': '设置系统时区（对标 timezone）',
        'fields': [
            {'name': 'timezone', 'label': '时区', 'type': 'text', 'required': True,
             'placeholder': 'Asia/Shanghai'},
        ],
    },
    'hostname': {
        'title': '主机名',
        'desc': '设置主机名（对标 hostname）',
        'fields': [
            {'name': 'hostname', 'label': '主机名', 'type': 'text', 'required': True},
        ],
    },
    'etc_hosts': {
        'title': 'hosts 记录',
        'desc': '管理 /etc/hosts 条目（对标 lineinfile on /etc/hosts）',
        'fields': [
            {'name': 'ip', 'label': 'IP 地址', 'type': 'text', 'required': True},
            {'name': 'hostnames', 'label': '主机名', 'type': 'text', 'required': True,
             'placeholder': 'app.local, www.app.local（逗号分隔）'},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
        ],
    },
    'modprobe': {
        'title': '内核模块',
        'desc': '加载/卸载内核模块（对标 modprobe）',
        'fields': [
            {'name': 'name', 'label': '模块名', 'type': 'text', 'required': True,
             'placeholder': 'br_netfilter'},
            {'name': 'present', 'label': '加载', 'type': 'boolean', 'default': True},
            {'name': 'persist', 'label': '开机自动加载', 'type': 'boolean', 'default': True},
        ],
    },
    'authorized_key': {
        'title': 'SSH 公钥',
        'desc': '管理用户的 authorized_keys（对标 authorized_key）',
        'fields': [
            {'name': 'user', 'label': '用户', 'type': 'text', 'required': True,
             'placeholder': 'root'},
            {'name': 'public_key', 'label': '公钥内容', 'type': 'textarea', 'required': True,
             'placeholder': 'ssh-ed25519 AAAA... user@host'},
            {'name': 'present', 'label': '存在', 'type': 'boolean', 'default': True},
            {'name': 'comment', 'label': '备注（用于删除时定位）', 'type': 'text'},
        ],
    },
    'service_script': {
        'title': '执行脚本',
        'desc': '上传并执行本地脚本（对标 script）',
        'fields': [
            {'name': 'script', 'label': '脚本内容', 'type': 'textarea', 'required': True,
             'placeholder': '#!/bin/bash\nset -e\necho hello'},
            {'name': 'args', 'label': '参数', 'type': 'text', 'placeholder': '--force'},
            {'name': 'interpreter', 'label': '解释器', 'type': 'text', 'default': 'bash'},
        ],
    },
    'pip': {
        'title': 'Python 包',
        'desc': 'pip 安装/卸载 Python 包（对标 pip）',
        'fields': [
            {'name': 'packages', 'label': '包名', 'type': 'text', 'required': True,
             'placeholder': 'requests, flask（逗号分隔）'},
            {'name': 'present', 'label': '安装', 'type': 'boolean', 'default': True},
            {'name': 'virtualenv', 'label': '虚拟环境路径', 'type': 'text',
             'placeholder': '可选，如 /opt/app/venv'},
            {'name': 'extra_args', 'label': '额外参数', 'type': 'text',
             'placeholder': '-i https://pypi.tuna.tsinghua.edu.cn/simple'},
        ],
    },
    'git_repo': {
        'title': 'Git 仓库',
        'desc': '克隆/更新远端 Git 仓库（对标 git）',
        'fields': [
            {'name': 'src', 'label': '仓库地址', 'type': 'text', 'required': True,
             'placeholder': 'https://github.com/org/repo.git'},
            {'name': 'dest', 'label': '本地路径', 'type': 'text', 'required': True,
             'placeholder': '/opt/app'},
            {'name': 'branch', 'label': '分支/标签', 'type': 'text', 'placeholder': 'main'},
            {'name': 'update', 'label': '已存在时更新', 'type': 'boolean', 'default': True},
            {'name': 'pull', 'label': '强制 pull', 'type': 'boolean', 'default': False},
        ],
    },
    'reboot': {
        'title': '重启主机',
        'desc': '重启目标主机并等待恢复（对标 reboot）',
        'fields': [
            {'name': 'timeout', 'label': '等待超时(秒)', 'type': 'number', 'default': 300},
        ],
    },
    'wait': {
        'title': '等待',
        'desc': '等待端口/文件/条件就绪（对标 wait_for）',
        'fields': [
            {'name': 'port', 'label': '端口', 'type': 'number', 'placeholder': '如 80'},
            {'name': 'path', 'label': '文件路径', 'type': 'text',
             'placeholder': '等待该文件出现'},
            {'name': 'timeout', 'label': '超时(秒)', 'type': 'number', 'default': 300},
        ],
    },
    'apt_repo': {
        'title': 'APT 软件源',
        'desc': '管理 Debian 系软件源（对标 apt_repository）',
        'fields': [
            {'name': 'name', 'label': '源名称', 'type': 'text', 'required': True,
             'placeholder': 'nginx'},
            {'name': 'src', 'label': '源地址', 'type': 'text', 'required': True,
             'placeholder': 'deb http://nginx.org/packages/ubuntu/ noble nginx'},
            {'name': 'present', 'label': '启用', 'type': 'boolean', 'default': True},
        ],
    },
    'yum_repo': {
        'title': 'YUM 软件源',
        'desc': '管理 RedHat 系软件源（对标 yum_repository）',
        'fields': [
            {'name': 'name', 'label': '源名称', 'type': 'text', 'required': True},
            {'name': 'baseurl', 'label': '仓库地址', 'type': 'text', 'required': True},
            {'name': 'gpgcheck', 'label': '校验 GPG', 'type': 'boolean', 'default': False},
            {'name': 'present', 'label': '启用', 'type': 'boolean', 'default': True},
        ],
    },
}


def _as_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value).replace('\n', ',').split(',') if x.strip()]


def _mode(value):
    if value in (None, ''):
        return None
    return value


def _sh(value):
    """把路径安全地嵌入 shell 脚本（单引号转义）。"""
    return "'" + str(value).replace("'", "'\\''") + "'"


@operation()
def _copy_op(src: str, dest: str, move: bool = False):
    """复制/移动（Ansible copy 语义），基于远端实际状态判断，重复执行不变更。

    pyinfra 自带的 files.copy 只支持「复制进已存在的目录」，不支持 dest 指定文件名；
    这里在 prepare 阶段用 Fact 判断目标是否已一致，一致则不产生任何命令。
    """
    from pyinfra.facts.files import Directory, File

    src_is_dir = host.get_fact(Directory, path=src)
    src_is_file = host.get_fact(File, path=src)
    if not src_is_dir and not src_is_file:
        raise OperationError(f'源路径不存在: {src}')

    # dest 以 / 结尾或远端已是目录：放进该目录；否则视为完整目标路径（可重命名）
    dest_is_dir = host.get_fact(Directory, path=dest)
    if dest_is_dir or dest.endswith('/'):
        target = posixpath.join(dest.rstrip('/') or '/', posixpath.basename(src.rstrip('/')))
    else:
        target = dest

    if src_is_file:
        target_exists = host.get_fact(File, path=target)
        if target_exists:
            same = host.get_fact(Sha256File, path=src) == host.get_fact(Sha256File, path=target)
            if same and not move:
                host.noop(f'{target} 已与源一致')
                return
            if same and move:
                # 内容一致但要求移动：删源即可
                yield StringCommand('rm', '-f', QuoteString(src))
                return
    else:
        # 目录：目标已存在时按内容比对，一致则跳过
        if host.get_fact(Directory, path=target):
            host.noop(f'{target} 已存在')
            return

    parent = posixpath.dirname(target)
    if parent:
        yield StringCommand('mkdir', '-p', QuoteString(parent))
    cmd = 'mv' if move else 'cp -a'
    yield StringCommand(cmd, QuoteString(src), QuoteString(target))


@operation()
def _unarchive_op(src: str, dest: str, creates=None, strip_components=None):
    """解压归档到目标目录，creates 已存在时跳过（保证幂等）。"""
    from pyinfra.facts.files import Directory, File

    if not host.get_fact(File, path=src):
        raise OperationError(f'压缩包不存在: {src}')
    if creates and host.get_fact(File, path=creates):
        host.noop(f'{creates} 已存在，跳过解压')
        return
    yield StringCommand('mkdir', '-p', QuoteString(dest))
    opts = ['--strip-components=%d' % int(strip_components)] if strip_components else []
    yield StringCommand('tar', 'xf', QuoteString(src), '-C', QuoteString(dest), *opts)


def _regex_flags(value):
    if not value:
        return None
    flags = []
    for name in str(value).replace('|', ',').split(','):
        name = name.strip().upper()
        if name and hasattr(re, name):
            flags.append(name)
    return flags or None


def normalize(module, params):
    """表单参数归一化，避免 UI 传来的字符串直接进入 operation。"""
    if isinstance(params, str):
        try:
            params = json.loads(params or '{}')
        except ValueError:
            params = {}
    params = dict(params or {})
    for key in ('present', 'latest', 'recursive', 'running', 'enabled', 'restarted',
                'system', 'persist', 'force', 'move', 'remote_src', 'update', 'pull',
                'gpgcheck'):
        if key in params:
            value = params[key]
            if isinstance(value, str):
                params[key] = value.lower() in ('1', 'true', 'yes', 'on')
    if module == 'pkg':
        params['packages'] = _as_list(params.get('packages'))
    elif module == 'service':
        params['name'] = (params.get('name') or '').strip()
    elif module == 'user':
        params['groups'] = _as_list(params.get('groups'))
    return params


def _pkg_family(facts):
    family = (facts.get('os_family') or '').lower()
    if family in ('debian', 'ubuntu'):
        return 'debian'
    if family in ('redhat', 'centos', 'fedora', 'rocky', 'almalinux'):
        return 'redhat'
    if family in ('alpine',):
        return 'alpine'
    # 兜底：按 os 名称再猜一次
    os_name = (facts.get('os') or '').lower()
    if 'alpine' in os_name:
        return 'alpine'
    if 'debian' in os_name or 'ubuntu' in os_name:
        return 'debian'
    return 'redhat'


def _pkg_backend(facts):
    """RedHat 系还要区分 yum / dnf：CentOS 7 及更早只有 yum。

    判断顺序：
      1. 直接探测（facts 里带 which_dnf / which_yum）最可靠；
      2. 否则按发行版大版本：CentOS/RHEL < 8 用 yum，其余用 dnf。
    """
    if facts.get('which_dnf'):
        return 'dnf'
    if facts.get('which_yum'):
        return 'yum'
    os_name = (facts.get('os') or '').lower()
    os_version = (facts.get('os_version') or '').split('.')[0]
    old = any(x in os_name for x in ('centos', 'red hat', 'redhat', 'rhel')) and os_version.isdigit() and int(os_version) < 8
    return 'yum' if old else 'dnf'


def _is_systemd(facts):
    return (facts.get('os_family') or '').lower() not in ('alpine',)


def build_plan(hosts, module, params, facts_map):
    """返回 [(op_func, kwargs, [host, ...]), ...]，同一批主机按发行版拆组。"""
    params = normalize(module, params)
    if module == 'pkg':
        groups = {}
        for host in hosts:
            facts = facts_map.get(host.id, {}) or {}
            family = _pkg_family(facts)
            # RedHat 系再按 yum/dnf 可用性拆组，CentOS 7 只有 yum
            key = family if family != 'redhat' else f'redhat-{_pkg_backend(facts)}'
            groups.setdefault(key, []).append(host)
        plan = []
        funcs = {
            'debian': apt.packages,
            'redhat-dnf': dnf.packages,
            'redhat-yum': yum.packages,
            'alpine': apk.packages,
        }
        for family, family_hosts in groups.items():
            func = funcs.get(family) or apt.packages
            kwargs = {
                'packages': params.get('packages') or [],
                'present': params.get('present', True),
                'latest': params.get('latest', False),
            }
            # apt 支持 update；yum/dnf 的 update 语义不同，不传
            if family == 'debian' and params.get('update'):
                kwargs['update'] = True
                # cache_time：更新戳记较新时跳过 apt-get update，保证幂等
                if params.get('cache_time'):
                    kwargs['cache_time'] = int(params['cache_time'])
            plan.append((func, kwargs, family_hosts))
        return plan

    if module == 'service':
        # systemd 与 sysvinit 分开建 op，避免混用导致命令不可用
        sd_hosts = [h for h in hosts if _is_systemd(facts_map.get(h.id, {}))]
        sysv_hosts = [h for h in hosts if h not in sd_hosts]
        plan = []
        base = {
            'service': params.get('name'),
            'running': params.get('running', True),
            'enabled': params.get('enabled'),
        }
        if params.get('restarted'):
            base['restarted'] = True
        if sd_hosts:
            plan.append((systemd.service, dict(base), sd_hosts))
        if sysv_hosts:
            plan.append((sysvinit.service, dict(base), sysv_hosts))
        return plan

    if module == 'file':
        if params.get('content') is not None and params.get('present', True):
            kwargs = {
                'src': StringIO(params.get('content')),
                'dest': params.get('path'),
                'user': params.get('owner'),
                'group': params.get('group'),
                'mode': _mode(params.get('mode')),
            }
            return [(files.put, kwargs, hosts)]
        kwargs = {
            'path': params.get('path'),
            'present': params.get('present', True),
            'user': params.get('owner'),
            'group': params.get('group'),
            'mode': _mode(params.get('mode')),
        }
        return [(files.file, kwargs, hosts)]

    if module == 'directory':
        kwargs = {
            'path': params.get('path'),
            'present': params.get('present', True),
            'user': params.get('owner'),
            'group': params.get('group'),
            'mode': _mode(params.get('mode')),
            'recursive': params.get('recursive', False),
        }
        return [(files.directory, kwargs, hosts)]

    if module == 'user':
        kwargs = {
            'user': params.get('username'),
            'present': params.get('present', True),
            'home': params.get('home') or None,
            'shell': params.get('shell') or None,
            'groups': params.get('groups') or None,
        }
        if params.get('password'):
            kwargs['password'] = params['password']
        return [(server.user, kwargs, hosts)]

    if module == 'group':
        kwargs = {
            'group': params.get('group'),
            'present': params.get('present', True),
            'system': params.get('system', False),
        }
        return [(server.group, kwargs, hosts)]

    if module == 'command':
        commands = params.get('commands')
        if isinstance(commands, str):
            commands = [x for x in commands.splitlines() if x.strip()]
        if not commands:
            raise ValueError('命令内容不能为空')
        return [(server.shell, {'commands': commands}, hosts)]

    if module == 'line':
        kwargs = {
            'path': params.get('path'),
            'line': params.get('line'),
            'present': params.get('present', True),
        }
        if params.get('replace'):
            kwargs['replace'] = params['replace']
        return [(files.line, kwargs, hosts)]

    if module == 'block':
        kwargs = {
            'path': params.get('path'),
            'content': params.get('content'),
            'present': params.get('present', True),
        }
        # pyinfra 的 marker 是带 {mark} 占位符的模板，begin/end 只填充占位符；
        # 直接传纯名称会导致前后分隔符相同而报错
        marker = params.get('marker')
        if marker:
            kwargs['marker'] = f'# {marker} {{mark}}'
            kwargs['begin'] = 'BEGIN'
            kwargs['end'] = 'END'
        return [(files.block, kwargs, hosts)]

    if module == 'sysctl':
        kwargs = {
            'key': params.get('key'),
            'value': params.get('value'),
            'persist': params.get('persist', True),
        }
        return [(server.sysctl, kwargs, hosts)]

    if module == 'crontab':
        base = {
            'command': params.get('command'),
            'present': params.get('present', True),
        }
        if params.get('cron_name'):
            base['cron_name'] = params['cron_name']
        if params.get('user'):
            base['user'] = params['user']
        for key in ('minute', 'hour', 'day_of_month', 'month', 'day_of_week'):
            value = params.get(key)
            if value not in (None, ''):
                base[key] = value
        if not params.get('user'):
            return [(crontab.crontab, dict(base), hosts)]
        # 操作其他用户的 crontab 需要 root：按连接用户拆分成不同的 op
        plan = []
        for host in hosts:
            kwargs = dict(base)
            if params['user'] != (host.username or 'root'):
                kwargs['_sudo'] = True
            plan.append((crontab.crontab, kwargs, [host]))
        return plan

    if module == 'download':
        src = params.get('src') or ''
        dest = params.get('dest') or ''
        # pyinfra 的 download 要求 dest 是文件路径：以 / 结尾时自动补文件名
        if dest.endswith('/'):
            name = src.rstrip('/').split('/')[-1] or 'download'
            dest = dest + name
        kwargs = {
            'src': src,
            'dest': dest,
            'force': params.get('force', False),
        }
        if params.get('md5sum'):
            kwargs['md5sum'] = params['md5sum']
        return [(files.download, kwargs, hosts)]

    # ---------------- 以下对标 Ansible 高频模块 ----------------
    if module == 'link':
        kwargs = {
            'path': params.get('path'),
            'target': params.get('target'),
            'present': params.get('present', True),
        }
        # force 会先删除再重建，导致每次都判定 changed；仅在用户显式要求时启用
        if params.get('force'):
            kwargs['force'] = True
        if params.get('owner'):
            kwargs['user'] = params['owner']
        if params.get('group'):
            kwargs['group'] = params['group']
        return [(files.link, kwargs, hosts)]

    if module == 'unarchive':
        # 仅支持远端已存在的压缩包，避免与「数据传输」职责重叠
        if not params.get('remote_src', True):
            raise ValueError('解压模块仅支持远端已存在的压缩包，请先用「数据传输」上传')
        return [(_unarchive_op, {
            'src': params.get('src'),
            'dest': params.get('dest'),
            'creates': params.get('creates') or None,
            'strip_components': params.get('strip_components') or None,
        }, hosts)]

    if module == 'copy':
        return [(_copy_op, {
            'src': params.get('src'),
            'dest': params.get('dest'),
            'move': params.get('move', False),
        }, hosts)]

    if module == 'replace':
        kwargs = {
            'path': params.get('path'),
            'text': params.get('match'),
            'replace': params.get('replace'),
        }
        flags = _regex_flags(params.get('flags'))
        if flags:
            kwargs['flags'] = flags
        return [(files.replace, kwargs, hosts)]

    if module == 'fetch':
        # 服务端保存目录：默认落在 data/downloads/<host_id>/ 下
        dest = params.get('dest')
        plan = []
        for host in hosts:
            kwargs = {
                'src': params.get('src'),
                'dest': os.path.join(dest, str(host.id)) if dest else None,
            }
            if not dest:
                from django.conf import settings
                kwargs['dest'] = os.path.join(str(settings.DATA_DIR), 'downloads', str(host.id))
            plan.append((files.get, kwargs, [host]))
        return plan

    if module == 'mount':
        kwargs = {
            'path': params.get('path'),
            'device': params.get('device'),
            'present': params.get('present', True),
        }
        if params.get('fstype'):
            kwargs['fstype'] = params['fstype']
        if params.get('options'):
            kwargs['options'] = params['options']
        return [(server.mount, kwargs, hosts)]

    if module == 'timezone':
        return [(server.timezone, {'timezone': params.get('timezone')}, hosts)]

    if module == 'hostname':
        return [(server.hostname, {'hostname': params.get('hostname')}, hosts)]

    if module == 'etc_hosts':
        kwargs = {
            'ip': params.get('ip'),
            'hostnames': _as_list(params.get('hostnames')),
            'present': params.get('present', True),
        }
        return [(server.etc_hosts, kwargs, hosts)]

    if module == 'modprobe':
        # pyinfra 的 modprobe 参数名是 module，且没有 persist：
        # 持久化需额外写 /etc/modules-load.d，这里用 files.line 完成
        present = params.get('present', True)
        plan = [(server.modprobe, {'module': params.get('name'), 'present': present}, hosts)]
        if present and params.get('persist', True):
            plan.append((files.line, {
                'path': '/etc/modules-load.d/spug.conf',
                'line': params.get('name'),
                'present': True,
            }, hosts))
        return plan

    if module == 'authorized_key':
        kwargs = {
            'user': params.get('user'),
            'public_keys': params.get('public_key'),
            'present': params.get('present', True),
        }
        if params.get('comment'):
            kwargs['comment'] = params['comment']
        return [(server.user_authorized_keys, kwargs, hosts)]

    if module == 'service_script':
        script = params.get('script') or ''
        if not script.strip():
            raise ValueError('脚本内容不能为空')
        if not script.startswith('#!'):
            script = f'#!{params.get("interpreter") or "bash"}\n{script}'
        kwargs = {'src': StringIO(script)}
        if params.get('args'):
            kwargs['args'] = params['args']
        return [(server.script, kwargs, hosts)]

    if module == 'pip':
        kwargs = {
            'packages': _as_list(params.get('packages')),
            'present': params.get('present', True),
        }
        if params.get('virtualenv'):
            kwargs['virtualenv'] = params['virtualenv']
        if params.get('extra_args'):
            kwargs['extra_args'] = params['extra_args']
        return [(pip.packages, kwargs, hosts)]

    if module == 'git_repo':
        kwargs = {
            'src': params.get('src'),
            'dest': params.get('dest'),
            'update': params.get('update', True),
            'pull': params.get('pull', False),
        }
        if params.get('branch'):
            kwargs['branch'] = params['branch']
        return [(git.repo, kwargs, hosts)]

    if module == 'reboot':
        return [(server.reboot, {'timeout': int(params.get('timeout') or 300)}, hosts)]

    if module == 'wait':
        kwargs = {}
        if params.get('port'):
            kwargs['port'] = int(params['port'])
        if params.get('path'):
            kwargs['path'] = params['path']
        if not kwargs:
            raise ValueError('端口与文件路径至少填写一个')
        kwargs['timeout'] = int(params.get('timeout') or 300)
        return [(server.wait, kwargs, hosts)]

    if module == 'apt_repo':
        return [(apt.repo, {
            'name': params.get('name'),
            'src': params.get('src'),
            'present': params.get('present', True),
        }, hosts)]

    if module == 'yum_repo':
        return [(yum.repo, {
            'name': params.get('name'),
            'baseurl': params.get('baseurl'),
            'gpgcheck': params.get('gpgcheck', False),
            'present': params.get('present', True),
        }, hosts)]

    raise ValueError(f'不支持的状态模块: {module}')
