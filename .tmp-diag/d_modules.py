"""新状态模块的 build_plan 构造检查（不连主机）。"""
import os
import sys

sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django  # noqa: E402

django.setup()

from apps.ops.kernel.modules import MODULE_SCHEMA, build_plan  # noqa: E402


class H:
    def __init__(self, i=1):
        self.id = i


hosts = [H(1)]
cases = {
    'link': {'path': '/tmp/x', 'target': '/tmp/y'},
    'unarchive': {'src': '/tmp/a.tar.gz', 'dest': '/tmp/out'},
    'copy': {'src': '/tmp/a', 'dest': '/tmp/b'},
    'replace': {'path': '/tmp/f', 'match': 'a', 'replace': 'b', 'flags': 'MULTILINE'},
    'mount': {'path': '/data', 'device': '/dev/sdb1', 'fstype': 'ext4'},
    'timezone': {'timezone': 'Asia/Shanghai'},
    'hostname': {'hostname': 'web1'},
    'etc_hosts': {'ip': '1.2.3.4', 'hostnames': 'a.local, b.local'},
    'modprobe': {'name': 'br_netfilter'},
    'authorized_key': {'user': 'root', 'public_key': 'ssh-ed25519 AAAA x'},
    'service_script': {'script': 'echo hi', 'interpreter': 'bash'},
    'pip': {'packages': 'requests, flask'},
    'git_repo': {'src': 'https://x/y.git', 'dest': '/opt/y'},
    'reboot': {'timeout': 120},
    'wait': {'port': 80},
    'apt_repo': {'name': 'nginx', 'src': 'deb http://x noble nginx'},
    'yum_repo': {'name': 'epel', 'baseurl': 'http://x/epel'},
}

missing = [k for k in cases if k not in MODULE_SCHEMA]
print('未注册 schema:', missing or '无')

fail = 0
for name, params in cases.items():
    try:
        plan = build_plan(hosts, name, params, {1: {'os_family': 'Debian'}})
        func, kwargs, op_hosts = plan[0]
        print('%-16s -> %-22s %s' % (name, func.__name__, sorted(kwargs.keys())))
    except Exception as e:
        fail += 1
        print('%-16s -> 失败: %s: %s' % (name, type(e).__name__, e))

print('\nschema 总数:', len(MODULE_SCHEMA), '构造失败:', fail)
