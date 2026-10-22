# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""基线执行（一键收敛 / 一键巡检）。

一条基线 = 多个状态模块节点，按顺序在同一批主机上执行；
结果汇总为一条 StateTask + 每主机 changed/failed，并写入全局变更日志。
"""
import json
import uuid

from django.utils import timezone

from apps.host.models import Host
from apps.ops.kernel.runner import StateRunner
from apps.ops.models import StateTask, StateTaskHost


def run_baseline(baseline, hosts, dry_run=False, operator=None, user_id=None):
    hosts = list(hosts)
    nodes = baseline.to_view()['nodes'] or []
    task = StateTask.objects.create(
        token=uuid.uuid4().hex,
        module='baseline',
        params=json.dumps({'baseline_id': baseline.id, 'nodes': nodes}, ensure_ascii=False),
        host_ids=json.dumps([x.id for x in hosts]),
        dry_run=dry_run,
        total=len(hosts),
        created_by_id=user_id or baseline.created_by_id,
    )

    def work():
        merged = {}
        for node in nodes:
            module = node.get('state_module') or node.get('module')
            params = node.get('state_params') or {}
            if not module or module in ('state', 'facts'):
                continue
            summary = StateRunner(
                hosts, module, params,
                dry_run=dry_run,
                record=True,
                source='baseline',
                source_id=baseline.id,
                operator=operator,
            ).run()
            for item in summary.results:
                current = merged.setdefault(item.host_id, {
                    'host_name': item.host_name, 'changed': False, 'failed': False,
                    'diff': [], 'msg': [],
                })
                current['changed'] = current['changed'] or item.changed
                current['failed'] = current['failed'] or item.failed
                if item.diff:
                    current['diff'].append(item.diff)
                if item.msg:
                    current['msg'].append(item.msg)

        for host in hosts:
            item = merged.get(host.id)
            if item is None:
                continue
            StateTaskHost.objects.update_or_create(
                task=task, host_id=host.id,
                defaults=dict(
                    host_name=item['host_name'],
                    changed=item['changed'],
                    failed=item['failed'],
                    diff='\n'.join(item['diff'])[:20000],
                    msg='\n'.join(item['msg'])[:20000],
                    finished_at=timezone.now(),
                ))
        task.changed_count = sum(1 for x in merged.values() if x['changed'])
        task.failed_count = sum(1 for x in merged.values() if x['failed'])
        task.status = 2 if task.failed_count else 1
        task.finished_at = timezone.now()
        task.save()

    import threading
    threading.Thread(target=work, daemon=True).start()
    return task
