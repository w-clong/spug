"""真实主机幂等验证（仅操作 /tmp 下的临时路径，不改系统配置）。

每个模块连续执行两次，第二次必须 changed=False。
用法: python -I d_idem.py <ip> <password> <user>
"""
import os
import sys
import time

sys.path.insert(0, r'C:\Users\wcl\Downloads\spug\spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.environ['SPUG_DATA_DIR'] = r'C:\Users\wcl\Downloads\spug\.tmp-diag\data'
import django  # noqa: E402

django.setup()

from apps.host.models import Host  # noqa: E402
from apps.ops.kernel.runner import StateRunner  # noqa: E402

IP, PWD, USR = sys.argv[1], sys.argv[2], sys.argv[3]
BASE = '/tmp/spug-idem'

CASES = [
    ('directory', {'path': BASE + '/dir', 'present': True, 'mode': '0755'}, '目录'),
    ('file', {'path': BASE + '/file.txt', 'present': True, 'content': 'hello\n', 'mode': '0644'}, '文件'),
    ('link', {'path': BASE + '/link', 'target': BASE + '/file.txt', 'present': True}, '软链接'),
    ('copy', {'src': BASE + '/file.txt', 'dest': BASE + '/copy.txt'}, '复制'),    ('line', {'path': BASE + '/line.txt', 'line': 'KEY=value', 'present': True}, '配置行'),
    ('block', {'path': BASE + '/block.txt', 'content': 'a=1\nb=2\n', 'marker': 'idem'}, '配置块'),
    ('replace', {'path': BASE + '/line.txt', 'match': '^KEY=value$', 'replace': 'KEY=value2'},
     '内容替换'),
    ('unarchive', {'src': BASE + '/pkg.tar.gz', 'dest': BASE + '/unpack',
                   'creates': BASE + '/unpack/a.txt'}, '解压'),
    ('modprobe', {'name': 'br_netfilter', 'present': True, 'persist': True}, '内核模块'),
    ('download', {'src': 'http://127.0.0.1:1/none', 'dest': BASE + '/x', 'force': False}, '跳过-下载'),
]


def make_host():
    h = Host(id=999, name='idem', hostname=IP, port=22, username=USR)
    h.password = PWD
    return h


def main():
    host = make_host()
    with host.get_ssh() as ssh:
        ssh.exec_command_raw('rm -rf %s && mkdir -p %s/src && echo hi > %s/src/a.txt && '
                             'tar czf %s/pkg.tar.gz -C %s/src . && rm -rf %s/src'
                             % (BASE, BASE, BASE, BASE, BASE, BASE))

    ok = fail = skip = 0
    print('%-10s %-10s %-10s %s' % ('模块', '第一次', '第二次', '结论'))
    print('-' * 46)
    for module, params, label in CASES:
        if label.startswith('跳过'):
            skip += 1
            continue
        try:
            r1 = StateRunner([make_host()], module, params, record=False).run()
            time.sleep(0.4)
            r2 = StateRunner([make_host()], module, params, record=False).run()
            first = 'failed' if r1.failed_count else ('changed' if r1.changed_count else 'unchanged')
            second = 'failed' if r2.failed_count else ('changed' if r2.changed_count else 'unchanged')
            good = (r2.failed_count == 0 and r2.changed_count == 0)
            ok += good
            fail += (not good)
            print('%-10s %-10s %-10s %s' % (label, first, second, 'OK' if good else 'FAIL'))
            if not good:
                for item in r2.results:
                    if item.changed or item.failed:
                        print('    ', (item.msg or '')[:150].replace('\n', ' '))
        except Exception as e:
            fail += 1
            print('%-10s 异常 %s: %s' % (label, type(e).__name__, e))

    print('\n幂等通过 %d，失败 %d，跳过 %d' % (ok, fail, skip))
    with host.get_ssh() as ssh:
        ssh.exec_command_raw('rm -rf %s' % BASE)


main()
