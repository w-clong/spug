# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""基线执行自检（假 Runner，不连真实主机）。"""
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.ops import baseline_runner  # noqa: E402
from apps.ops.kernel.result import HostResult, RunSummary  # noqa: E402
from apps.ops.models import Baseline, StateTask, StateTaskHost  # noqa: E402


class FakeRunner:
    def __init__(self, hosts, module, params, **kwargs):
        self.hosts = hosts
        self.module = module

    def run(self):
        return RunSummary(results=[
            HostResult(host_id=self.hosts[0].id, host_name=self.hosts[0].name,
                       changed=True, diff=f'{self.module} changed', msg='已变更'),
        ])


def main():
    baseline_runner.StateRunner = FakeRunner
    user = User.objects.filter(username='base-tester').first() or User.objects.create(
        username='base-tester', nickname='base', password_hash='x', is_supper=True)
    host = Host.objects.filter(name='base-host').first() or Host.objects.create(
        name='base-host', hostname='10.0.0.6', port=22, username='root', pkey='x', created_by=user)
    Baseline.objects.filter(name='base-test').delete()
    baseline = Baseline.objects.create(
        name='base-test', nodes='[{"state_module": "pkg", "state_params": {"packages": "nginx"}}]',
        created_by=user)
    task = baseline_runner.run_baseline(baseline, [host], dry_run=False, operator='tester')
    for _ in range(50):
        task.refresh_from_db()
        if task.finished_at:
            break
        time.sleep(0.1)
    assert task.status == 1, task.status
    assert task.changed_count == 1
    detail = StateTaskHost.objects.get(task=task, host_id=host.id)
    assert detail.changed and 'pkg changed' in detail.diff
    print('baseline selftest passed: task=%s changed=%s' % (task.id, task.changed_count))


if __name__ == '__main__':
    main()
