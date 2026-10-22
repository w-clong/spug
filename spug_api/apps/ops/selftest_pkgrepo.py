# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""制品源 rpm / deb 自检：写远端源配置 + pyinfra pkg 模块安装。

repo：http://192.168.10.240:4000/rpm/myrepo 与 /deb/ubuntu（NORA）
主机：10.0.0.34 Rocky9 root、10.0.0.35 Ubuntu24.04 wcl（sudo 密码 = SSH 密码）
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.pipeline.models import Pipeline  # noqa: E402
from apps.pipeline.utils import NodeExecutor  # noqa: E402
from libs.memredis import get_redis_connection  # noqa: E402

NORA = 'http://192.168.10.240:4000'
NODE_ID = 9100


class RecordingHelper:
    def __init__(self):
        self.logs = []

    def send(self, key, data=None, **kwargs):
        self.logs.append((key, data))

    def send_info(self, key, msg, *args, **kwargs):
        self.logs.append((key, msg))

    def send_success(self, key, msg, *args, **kwargs):
        self.logs.append((key, msg))

    def send_error(self, key, msg, *args, **kwargs):
        self.logs.append((key, msg))

    def send_status(self, key, status):
        self.logs.append((key, status))

    def clear(self):
        pass


def get_hosts():
    user = User.objects.filter(username='pkgrepo-tester').first() or User.objects.create(
        username='pkgrepo-tester', nickname='pkgrepo', password_hash='x', is_supper=True)
    hosts = {}
    for name, ip, username, password in (
            ('pkgrepo-rocky', '10.0.0.34', 'root', '1'),
            ('pkgrepo-ubuntu', '10.0.0.35', 'wcl', '123456')):
        host, _ = Host.objects.update_or_create(
            name=name,
            defaults=dict(hostname=ip, port=22, username=username, password=password,
                          pkey=None, created_by=user))
        hosts[ip] = host
    return user, hosts


def run_node(pipe, host, node, dry_run=False):
    executor = NodeExecutor(get_redis_connection(), 'pkgrepo-token', [node],
                            pipeline_id=pipe.id, dry_run=dry_run)
    helper = RecordingHelper()
    executor.helper = helper
    executor.run()
    return executor, helper


def base_node(host, source_type, package, extra=None):
    base = NORA + ('/rpm' if source_type == 'rpm' else '/deb')
    node = {
        'id': NODE_ID, 'module': 'artifact', 'name': '制品安装',
        'condition': 'success', 'targets': [host.id],
        'source_type': source_type, 'base_url': base,
        'repo_name': 'myrepo' if source_type == 'rpm' else 'ubuntu',
        'package': package, 'version': '',
        'dest_path': '', 'overwrite': False,
        'auth_type': 'none', 'dry_run': False,
    }
    node.update(extra or {})
    return node


def main():
    user, hosts = get_hosts()
    rocky, ubuntu = hosts['10.0.0.34'], hosts['10.0.0.35']
    Pipeline.objects.filter(name='pkgrepo-pipeline').delete()
    pipe = Pipeline.objects.create(name='pkgrepo-pipeline', created_by=user, nodes='[]')

    try:
        # ---------- rpm ----------
        # 先确保环境干净（包已卸载、无源配置），再验证 changed
        with rocky.get_ssh() as ssh:
            ssh.exec_command_raw('dnf remove -y accountsservice >/dev/null 2>&1; '
                                 'rm -f /etc/yum.repos.d/spug-artifact-%d.repo' % NODE_ID)
        # 注意：若系统其它源已包含同一 URL，节点会跳过写入（防 Trusted 冲突）
        node = base_node(rocky, 'rpm', 'accountsservice')
        executor, helper = run_node(pipe, rocky, node)
        assert executor.states[NODE_ID] == 'changed', executor.states
        text = '\n'.join(str(x[1]) for x in helper.logs)
        # 本机系统已存在指向同一仓库的 local.repo，属预期：跳过写入以避免重复/冲突
        assert ('已写入源配置' in text or '系统已存在相同源配置' in text), text
        if '已写入源配置' in text:
            assert '/etc/yum.repos.d/' in text, text
        assert 'password=' not in text and 'Bearer' not in text, '日志不应包含凭据'
        print('rpm install changed ok')

        executor, helper = run_node(pipe, rocky, node)
        assert executor.states[NODE_ID] == 'success', executor.states
        assert any('无需变更' in str(x[1]) or '已安装' in str(x[1]) for x in helper.logs)
        print('rpm idempotent ok')

        # dry-run：不应写源配置
        with rocky.get_ssh() as ssh:
            ssh.exec_command_raw('rm -f /etc/yum.repos.d/spug-artifact-%d.repo' % NODE_ID)
        executor, helper = run_node(pipe, rocky, node, dry_run=True)
        text = '\n'.join(str(x[1]) for x in helper.logs)
        assert '已写入源配置' not in text, 'dry-run 不应写源配置'
        print('rpm dry-run ok')

        # ---------- deb ----------
        # 先确保环境干净
        with ubuntu.get_ssh() as ssh:
            ssh.exec_command_stdin(
                'sudo -S -p "" sh -c "apt-get remove -y tree >/dev/null 2>&1; '
                'rm -f /etc/apt/sources.list.d/spug-artifact-%d.list"' % NODE_ID,
                stdin_data=(ubuntu.password or '') + '\n')
        node = base_node(ubuntu, 'deb', 'tree', {'suite': 'noble', 'component': 'main'})
        executor, helper = run_node(pipe, ubuntu, node)
        assert executor.states[NODE_ID] == 'changed', executor.states
        text = '\n'.join(str(x[1]) for x in helper.logs)
        assert ('已写入源配置' in text or '系统已存在相同源配置' in text), text
        if '已写入源配置' in text:
            assert '/etc/apt/sources.list.d/' in text, text
        print('deb install changed ok')

        executor, helper = run_node(pipe, ubuntu, node)
        assert executor.states[NODE_ID] == 'success', executor.states
        assert any('无需变更' in str(x[1]) or '已安装' in str(x[1]) for x in helper.logs)
        print('deb idempotent ok')

        # ---------- 校验安装结果与源配置 ----------
        with rocky.get_ssh() as ssh:
            code, out = ssh.exec_command_raw('rpm -q accountsservice')
            assert code == 0, out
            print('rocky verified:', out.strip())
            code, out = ssh.exec_command_raw(
                'grep -rh "baseurl" /etc/yum.repos.d/*.repo 2>/dev/null | grep 240 | head -2')
            assert '192.168.10.240' in out, out
            print('rocky repo config ok:', out.strip().splitlines()[0] if out.strip() else '(none)')

        with ubuntu.get_ssh() as ssh:
            code, out = ssh.exec_command_raw('dpkg -s tree | head -2')
            assert code == 0, out
            print('ubuntu verified:', out.strip().replace('\n', ' | '))
            code, out = ssh.exec_command_raw(
                'grep -rh "192.168.10.240" /etc/apt/sources.list.d/ /etc/apt/sources.list 2>/dev/null | head -2')
            assert '192.168.10.240' in out, out
            print('ubuntu repo config ok:', out.strip().splitlines()[0])

        # ---------- 清理：卸载测试包、删除源配置 ----------
        with rocky.get_ssh() as ssh:
            ssh.exec_command_raw('dnf remove -y accountsservice >/dev/null 2>&1; '
                                 'rm -f /etc/yum.repos.d/spug-artifact-%d.repo' % NODE_ID)
        with ubuntu.get_ssh() as ssh:
            ssh.exec_command_stdin(
                'sudo -S -p "" sh -c "apt-get remove -y tree >/dev/null 2>&1; '
                'rm -f /etc/apt/sources.list.d/spug-artifact-%d.list"' % NODE_ID,
                stdin_data=(ubuntu.password or '') + '\n')
        print('cleanup ok')
    finally:
        pipe.delete()
    print('rpm/deb artifact selftest passed')


if __name__ == '__main__':
    main()
