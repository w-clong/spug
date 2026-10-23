# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一变量池。

优先级（从低到高）：全局 < 环境/分组 < 流水线变量 < 主机变量 < Facts。
与 `apps.ops.context.get_merged_context` 保持完全一致（变量预览面板展示的就是
实际渲染用的值），Facts 只读且最高，任何用户变量都不能覆盖同名 Fact。

同一套变量用于：
  - 状态模块参数渲染
  - Jinja2 模板渲染
  - Shell/Python 脚本的 _SPUG_FACT_* / _SPUG_VAR_* 环境变量注入
"""
import json


def _global_vars():
    """平台全局变量（系统设置里配置），最低优先级。"""
    from apps.setting.utils import AppSetting
    value = AppSetting.get_default('global_variables', {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {}
    return value if isinstance(value, dict) else {}


def _group_vars(host):
    from apps.ops.models import GroupVariable
    group_ids = list(host.groups.values_list('id', flat=True))
    if not group_ids:
        return {}
    result = {}
    # 按分组 id 升序合并，后面的分组覆盖前面的（与 Ansible 的 group 优先级近似）
    for item in GroupVariable.objects.filter(group_id__in=group_ids).order_by('group_id'):
        result[item.key] = item.value
    return result


def _host_vars(host):
    from apps.ops.models import HostVariable
    return {x.key: x.value for x in HostVariable.objects.filter(host_id=host.id)}


def collect(host, pipeline_vars=None, facts=None, use_cache=True):
    """返回 (变量字典, 环境变量字典)。"""
    from . import facts as facts_kernel
    if facts is None and use_cache:
        facts = facts_kernel.load(host.id)

    # Facts 只暴露已注册字段（与变量面板 / context.get_merged_context 口径一致），
    # 避免用户变量名恰好撞上未注册的内部 fact key 时出现两处渲染结果不同
    if facts:
        from apps.ops.context import FACTS_META
        facts = {k: v for k, v in facts.items() if k in FACTS_META}

    # 顺序即优先级，低 -> 高，与 context.get_merged_context 一致
    merged = {}
    merged.update(_global_vars())
    if host is not None:
        merged.update(_group_vars(host))
    if pipeline_vars:
        merged.update({str(k): v for k, v in pipeline_vars.items()})
    if host is not None:
        merged.update(_host_vars(host))
    if facts:
        merged.update(facts)

    env = {}
    if facts:
        env.update(facts_kernel.to_env(facts))
    if host is not None:
        for key, value in _group_vars(host).items():
            env[f'_SPUG_VAR_{key.upper()}'] = str(value)
        for key, value in _host_vars(host).items():
            env[f'_SPUG_VAR_{key.upper()}'] = str(value)
    for key, value in merged.items():
        if key not in env:
            env[f'_SPUG_VAR_{key.upper()}'] = value if isinstance(value, str) else json.dumps(value)
    return merged, env
