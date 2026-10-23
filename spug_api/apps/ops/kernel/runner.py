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

# 远端非交互式 sh 的 PATH 常常只有 /bin:/usr/bin，缺少 sbin 目录，
# 会导致 dnf/apt/systemctl 等报 "command not found"，这里显式补全
DEFAULT_REMOTE_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

# pyinfra 通过 `stat -c ... %N` / `ls -ld` 解析文件与链接信息，而部分发行版（如 CentOS 7
# 配合中文 locale）会把 %N 的路径用本地化引号包裹（“...”），导致 pyinfra 误判
# link_target 不一致、软链接每次都被重建（非幂等）。固定 LANG=C 保证输出可解析。
DEFAULT_REMOTE_ENV = {
    'PATH': DEFAULT_REMOTE_PATH,
    'LANG': 'C',
    'LC_ALL': 'C',
}


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

    def _op_error_detail(self, state, host, op_hash):
        """取操作失败的真实原因（远端 stderr），避免只看到“No hosts remaining!”。"""
        try:
            op_data = state.ops[host][op_hash]
            meta = op_data.operation_meta
            if meta.is_complete():
                detail = (meta.stderr or '').strip()
                if not detail:
                    detail = (meta.stdout or '').strip()
                return detail[-800:]
        except Exception:
            pass
        return ''

    def operation_host_error(self, state, host, op_hash, retry_count=0, max_retries=0):
        names = self._op_names(state, op_hash)
        detail = self._op_error_detail(state, host, op_hash)
        message = f'{names} 执行失败'
        if detail:
            message += f'\n{detail}'
        self.emit(self._host_id(host), 'error', message)

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
                # 状态模块分发依赖 os_family / os_version / 包管理器可用性，实时采集（不写入缓存）
                for host in connected:
                    py_host = py_hosts[host.id]
                    item = {}
                    for key in ('os_release', 'os'):
                        try:
                            item[key] = py_host.get_fact(facts_kernel.FACT_DEFS[key])
                        except Exception:
                            pass
                    item['os_family'] = facts_kernel.family_of(item)
                    release = item.get('os_release')
                    if isinstance(release, dict):
                        version = release.get('version_id') or release.get('version')
                        if version:
                            item['os_version'] = version
                    # 包管理器可用性：CentOS 7 只有 yum，必须探测而不能按发行版猜
                    for key in ('which_dnf', 'which_yum', 'which_apt', 'which_apk'):
                        try:
                            item[key] = py_host.get_fact(
                                facts_kernel.FACT_DEFS[key], *facts_kernel.FACT_ARGS[key])
                        except Exception:
                            pass
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
                    # 远端非交互式 sh 的 PATH 可能不含 /usr/sbin，且本地化 locale 会让
                    # stat/ls 输出无法被 pyinfra 解析，统一注入固定的远端环境
                    env = dict(DEFAULT_REMOTE_ENV)
                    env.update(kwargs.get('_env') or {})
                    kwargs = dict(kwargs, _env=env)
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
            # pyinfra 批量失败时只会抛 "No hosts remaining!"，这里把每台主机
            # 最后一次操作的真实报错补上，避免用户看不到原因
            detail_map = self._last_op_errors(state, py_hosts)
            for host in self.hosts:
                existing = summary.get(host.id)
                if existing is not None:
                    continue
                detail = detail_map.get(host.id) or str(e)
                summary.results.append(HostResult(
                    host_id=host.id, host_name=host.name, failed=True,
                    msg=f'执行失败: {detail}'))
                self._emit(host.id, 'error', f'执行失败: {detail}')
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

    def _last_op_errors(self, state, py_hosts):
        """从 pyinfra state 提取每台主机最后一次失败操作的真实报错。"""
        result = {}
        for host_id, py_host in py_hosts.items():
            best = ''
            try:
                for op_hash, op_data in (state.ops.get(py_host) or {}).items():
                    meta = op_data.operation_meta
                    if not meta.is_complete() or meta.did_succeed():
                        continue
                    detail = (meta.stderr or '').strip() or (meta.stdout or '').strip()
                    if detail:
                        best = detail[-800:]
            except Exception:
                continue
            if best:
                result[host_id] = best
        return result

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
