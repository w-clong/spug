# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""pyinfra 同进程执行内核（B2 方案）。

- 直接 import pyinfra.api，不调用 CLI、不起子进程；
- 连接复用 paramiko（pyinfra 的 SSH 连接器本身就基于 paramiko）；
- 每个任务在独立线程中执行，调用方负责线程池隔离与异常兜底；
- 事件回调转译为 Spug 原生控制台日志。
"""
import threading
import time

from pyinfra.api import BaseStateCallback, Config, State
from pyinfra.api.connect import connect_all, disconnect_all
from pyinfra.api.operation import add_op
from pyinfra.api.operations import run_ops
from pyinfra.api.state import StateStage

from . import facts as facts_kernel
from .inventory import build_inventory, inject_private_keys
from .modules import build_plan, normalize
from .result import HostResult, RunSummary


class _EventCallback(BaseStateCallback):
    """把 pyinfra 生命周期事件转成 (host_id, kind, message)。"""

    def __init__(self, emit):
        self.emit = emit

    @staticmethod
    def _host_id(host):
        try:
            return host.data.get('spug_id')
        except Exception:
            return None

    def _op_names(self, state, op_hash):
        try:
            meta = state.get_op_meta(op_hash)
            return '/'.join(sorted(meta.names))
        except Exception:
            return op_hash[:8]

    def operation_host_start(self, state, host, op_hash):
        names = self._op_names(state, op_hash)
        self.emit(self._host_id(host), 'start', f'开始执行 {names}')

    def operation_host_success(self, state, host, op_hash, retry_count=0):
        names = self._op_names(state, op_hash)
        self.emit(self._host_id(host), 'success', f'{names} 执行成功')

    def operation_host_error(self, state, host, op_hash, retry_count=0, max_retries=0):
        names = self._op_names(state, op_hash)
        self.emit(self._host_id(host), 'error', f'{names} 执行失败')

    def host_connect_error(self, state, host, error):
        self.emit(self._host_id(host), 'error', f'SSH 连接失败: {error}')


class StateRunner:
    def __init__(self, hosts, module, params, dry_run=False, on_event=None,
                 collect_facts=False, record=True, source='batch', source_id=None,
                 operator=None, parallel=10, timeout=10, sudo=False, sudo_password=None):
        self.hosts = list(hosts)
        self.module = module
        self.params = normalize(module, params)
        self.dry_run = dry_run
        self.on_event = on_event
        self.collect_facts = collect_facts
        self.record = record
        self.source = source
        self.source_id = source_id
        self.operator = operator
        self.parallel = parallel
        self.timeout = timeout
        # sudo：非 root 主机安装软件/写系统目录时需要；密码由 pyinfra 通过 stdin 传给 sudo -S
        self.sudo = sudo
        self.sudo_password = sudo_password
        self._lock = threading.Lock()

    def _emit(self, host_id, kind, message):
        if self.on_event:
            try:
                self.on_event(host_id, kind, message)
            except Exception:
                pass

    def run(self):
        started = time.time()
        inventory, name_map = build_inventory(self.hosts)
        config_kwargs = dict(
            PARALLEL=self.parallel,
            CONNECT_TIMEOUT=self.timeout,
            FAIL_PERCENT=100,
            DIFF=True,
        )
        if self.sudo and self.sudo_password:
            config_kwargs['SUDO_PASSWORD'] = self.sudo_password
        state = State(inventory, Config(**config_kwargs))
        inject_private_keys(state, self.hosts)
        state.add_callback_handler(_EventCallback(self._emit))

        py_hosts = {host.data.get('spug_id'): host for host in inventory}
        summary = RunSummary(dry_run=self.dry_run)
        facts_map = {}

        try:
            state.set_stage(StateStage.Connect)
            connect_all(state)

            connected = []
            for host in self.hosts:
                py_host = py_hosts.get(host.id)
                if py_host is None or not py_host.connected:
                    error = getattr(py_host, 'connect_error', None) if py_host else 'inventory error'
                    summary.results.append(HostResult(
                        host_id=host.id, host_name=host.name, failed=True,
                        msg=f'SSH 连接失败: {error}', error=str(error)))
                    self._emit(host.id, 'error', f'SSH 连接失败: {error}')
                else:
                    connected.append(host)

            if connected:
                # 状态模块分发依赖 os_family / os，实时采集（不写入缓存）
                for host in connected:
                    py_host = py_hosts[host.id]
                    item = {}
                    for key in ('os_release', 'os'):
                        try:
                            item[key] = py_host.get_fact(facts_kernel.FACT_DEFS[key])
                        except Exception:
                            pass
                    item['os_family'] = facts_kernel.family_of(item)
                    facts_map[host.id] = item

                if self.collect_facts:
                    for host in connected:
                        collected = facts_kernel.collect(py_hosts[host.id])
                        facts_kernel.save(host.id, collected)
                        facts_map.setdefault(host.id, {}).update(collected)
                        self._emit(host.id, 'info', 'Facts 已刷新')

                state.set_stage(StateStage.Prepare)
                plan = self._template_plan(connected, facts_map) or build_plan(
                    connected, self.module, self.params, facts_map)
                for op_func, kwargs, op_hosts in plan:
                    if self.sudo:
                        kwargs = dict(kwargs, _sudo=True)
                    # add_op 接收的必须是 pyinfra Host，Spug Host 仅用于编排与日志
                    py_op_hosts = [py_hosts[h.id] for h in op_hosts if h.id in py_hosts]
                    if py_op_hosts:
                        add_op(state, op_func, host=py_op_hosts, **kwargs)

                if not self.dry_run:
                    state.set_stage(StateStage.Execute)
                    run_ops(state)

                self._collect_results(state, py_hosts, summary)
        except Exception as e:
            # 任何未预期异常都要落成失败结果，绝不允许拖垮调用方线程
            for host in self.hosts:
                existing = summary.get(host.id)
                if existing is None:
                    summary.results.append(HostResult(
                        host_id=host.id, host_name=host.name, failed=True, msg=f'Exception: {e}'))
            self._emit(None, 'error', f'执行异常: {e}')
        finally:
            try:
                state.set_stage(StateStage.Disconnect)
                disconnect_all(state)
            except Exception:
                pass

        if self.record and not self.dry_run:
            self._record_changes(summary)
        self.elapsed = round(time.time() - started, 2)
        return summary

    def _template_plan(self, hosts, facts_map):
        """file 模块 + template_id：按主机变量/Facts 渲染 Jinja2，内容相同的主机合并为一个 op。"""
        if self.module != 'file' or not self.params.get('template_id'):
            return None
        params = normalize('file', self.params)
        # present=False 时是删除文件，交给通用 build_plan 处理，不做模板渲染
        if not params.get('present', True):
            return None
        from io import StringIO

        from pyinfra.operations import files

        from apps.ops.models import ConfigTemplate
        from . import templates, variables

        template = ConfigTemplate.objects.filter(pk=self.params['template_id']).first()
        if template is None:
            raise ValueError(f'未找到配置模板: {self.params["template_id"]}')
        groups = {}
        for host in hosts:
            merged_facts = dict(facts_kernel.load(host.id))
            merged_facts.update(facts_map.get(host.id) or {})
            context, _ = variables.collect(host, facts=merged_facts)
            content = templates.render(template.content, context)
            groups.setdefault(content, []).append(host)
        plan = []
        for content, group_hosts in groups.items():
            kwargs = {
                'src': StringIO(content),
                'dest': params.get('path'),
                'user': params.get('owner'),
                'group': params.get('group'),
                'mode': params.get('mode') or None,
            }
            plan.append((files.put, kwargs, group_hosts))
        return plan

    def _collect_results(self, state, py_hosts, summary):
        for host in self.hosts:
            py_host = py_hosts.get(host.id)
            if py_host is None or not py_host.connected:
                continue
            result = summary.get(host.id) or HostResult(host.id, host.name)
            commands, outputs = [], []
            failed = False
            changed = False
            for op_hash, op_data in state.ops.get(py_host, {}).items():
                meta = op_data.operation_meta
                if not meta.is_complete():
                    # dry-run 未执行，changed 依据 will_change 计算
                    changed = changed or bool(meta.changed)
                else:
                    changed = changed or meta.did_change()
                    failed = failed or meta.did_error()
                    try:
                        if meta.stdout:
                            outputs.append(meta.stdout)
                        if meta.stderr:
                            outputs.append(meta.stderr)
                    except Exception:
                        pass
                try:
                    for cmd in op_data.command_generator():
                        commands.append(str(cmd))
                except Exception:
                    pass
            result.changed = changed
            result.failed = failed or result.failed
            result.diff = '\n'.join(commands)[:8000]
            result.msg = ('失败' if failed else ('已变更' if changed else '无变更'))
            if outputs:
                result.msg += '\n' + '\n'.join(outputs)[:8000]
            summary.results.append(result)
            self._emit(host.id, 'error' if failed else 'success', result.msg.splitlines()[0])

    def _record_changes(self, summary):
        from apps.ops.models import ChangeRecord
        for item in summary.results:
            if not (item.changed or item.failed):
                continue
            try:
                ChangeRecord.objects.create(
                    host_id=item.host_id,
                    host_name=item.host_name,
                    module=self.module,
                    action='failed' if item.failed else 'changed',
                    changed=item.changed,
                    failed=item.failed,
                    diff=item.diff,
                    msg=item.msg,
                    operator=self.operator,
                    source=self.source,
                    source_id=self.source_id,
                )
            except Exception:
                pass
