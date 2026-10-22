# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""真实 Linux 主机 E2E 验证（pyinfra 同进程 + 密码认证 + 状态模块）。

用法：
    cd spug_api
    $env:SPUG_DATA_DIR="C:\\path\\to\\data"
    ..\\.venv-win\\Scripts\\python.exe apps\\ops\\e2e_linux.py 10.0.0.34 root 1 10.0.0.35 wcl 123456
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.ops.kernel.facts_runner import refresh  # noqa: E402
from apps.ops.kernel.runner import StateRunner  # noqa: E402

TEST_FILE = '/tmp/spug-e2e/hello.txt'
TEST_DIR = '/tmp/spug-e2e'


def ensure_hosts(args):
    user = User.objects.filter(username='e2e').first()
    if user is None:
        user = User.objects.create(username='e2e', nickname='e2e', password_hash='x', is_supper=True)
    hosts = []
    for i in range(0, len(args), 3):
        ip, username, password = args[i], args[i + 1], args[i + 2]
        host, _ = Host.objects.update_or_create(
            name=f'e2e-{ip}',
            defaults=dict(hostname=ip, port=22, username=username, password=password,
                          pkey=None, created_by=user))
        hosts.append(host)
    return hosts


def show(title, summary):
    print(f'\n== {title} ==')
    for item in summary.results:
        print(f'  {item.host_name}: changed={item.changed} failed={item.failed} msg={(item.msg or "").splitlines()[0][:80]}')
    return summary


def cleanup(hosts):
    StateRunner(hosts, 'file', {'path': TEST_FILE, 'present': False}, record=False).run()
    StateRunner(hosts, 'directory', {'path': TEST_DIR, 'present': False}, record=False).run()


def main(args):
    hosts = ensure_hosts(args)
    print('hosts:', [(x.name, x.hostname, x.username) for x in hosts])
    cleanup(hosts)

    facts = refresh(hosts)
    for host in hosts:
        item = facts.get(host.id, {})
        print(f'FACTS {host.hostname}: os={item.get("os")} family={item.get("os_family")} '
              f'version={item.get("os_version")} arch={item.get("arch")}')
    families = {host.hostname: facts.get(host.id, {}).get('os_family') for host in hosts}
    assert 'RedHat' in families.values(), families
    assert 'Debian' in families.values(), families

    # 1. 目录：dry-run 应显示将变更，真实执行后 changed=True，再次执行幂等
    dry = show('directory dry-run', StateRunner(hosts, 'directory', {'path': TEST_DIR}, dry_run=True, record=False).run())
    assert any(x.changed for x in dry.results), 'dry-run 未检测到变更'

    first = show('directory apply', StateRunner(hosts, 'directory', {'path': TEST_DIR}, record=False).run())
    assert all(x.changed and not x.failed for x in first.results), '首次创建目录未产生变更'

    again = show('directory idempotent', StateRunner(hosts, 'directory', {'path': TEST_DIR}, record=False).run())
    assert not any(x.changed or x.failed for x in again.results), '目录重复执行不幂等'

    # 2. 文件内容
    file_first = show('file content apply', StateRunner(
        hosts, 'file', {'path': TEST_FILE, 'content': 'hello from spug pyinfra\n', 'mode': '0644'},
        record=False).run())
    assert all(x.changed and not x.failed for x in file_first.results), '文件内容未写入'
    file_again = show('file content idempotent', StateRunner(
        hosts, 'file', {'path': TEST_FILE, 'content': 'hello from spug pyinfra\n', 'mode': '0644'},
        record=False).run())
    assert not any(x.changed or x.failed for x in file_again.results), '文件内容重复执行不幂等'

    # 2.5 Jinja2 模板：按主机 Facts + 主机变量渲染，内容相同的主机合并 op
    from apps.ops.models import ConfigTemplate, HostVariable
    tpl_path = '/tmp/spug-tpl-e2e'
    tpl = ConfigTemplate.objects.create(
        name='e2e-template',
        content='host={{ hostname }} family={{ os_family }} version={{ os_version }} '
                'port={{ nginx_port | default("80") }}',
        created_by=hosts[0].created_by)
    HostVariable.objects.update_or_create(
        host_id=hosts[1].id, key='nginx_port', defaults={'value': '8080'})
    tpl_res = show('file template apply', StateRunner(
        hosts, 'file', {'path': tpl_path, 'template_id': tpl.id}, record=False).run())
    assert all(not x.failed for x in tpl_res.results), '模板渲染写入失败'
    for host, family, port in ((hosts[0], 'RedHat', '80'), (hosts[1], 'Debian', '8080')):
        with host.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(f'cat {tpl_path}')
        print(f'  rendered {host.hostname}: {out.strip()}')
        assert family in out and f'port={port}' in out, out
    StateRunner(hosts, 'file', {'path': tpl_path, 'present': False}, record=False).run()
    tpl.delete()
    HostVariable.objects.filter(host_id=hosts[1].id, key='nginx_port').delete()

    # 3. 服务模块（只读检查）：两个发行版服务名不同，已运行/已开机自启应无变更
    for host, svc_name in zip(hosts, ('sshd', 'ssh')):
        svc = show(f'service check ({host.hostname}/{svc_name})', StateRunner(
            [host], 'service', {'name': svc_name, 'running': True, 'enabled': True},
            dry_run=True, record=False).run())
        assert not any(x.failed for x in svc.results), '服务模块执行失败'

    # 4. 软件包 dry-run（只计算命令，不安装）；cowsay 在两个发行版上均未安装
    pkg = show('pkg dry-run (cowsay)', StateRunner(
        hosts, 'pkg', {'packages': ['cowsay'], 'present': True}, dry_run=True, record=False).run())
    assert all(x.changed for x in pkg.results), 'pkg dry-run 未计算出变更命令'

    # 5. 新增高频状态模块真实执行
    e2e_dir = '/tmp/spug-mod-e2e'
    line_path = f'{e2e_dir}/selinux.conf'
    block_path = f'{e2e_dir}/hosts'
    # group / command / line / block / sysctl / crontab / download
    # 先清理上次中断留下的状态，保证 changed 断言有效
    StateRunner([hosts[0]], 'group', {'group': 'spugtest', 'present': False}, record=False).run()
    StateRunner(hosts, 'crontab', {'command': '/bin/true', 'cron_name': 'spug-e2e',
                                   'present': False, 'user': 'root'},
                sudo=True, sudo_password='1', record=False).run()
    StateRunner(hosts, 'command', {'commands': f'rm -rf {e2e_dir}'}, record=False).run()

    r = show('group create', StateRunner(
        [hosts[0]], 'group', {'group': 'spugtest', 'present': True}, record=False).run())
    assert all(not x.failed for x in r.results) and r.results[0].changed

    r = show('command exec', StateRunner(
        hosts, 'command', {'commands': f'mkdir -p {e2e_dir}'}, record=False).run())
    assert all(not x.failed for x in r.results)

    r = show('line manage', StateRunner(
        hosts, 'line', {'path': line_path, 'line': 'SPUG_TEST=on'}, record=False).run())
    assert all(x.changed and not x.failed for x in r.results), 'line 首次未变更'
    r = show('line idempotent', StateRunner(
        hosts, 'line', {'path': line_path, 'line': 'SPUG_TEST=on'}, record=False).run())
    assert not any(x.changed for x in r.results), 'line 重复执行不幂等'

    r = show('block manage', StateRunner(
        hosts, 'block', {'path': block_path, 'content': '10.1.1.1 spugtest.local'},
        record=False).run())
    assert all(x.changed and not x.failed for x in r.results)

    r = show('sysctl set', StateRunner(
        hosts, 'sysctl', {'key': 'net.ipv4.ip_forward', 'value': '1', 'persist': False},
        dry_run=True, record=False).run())
    assert all(not x.failed for x in r.results), 'sysctl dry-run 失败'

    r = show('crontab manage', StateRunner(
        hosts, 'crontab', {'command': '/bin/true', 'cron_name': 'spug-e2e',
                           'minute': '0', 'hour': '3', 'user': 'root'},
        sudo=True, sudo_password='1', record=False).run())
    assert all(not x.failed for x in r.results), 'crontab 失败'

    r = show('download file', StateRunner(
        hosts, 'download', {'src': 'http://192.168.10.240:4000/raw/root.crt',
                            'dest': f'{e2e_dir}/root.crt'}, record=False).run())
    assert all(not x.failed for x in r.results), 'download 失败'
    for host in hosts:
        with host.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(f'ls -l {e2e_dir}/root.crt')
        print(f'  downloaded {host.hostname}: {out.strip()}')
        assert code == 0

    # 6. 清理
    StateRunner([hosts[0]], 'group', {'group': 'spugtest', 'present': False}, record=False).run()
    StateRunner(hosts, 'crontab', {'command': '/bin/true', 'cron_name': 'spug-e2e',
                                   'present': False, 'user': 'root'},
                sudo=True, sudo_password='1', record=False).run()
    StateRunner(hosts, 'command', {'commands': f'rm -rf {e2e_dir}'}, record=False).run()
    cleanup(hosts)
    print('\nE2E passed')


if __name__ == '__main__':
    main(sys.argv[1:])
