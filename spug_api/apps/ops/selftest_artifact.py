# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""制品拉取节点（raw）自检：真实 HTTP 源 + 两台测试主机。

在 Ubuntu 测试机上临时启动 python http.server 作为 raw 制品源，验证：
  - dry-run HEAD 探测
  - 真实下载 changed
  - 重复执行 unchanged
  - 目标文件内容正确、清理干净
"""
import json
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.pipeline.models import Pipeline  # noqa: E402
from apps.pipeline.utils import NodeExecutor  # noqa: E402
from libs.memredis import get_redis_connection  # noqa: E402

SRC_HOST = '10.0.0.35'
SRC_USER = 'wcl'
SRC_PASSWORD = '123456'
SRC_DIR = '/tmp/artifact-src'
DST_DIR = '/tmp/artifact-dst'
PORT = 18080
NODE_ID = 9001


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
    user = User.objects.filter(username='artifact-tester').first() or User.objects.create(
        username='artifact-tester', nickname='artifact', password_hash='x', is_supper=True)
    hosts = []
    for ip, username, password in (('10.0.0.34', 'root', '1'), ('10.0.0.35', 'wcl', '123456')):
        host, _ = Host.objects.update_or_create(
            name=f'artifact-{ip}',
            defaults=dict(hostname=ip, port=22, username=username, password=password,
                          pkey=None, created_by=user))
        hosts.append(host)
    return user, hosts


def run_node(pipeline, hosts, dry_run=False):
    node = {
        'id': NODE_ID, 'module': 'artifact', 'name': '拉取制品',
        'condition': 'success', 'targets': [x.id for x in hosts],
        'source_type': 'raw', 'base_url': f'http://{SRC_HOST}:{PORT}',
        'repo_name': '', 'package': 'demo.txt', 'version': '',
        'dest_path': f'{DST_DIR}/demo.txt', 'overwrite': False,
        'auth_type': 'none', 'dry_run': dry_run,
    }
    executor = NodeExecutor(get_redis_connection(), 'artifact-test-token', [node],
                            pipeline_id=pipeline.id)
    helper = RecordingHelper()
    executor.helper = helper
    executor.run()
    return executor, helper


def main():
    user, hosts = get_hosts()
    src = Host.objects.get(name=f'artifact-{SRC_HOST}')

    # 准备 HTTP 源
    with src.get_ssh() as ssh:
        ssh.exec_command_raw(
            f'mkdir -p {SRC_DIR} && echo "artifact-demo-v1" > {SRC_DIR}/demo.txt && '
            f'pkill -f "http.server {PORT}" 2>/dev/null || true')
        ssh.exec_command_raw(
            f'nohup python3 -m http.server {PORT} --directory {SRC_DIR} '
            f'>/tmp/artifact-http.log 2>&1 &')
    time.sleep(2)

    Pipeline.objects.filter(name='artifact-test-pipeline').delete()
    pipe = Pipeline.objects.create(name='artifact-test-pipeline', created_by=user, nodes='[]')

    # 清理旧目标
    for host in hosts:
        with host.get_ssh() as ssh:
            ssh.exec_command_raw(f'rm -rf {DST_DIR}')

    try:
        # dry-run：HEAD 探测
        _, helper = run_node(pipe, hosts, dry_run=True)
        text = '\n'.join(str(x[1]) for x in helper.logs)
        assert 'Dry-run: 资源可访问' in text, text
        print('dry-run HEAD ok')

        # 真实下载
        executor, helper = run_node(pipe, hosts, dry_run=False)
        assert executor.states[NODE_ID] == 'changed', executor.states
        text = '\n'.join(str(x[1]) for x in helper.logs)
        assert '下载完成' in text, text
        print('download changed ok')

        # 幂等：再次执行应 unchanged
        executor, helper = run_node(pipe, hosts, dry_run=False)
        assert executor.states[NODE_ID] == 'success', executor.states
        text = '\n'.join(str(x[1]) for x in helper.logs)
        assert '跳过下载' in text, text
        print('idempotent unchanged ok')

        # 校验内容
        for host in hosts:
            with host.get_ssh() as ssh:
                code, out = ssh.exec_command_raw(f'cat {DST_DIR}/demo.txt')
            assert code == 0 and 'artifact-demo-v1' in out, (host.name, out)
            print('content ok:', host.name)

        # 认证头生成（不打印凭据）
        from apps.credential.models import Credential
        from apps.ops.artifact import _auth_headers
        cred, _ = Credential.objects.get_or_create(
            name='artifact-test-cred',
            defaults=dict(type='pw', username='user1', secret='s3cret-token', created_by=user))
        headers, label = _auth_headers({'auth_type': 'bearer', 'credential_id': cred.id})
        assert headers['Authorization'] == 'Bearer s3cret-token' and label == 'Bearer Token'
        headers, label = _auth_headers({'auth_type': 'basic', 'credential_id': cred.id})
        assert headers['Authorization'].startswith('Basic ') and label == 'Basic Auth'
        cred.delete()
        print('auth header ok')
    finally:
        for host in hosts:
            with host.get_ssh() as ssh:
                ssh.exec_command_raw(f'rm -rf {DST_DIR}')
        with src.get_ssh() as ssh:
            ssh.exec_command_raw(f'pkill -f "http.server {PORT}" 2>/dev/null || true; rm -rf {SRC_DIR}')
        pipe.delete()
    print('artifact raw selftest passed')


if __name__ == '__main__':
    main()
