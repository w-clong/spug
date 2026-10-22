# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""定时任务中的状态模块 / Facts 刷新执行器。

与手工批量执行共用 StateRunner，但结果写入 schedule.History，供原生
「任务计划 -> 执行历史」直接展示；无变更时静默不推送，有变更/失败时汇总一条通知。
"""
import json
import time

from django.db import close_old_connections
from django.utils import timezone

from apps.host.models import Host
from apps.schedule.models import History, Task
from apps.schedule.utils import send_summary_notify
from apps.ops.kernel.facts_runner import refresh as refresh_facts
from apps.ops.kernel.runner import StateRunner


def schedule_state_worker_handler(job):
    data = json.loads(job)
    try:
        _run(data)
    finally:
        close_old_connections()


def _run(data):
    history = History.objects.filter(pk=data['history_id']).first()
    task = Task.objects.filter(pk=data['task_id']).first()
    if history is None or task is None:
        return
    hosts = list(Host.objects.filter(id__in=data.get('host_ids') or []))
    outputs = {str(x.id): None for x in hosts}
    started = {}
    finished = {}

    def on_event(host_id, kind, message):
        if host_id is None:
            return
        if kind == 'start':
            started.setdefault(host_id, time.time())
        elif kind in ('success', 'error'):
            finished.setdefault(host_id, time.time())

    kind = data.get('kind', 'state')
    summary = None
    if kind == 'facts':
        t0 = time.time()
        result = refresh_facts(hosts, on_event=on_event)
        for host in hosts:
            if host.id in result:
                outputs[str(host.id)] = [0, round(time.time() - t0, 3), 'Facts 已刷新']
            else:
                outputs[str(host.id)] = [1, round(time.time() - t0, 3), 'Facts 刷新失败']
        changed = 0
        failed = len(hosts) - len(result)
    else:
        summary = StateRunner(
            hosts, data.get('module'), data.get('params') or {},
            dry_run=bool(data.get('dry_run')),
            on_event=on_event,
            record=True,
            source='schedule',
            source_id=task.id,
            operator='scheduler',
        ).run()
        for item in summary.results:
            duration = round(finished.get(item.host_id, time.time()) - started.get(item.host_id, time.time()), 3)
            if duration < 0:
                duration = 0
            text = item.msg or ''
            if item.diff:
                text += '\n--- 变更命令 ---\n' + item.diff
            outputs[str(item.host_id)] = [1 if item.failed else 0, duration, text]
        changed = summary.changed_count
        failed = summary.failed_count

    history.output = json.dumps(outputs, ensure_ascii=False)
    history.status = '2' if failed else '1'
    history.save()

    # 无变更且无失败时静默；有变更/失败才推送一条汇总
    if failed or changed:
        # 四种级别：执行失败 / 巡检漂移 / 存在变更 / （正常完成不推送）
        if failed:
            title = f'任务执行失败: {task.name}'
        elif data.get('dry_run'):
            title = f'巡检发现漂移: {task.name}'
        else:
            title = f'任务存在变更: {task.name}'
        lines = [
            f'任务名称: {task.name}',
            f'任务类型: {task.type}',
            f'目标主机: {len(hosts)} 台',
            f'变更主机: {changed} 台',
            f'失败主机: {failed} 台',
        ]
        if summary is not None:
            for item in summary.results:
                if item.changed or item.failed:
                    flag = '失败' if item.failed else '变更'
                    lines.append(f'- [{flag}] {item.host_name}: {(item.msg or "").splitlines()[0][:80]}')
        send_summary_notify(task, title, '\n'.join(lines))
