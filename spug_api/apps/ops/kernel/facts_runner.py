# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Facts 刷新任务：连接主机 -> pyinfra 采集 -> 入库缓存 -> 同步动态分组。

供三处调用：
  1. 流水线前置刷新节点（module='facts'）
  2. 定时采集任务
  3. 主机列表/详情的手动刷新
"""
from pyinfra.api import Config, State
from pyinfra.api.connect import connect_all, disconnect_all
from pyinfra.api.state import StateStage

from . import facts as facts_kernel
from .inventory import build_inventory, inject_private_keys


def refresh(hosts, on_event=None, parallel=10, timeout=10, sync_groups=True):
    """采集并缓存 Facts，返回 {host_id: {fact_key: value}}。"""
    hosts = list(hosts)
    if not hosts:
        return {}
    inventory, _ = build_inventory(hosts)
    state = State(inventory, Config(
        PARALLEL=parallel,
        CONNECT_TIMEOUT=timeout,
        FAIL_PERCENT=100,
        # 固定远端 locale：部分发行版在中文 locale 下 stat/ls 输出带本地化引号，
        # 会让 pyinfra 的 facts 解析出错
        ENV={'LANG': 'C', 'LC_ALL': 'C'},
    ))
    inject_private_keys(state, hosts)
    py_hosts = {host.data.get('spug_id'): host for host in inventory}
    result = {}
    try:
        state.set_stage(StateStage.Connect)
        connect_all(state)
        for host in hosts:
            py_host = py_hosts.get(host.id)
            if py_host is None or not py_host.connected:
                if on_event:
                    on_event(host.id, 'error', 'SSH 连接失败')
                continue
            try:
                values = facts_kernel.collect(py_host)
            except Exception as e:
                if on_event:
                    on_event(host.id, 'error', f'Facts 采集失败: {e}')
                continue
            facts_kernel.save(host.id, values)
            result[host.id] = values
            if on_event:
                on_event(host.id, 'success', f'Facts 已更新（{len(values)} 项）')
    finally:
        try:
            state.set_stage(StateStage.Disconnect)
            disconnect_all(state)
        except Exception:
            pass
    if sync_groups and result:
        try:
            from apps.ops.groups import sync_hosts
            sync_hosts(list(result.keys()))
        except Exception:
            pass
    return result
