# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一变量池。

优先级（从低到高）：流水线变量 < Facts 变量 < 分组变量 < 主机变量。
同一套变量用于：
  - 状态模块参数渲染
  - Jinja2 模板渲染
  - Shell/Python 脚本的 _SPUG_FACT_* / _SPUG_VAR_* 环境变量注入
"""
import json


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

    merged = {}
    if pipeline_vars:
        merged.update({str(k): v for k, v in pipeline_vars.items()})
    if facts:
        merged.update(facts)
    merged.update(_group_vars(host))
    merged.update(_host_vars(host))

    env = {}
    if facts:
        env.update(facts_kernel.to_env(facts))
    for key, value in _group_vars(host).items():
        env[f'_SPUG_VAR_{key.upper()}'] = str(value)
    for key, value in _host_vars(host).items():
        env[f'_SPUG_VAR_{key.upper()}'] = str(value)
    for key, value in merged.items():
        if key not in env:
            env[f'_SPUG_VAR_{key.upper()}'] = value if isinstance(value, str) else json.dumps(value)
    return merged, env
