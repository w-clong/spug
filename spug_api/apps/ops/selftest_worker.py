# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""状态模块 worker 自检（不连接真实主机，用假 Runner 验证队列->落库链路）。

用法：
    cd spug_api
    $env:SPUG_DATA_DIR="...\.tmp-data"; ..\.venv-win\Scripts\python.exe manage.py migrate
    ..\.venv-win\Scripts\python.exe apps\ops\selftest_worker.py
"""
import json
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.exec.models import ExecHistory  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.ops import executor as exec_mod  # noqa: E402
from apps.ops.kernel.result import HostResult, RunSummary  # noqa: E402
from apps.ops.models import ChangeRecord, StateTask, StateTaskHost  # noqa: E402


class FakeRunner:
    def __init__(self, hosts, module, params, **kwargs):
        self.hosts = hosts
        self.module = module

    def run(self):
        return RunSummary(
            results=[
                HostResult(host_id=self.hosts[0].id, host_name=self.hosts[0].name,
                           changed=True, diff='mkdir -p /opt/app', msg='已变更'),
            ],
            dry_run=False,
        )


def main():
    exec_mod.StateRunner = FakeRunner
    token = 'state-test-token'
    # 允许重复执行：清理上一次自检数据
    ExecHistory.objects.filter(digest=token).delete()
    StateTask.objects.filter(token=token).delete()
    user = User.objects.filter(username='tester').first()
    if user is None:
        user = User.objects.create(username='tester', nickname='tester',
                                   password_hash='x', is_supper=True)
    host = Host.objects.filter(name='test-host').first()
    if host is None:
        host = Host.objects.create(name='test-host', hostname='10.0.0.9', port=22,
                                   username='root', pkey='x', created_by=user)
    ExecHistory.objects.create(
        kind='state', module='directory', user=user, digest=token, interpreter='state',
        command=json.dumps({'path': '/opt/app'}), host_ids=json.dumps([host.id]),
        params='{}', dry_run=False,
    )
    job = dict(token=token, host_ids=[host.id], module='directory',
               params={'path': '/opt/app'}, dry_run=False, user_id=user.id, operator='tester')
    exec_mod.state_worker_handler(json.dumps(job))

    task = StateTask.objects.get(token=token)
    assert task.status == 1, task.status
    assert task.changed_count == 1, task.changed_count
    detail = StateTaskHost.objects.get(task=task)
    assert detail.changed and detail.diff == 'mkdir -p /opt/app'
    print('worker selftest passed: task=%s changed=%s' % (task.id, task.changed_count))


if __name__ == '__main__':
    main()
