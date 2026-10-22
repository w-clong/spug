# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""内核自检（不连接真实主机）：验证 Inventory 构建、私钥内存注入、模块分发。

用法（仓库根目录）：
    .venv-win\\Scripts\\python.exe spug_api\\apps\\ops\\kernel\\selftest.py
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from pyinfra.api import Config, State  # noqa: E402

from apps.ops.kernel.inventory import build_inventory, inject_private_keys  # noqa: E402
from apps.ops.kernel.modules import build_plan, normalize  # noqa: E402
from libs.ssh import SSH  # noqa: E402


def main():
    key, _ = SSH.generate_key()
    host = SimpleNamespace(id=1, name='web1', hostname='10.0.0.5', port=22,
                           username='root', pkey=key, password=None)
    inventory, name_map = build_inventory([host])
    py_host = list(inventory)[0]
    assert py_host.data.get('spug_id') == 1
    assert py_host.data.get('ssh_key') == 'spug://key/1'
    print('inventory ok:', py_host.name, name_map)

    state = State(inventory, Config())
    inject_private_keys(state, [host])
    assert 'spug://key/1' in state.private_keys
    print('private key injected in memory ok')

    facts = {1: {'os_family': 'Debian', 'os': 'Linux'}}
    for module, params in [
        ('pkg', {'packages': 'nginx, curl', 'present': True}),
        ('service', {'name': 'nginx', 'enabled': True}),
        ('file', {'path': '/tmp/a.conf', 'content': 'hello'}),
        ('directory', {'path': '/opt/app', 'mode': '0755'}),
        ('user', {'username': 'deploy', 'groups': 'sudo, docker'}),
        ('group', {'group': 'docker'}),
        ('command', {'commands': 'mkdir -p /data/app\nchown www:www /data/app'}),
        ('line', {'path': '/etc/selinux/config', 'line': 'SELINUX=disabled',
                  'replace': '^SELINUX=.*'}),
        ('block', {'path': '/etc/hosts', 'content': '10.0.0.5 db'}),
        ('sysctl', {'key': 'net.ipv4.ip_forward', 'value': '1', 'persist': True}),
        ('crontab', {'command': '/data/backup.sh', 'cron_name': 'spug-backup',
                     'minute': '0', 'hour': '2', 'user': 'root'}),
        ('download', {'src': 'https://example.com/a.tgz', 'dest': '/tmp/a.tgz',
                      'md5sum': 'd41d8cd98f00b204e9800998ecf8427e'}),
    ]:
        plan = build_plan([host], module, normalize(module, params), facts)
        print(module, '->', [(getattr(f, '__name__', str(f)), sorted(kw), len(hs))
                             for f, kw, hs in plan])

    print('selftest passed')


if __name__ == '__main__':
    main()
