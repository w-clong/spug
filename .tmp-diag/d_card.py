"""复现：数据传输目标路径填 /tmp（不带结尾 /），单文件来源。"""
import os
import sys
import types

sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
DATA = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
os.environ['SPUG_DATA_DIR'] = DATA
import django  # noqa: E402

django.setup()

from apps.deploy import ext2  # noqa: E402
from apps.deploy.helper import SpugError  # noqa: E402
from apps.host.models import Host  # noqa: E402
from libs.utils import AttrDict  # noqa: E402

IP, PWD, USR = sys.argv[1], sys.argv[2], sys.argv[3]
ZIP = r'C:\Users\wcl\APP\安装包\brynhildr30702.zip'


class H:
    def __init__(self):
        self.errors = []

    def _p(self, k, m):
        t = str(m).replace('\r', '').strip()
        if t:
            print('  [%s] %s' % (k, t[:180]))

    def send_info(self, k, m, **kw):
        self._p('info', m)

    def send_success(self, k, m, **kw):
        self._p('ok', m)

    def send_error(self, k, m, **kw):
        self.errors.append(str(m))
        self._p('ERROR', m)
        raise SpugError(m)

    def send_clear(self, k):
        pass

    def set_deploy_process(self, k):
        pass

    def save_pid(self, pid, k):
        pass

    def progress_callback(self, k):
        return lambda *a: None

    def remote(self, k, ssh, command, env=None):
        self._p('cmd', 'REMOTE> ' + command.replace('\n', ' | '))
        code = -1
        for code, out in ssh.exec_command_with_stream(command, environment=env):
            if out and out.strip():
                self._p('out', out)
        if code != 0:
            self.send_error(k, 'exit code: %s' % code)

    def parse_filter_rule(self, r, s, e):
        return []


def main():
    host = Host(id=999, name='x', hostname=IP, port=22, username=USR)
    host.password = PWD
    ext2.Host.objects.filter = lambda **kw: types.SimpleNamespace(first=lambda: host)
    ext2.REPOS_DIR = os.path.join(DATA, 'repos')
    os.makedirs(os.path.join(ext2.REPOS_DIR, '1'), exist_ok=True)
    env = AttrDict(SPUG_DEPLOY_ID='1')
    helper = H()

    # 用户配置：src=本地 zip，dst=/tmp（无结尾斜杠），mode=0
    actions = [{'type': 'transfer', 'title': '数据传输', 'src_mode': '0',
                'src': ZIP, 'dst': '/tmp', 'mode': '0', 'rule': '', 'name': ''}]
    print('=== 目标路径 /tmp ===')
    try:
        ext2._deploy_ext2_host(helper, 999, actions, env, 'probe')
        print('结果: 成功')
    except Exception as e:
        print('结果: 异常 ->', type(e).__name__, e)

    print('\n=== 目标路径 /tmp/ ===')
    helper2 = H()
    actions2 = [dict(actions[0], dst='/tmp/')]
    try:
        ext2._deploy_ext2_host(helper2, 999, actions2, env, 'probe2')
        print('结果: 成功')
    except Exception as e:
        print('结果: 异常 ->', type(e).__name__, e)


main()
