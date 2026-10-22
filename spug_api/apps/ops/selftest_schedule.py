# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""定时任务状态模块自检（假 Runner，不连真实主机）。"""
import json
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Host  # noqa: E402
from apps.ops import schedule_executor  # noqa: E402
from apps.ops.kernel.result import HostResult, RunSummary  # noqa: E402
from apps.schedule.models import History, Task  # noqa: E402
from apps.schedule.scheduler import Scheduler  # noqa: E402
from libs.memredis import get_redis_connection  # noqa: E402


class FakeRunner:
    def __init__(self, hosts, module, params, **kwargs):
        self.hosts = hosts

    def run(self):
        return RunSummary(results=[
            HostResult(host_id=self.hosts[0].id, host_name=self.hosts[0].name,
                       changed=True, diff='mkdir -p /opt/app', msg='已变更'),
        ])


def main():
    schedule_executor.StateRunner = FakeRunner
    user = User.objects.filter(username='sched-tester').first() or User.objects.create(
        username='sched-tester', nickname='sched', password_hash='x', is_supper=True)
    host = Host.objects.filter(name='sched-host').first() or Host.objects.create(
        name='sched-host', hostname='10.0.0.7', port=22, username='root', pkey='x', created_by=user)

    Task.objects.filter(name='state-schedule-test').delete()
    task = Task.objects.create(
        type='test', name='state-schedule-test', kind='state', module='directory',
        interpreter='state', command=json.dumps({'path': '/opt/app'}),
        targets=json.dumps([host.id]), trigger='interval', trigger_args='3600',
        is_active=False, rst_notify=json.dumps({'mode': '0'}), created_by=user)

    rds = get_redis_connection()
    rds.delete('spug:state:worker')
    Scheduler.dispatch(task.id, task.interpreter, task.command, json.loads(task.targets),
                       task.kind, task.module, task.dry_run)
    job = rds.lindex('spug:state:worker', 0)
    assert job, 'schedule job not queued'
    payload = json.loads(job)
    assert payload['kind'] == 'state' and payload['module'] == 'directory'
    schedule_executor.schedule_state_worker_handler(job)

    history = History.objects.filter(task_id=task.id).order_by('-id').first()
    assert int(history.status) == 1, history.status
    output = json.loads(history.output)
    assert output[str(host.id)][0] == 0, output
    assert 'mkdir -p /opt/app' in output[str(host.id)][2]
    print('schedule state selftest passed: history=%s status=%s' % (history.id, history.status))


if __name__ == '__main__':
    main()
