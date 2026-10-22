# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""状态模块后台执行器。

由 Worker 线程池调用（与 Shell/Python 任务共用队列消费模型），
单个任务内部再通过 pyinfra 的 gevent 池并发连接多台主机。
输出沿用 Spug 原生批量执行协议：向 redis 频道 `token` 发布
{"key": host_id, "data": "..."} / {"key": host_id, "status": 0|1}，
前端复用现有 WebSocket 控制台（/api/ws/subscribe/<token>/）。
"""
import json
import time

from django.db import close_old_connections
from django.utils import timezone

from libs.memredis import get_redis_connection
from apps.host.models import Host
from apps.ops.kernel.runner import StateRunner
from apps.ops.models import StateTask, StateTaskHost


class StateJob:
    def __init__(self, token, host_ids, module, params, dry_run=False,
                 language='zh', user_id=None, operator=None):
        self.token = token
        self.host_ids = host_ids or []
        self.module = module
        self.params = params or {}
        self.dry_run = dry_run
        self.language = language
        self.user_id = user_id
        self.operator = operator
        self.rds = get_redis_connection()

    def _send(self, key, data=None, status=None):
        message = {'key': key}
        if data is not None:
            message['data'] = data
        if status is not None:
            message['status'] = status
        try:
            self.rds.publish(self.token, json.dumps(message))
        except Exception:
            pass

    def _task(self):
        return StateTask.objects.filter(token=self.token).first()

    def run(self):
        task = self._task()
        hosts = list(Host.objects.filter(id__in=self.host_ids))
        if task is None:
            task = StateTask.objects.create(
                token=self.token, module=self.module, params=json.dumps(self.params, ensure_ascii=False),
                host_ids=json.dumps(self.host_ids), dry_run=self.dry_run,
                total=len(hosts), created_by_id=self.user_id or 1)
        if not hosts:
            task.status = 2
            task.finished_at = timezone.now()
            task.save()
            return

        mode = 'DRY-RUN 预览' if self.dry_run else '执行'
        for host in hosts:
            self._send(host.id, f'\r\n\x1b[36m### {mode}状态模块 {self.module} ...\x1b[0m\r\n')

        def on_event(host_id, kind, message):
            text = f'\r\n{message}\r\n'
            if host_id is None:
                for host in hosts:
                    self._send(host.id, text)
            else:
                self._send(host_id, text)

        started = time.time()
        try:
            runner = StateRunner(
                hosts, self.module, self.params,
                dry_run=self.dry_run,
                on_event=on_event,
                record=True,
                source='batch',
                source_id=task.id,
                operator=self.operator,
            )
            summary = runner.run()
        except Exception as e:
            # 理论上 StateRunner 内部已兜底，这里只防最后一道
            for host in hosts:
                self._send(host.id, f'\r\n\x1b[31m### 执行异常: {e}\x1b[0m\r\n', status=1)
            task.status = 2
            task.finished_at = timezone.now()
            task.save()
            return

        for item in summary.results:
            StateTaskHost.objects.update_or_create(
                task=task, host_id=item.host_id,
                defaults=dict(
                    host_name=item.host_name, changed=item.changed, failed=item.failed,
                    diff=item.diff, msg=item.msg, finished_at=timezone.now()))
            lines = []
            if item.changed:
                lines.append('\r\n\x1b[33m### 状态变更 (changed)\x1b[0m')
            if item.failed:
                lines.append('\r\n\x1b[31m### 执行失败 (failed)\x1b[0m')
            if not item.changed and not item.failed:
                lines.append('\r\n\x1b[32m### 已完成，无变更\x1b[0m')
            if item.diff:
                lines.append('\r\n\x1b[36m--- 变更命令/输出 ---\x1b[0m\r\n' + item.diff)
            if item.msg:
                lines.append('\r\n' + item.msg)
            self._send(item.host_id, ''.join(lines), status=1 if item.failed else 0)

        task.total = len(summary.results)
        task.changed_count = summary.changed_count
        task.failed_count = summary.failed_count
        task.status = 2 if summary.failed_count else 1
        task.finished_at = timezone.now()
        task.save()
        try:
            close_old_connections()
        except Exception:
            pass


def state_worker_handler(job):
    data = json.loads(job)
    StateJob(**data).run()
