# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""文件分发（SFTP 版）自检：主机→主机、本地上传→主机。"""
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.exec.models import Transfer  # noqa: E402
from apps.exec.transfer import _dispatch_sync  # noqa: E402
from apps.host.models import Host  # noqa: E402

SRC_DIR = '/tmp/spug-sftp-src'
DST_DIR = '/tmp/spug-sftp-dst'


def hosts():
    user = User.objects.filter(username='sftp-tester').first() or User.objects.create(
        username='sftp-tester', nickname='sftp', password_hash='x', is_supper=True)
    src, _ = Host.objects.update_or_create(
        name='sftp-src', defaults=dict(hostname='10.0.0.77', port=22, username='root',
                                       password='1', pkey=None, created_by=user))
    dst, _ = Host.objects.update_or_create(
        name='sftp-dst', defaults=dict(hostname='10.0.0.11', port=22, username='root',
                                       password='1', pkey=None, created_by=user))
    return user, src, dst


def main():
    user, src, dst = hosts()
    try:
        # 准备源主机目录
        with src.get_ssh() as ssh:
            ssh.exec_command_raw(
                f'rm -rf {SRC_DIR} && mkdir -p {SRC_DIR}/sub && '
                f'echo hello-a > {SRC_DIR}/a.txt && echo hello-b > {SRC_DIR}/sub/b.txt')
        with dst.get_ssh() as ssh:
            ssh.exec_command_raw(f'rm -rf {DST_DIR}')

        # 1) 主机 → 主机
        task = Transfer.objects.create(
            user=user, digest='sftp-test-1', host_id=src.id, src_dir=SRC_DIR,
            dst_dir=DST_DIR, host_ids=json.dumps([dst.id]))
        _dispatch_sync(task)
        with dst.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(f'cat {DST_DIR}/a.txt; cat {DST_DIR}/sub/b.txt')
        assert code == 0 and 'hello-a' in out and 'hello-b' in out, out
        print('host -> host ok:', out.strip().replace('\n', ' | '))

        # 2) 本地目录 → 主机
        local_dir = tempfile.mkdtemp(prefix='spug-sftp-')
        with open(os.path.join(local_dir, 'local.txt'), 'w') as f:
            f.write('hello-local')
        with dst.get_ssh() as ssh:
            ssh.exec_command_raw(f'rm -rf {DST_DIR}-2')
        task2 = Transfer.objects.create(
            user=user, digest='sftp-test-2', host_id=None, src_dir=local_dir,
            dst_dir=f'{DST_DIR}-2', host_ids=json.dumps([dst.id]))
        _dispatch_sync(task2)
        with dst.get_ssh() as ssh:
            code, out = ssh.exec_command_raw(f'cat {DST_DIR}-2/local.txt')
        assert code == 0 and 'hello-local' in out, out
        print('local -> host ok:', out.strip())

        # 3) 清理
        with src.get_ssh() as ssh:
            ssh.exec_command_raw(f'rm -rf {SRC_DIR}')
        with dst.get_ssh() as ssh:
            ssh.exec_command_raw(f'rm -rf {DST_DIR} {DST_DIR}-2')
        shutil.rmtree(local_dir, ignore_errors=True)
        task.delete()
        task2.delete()
        print('transfer selftest passed')
    finally:
        pass


if __name__ == '__main__':
    main()
