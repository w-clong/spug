# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一状态模块注册表（对标 Ansible Module）。

每个模块向 UI 暴露一份字段描述（MODULE_SCHEMA），并负责把表单参数翻译成
pyinfra 原生 operation。禁止 subprocess / CLI，全部同进程调用。
"""
import json
from io import StringIO

from pyinfra.operations import (apk, apt, crontab, dnf, files, server, systemd,
                                sysvinit, yum)

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


def normalize(module, params):
    """表单参数归一化，避免 UI 传来的字符串直接进入 operation。"""
    if isinstance(params, str):
        try:
            params = json.loads(params or '{}')
        except ValueError:
            params = {}
    params = dict(params or {})
    for key in ('present', 'latest', 'recursive', 'running', 'enabled', 'restarted',
                'system', 'persist', 'force'):
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


def _is_systemd(facts):
    return (facts.get('os_family') or '').lower() not in ('alpine',)


def build_plan(hosts, module, params, facts_map):
    """返回 [(op_func, kwargs, [host, ...]), ...]，同一批主机按发行版拆组。"""
    params = normalize(module, params)
    if module == 'pkg':
        groups = {}
        for host in hosts:
            groups.setdefault(_pkg_family(facts_map.get(host.id, {})), []).append(host)
        plan = []
        funcs = {'debian': apt.packages, 'redhat': dnf.packages, 'alpine': apk.packages}
        for family, family_hosts in groups.items():
            func = funcs.get(family) or apt.packages
            kwargs = {
                'packages': params.get('packages') or [],
                'present': params.get('present', True),
                'latest': params.get('latest', False),
            }
            # apt 支持 update；dnf 的 update 语义不同，不传
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
        if params.get('marker'):
            kwargs['marker'] = params['marker']
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
        kwargs = {
            'src': params.get('src'),
            'dest': params.get('dest'),
            'force': params.get('force', False),
        }
        if params.get('md5sum'):
            kwargs['md5sum'] = params['md5sum']
        return [(files.download, kwargs, hosts)]

    raise ValueError(f'不支持的状态模块: {module}')
