# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一变量上下文（流水线渲染 + 变量预览共用）。

优先级（从低到高）：平台全局 < 环境/分组 < 流水线参数 < 主机变量 < Facts。
Facts 为只读快照，最后合并，任何用户变量都不能覆盖同名 Fact。

数据来源（复用现有模型，不新增表）：
  - 全局：AppSetting 'global_variables'（JSON 对象）
  - 环境/分组：主机所属分组的 GroupVariable
  - 流水线：parameter 节点的 static_params / dynamic_params
  - 主机：HostVariable
  - Facts：HostFact，仅 FACTS_META 注册过的字段
"""
import json

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError, UndefinedError

from libs.utils import SpugError

# Facts 白名单：只展示/渲染注册过的字段，禁止动态拾取任意 JSON key
FACTS_META = {
    'os': {'label': '操作系统', 'example': 'Linux'},
    'os_family': {'label': '系统系列', 'example': 'Debian'},
    'os_version': {'label': '系统版本', 'example': '24.04'},
    'arch': {'label': 'CPU 架构', 'example': 'x86_64'},
    'kernel': {'label': '内核', 'example': '6.8.0-xx-generic'},
    'hostname': {'label': '主机名', 'example': 'web-01'},
    'memory_total_mb': {'label': '内存(MB)', 'example': '8192'},
}

SOURCE_LABELS = {
    'global': '全局',
    'env': '环境',
    'pipeline': '流水线',
    'host': 'host_var',
    'fact': 'fact',
}


def _global_vars():
    from apps.setting.utils import AppSetting
    value = AppSetting.get_default('global_variables', {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {}
    return value if isinstance(value, dict) else {}


def _pipeline_vars(pipeline_id):
    from apps.pipeline.models import Pipeline
    if not pipeline_id:
        return {}
    pipe = Pipeline.objects.filter(pk=pipeline_id).first()
    if pipe is None:
        return {}
    result = {}
    for node in json.loads(pipe.nodes or '[]'):
        if node.get('module') != 'parameter':
            continue
        for item in node.get('static_params') or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                result[str(item[0])] = item[1]
        for key, value in (node.get('dynamic_params') or {}).items():
            result[str(key)] = value
    return result


def _host_vars(host_id):
    from apps.ops.models import HostVariable
    if not host_id:
        return {}
    return {x.key: x.value for x in HostVariable.objects.filter(host_id=host_id)}


def _env_vars(host):
    from apps.ops.models import GroupVariable
    if host is None:
        return {}
    group_ids = list(host.groups.values_list('id', flat=True))
    if not group_ids:
        return {}
    result = {}
    for item in GroupVariable.objects.filter(group_id__in=group_ids).order_by('group_id'):
        result[item.key] = item.value
    return result


def _fact_vars(host_id):
    from apps.ops.kernel import facts as facts_kernel
    from apps.ops.models import HostFact
    if not host_id:
        return {}, None
    values = facts_kernel.load(host_id)
    result = {k: values[k] for k in FACTS_META if k in values}
    updated = HostFact.objects.filter(host_id=host_id).order_by('-updated_at').values_list('updated_at', flat=True).first()
    return result, updated.strftime('%Y-%m-%d %H:%M:%S') if updated else None


def get_merged_context(pipeline_id=None, host_id=None):
    """返回 (context_dict, variables_list, facts_updated_at)。

    variables_list 每项：{name, value, source, source_label}
    未指定 host_id 时只返回变量定义（value 为空），Facts 使用 FACTS_META 的示例值。
    """
    from apps.host.models import Host

    host = Host.objects.filter(pk=host_id).first() if host_id else None
    merged = {}
    sources = {}

    def apply(values, source):
        for key, value in (values or {}).items():
            merged[str(key)] = value
            sources[str(key)] = source

    apply(_global_vars(), 'global')
    apply(_env_vars(host), 'env')
    apply(_pipeline_vars(pipeline_id), 'pipeline')
    apply(_host_vars(host_id), 'host')

    facts_updated_at = None
    if host is not None:
        fact_values, facts_updated_at = _fact_vars(host.id)
        apply(fact_values, 'fact')
    else:
        # 无主机：只展示注册过的 Facts 元信息
        for key, meta in FACTS_META.items():
            merged.setdefault(key, meta.get('example', ''))
            sources.setdefault(key, 'fact')

    variables = []
    for key, value in merged.items():
        variables.append({
            'name': key,
            'value': '' if value is None else (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)),
            'source': sources.get(key, 'global'),
            'source_label': SOURCE_LABELS.get(sources.get(key, 'global'), '全局'),
        })
    return merged, variables, facts_updated_at


def get_pipeline_host_ids(pipeline_id):
    """流水线绑定范围内的主机 id（各节点 targets 的并集）。"""
    from apps.pipeline.models import Pipeline
    pipe = Pipeline.objects.filter(pk=pipeline_id).first()
    if pipe is None:
        return []
    ids = set()
    for node in json.loads(pipe.nodes or '[]'):
        if node.get('module') in ('ssh_exec', 'data_upload', 'state', 'facts', 'artifact'):
            ids.update(node.get('targets') or [])
        elif node.get('module') == 'data_transfer':
            ids.update((node.get('destination') or {}).get('targets') or [])
    return sorted(ids)


def render_jinja(template, context, strict=True):
    """统一 Jinja 渲染入口；异常转换为友好提示，不暴露 traceback。"""
    if template is None:
        return ''
    env = Environment(undefined=StrictUndefined if strict else None, keep_trailing_newline=True)
    try:
        return env.from_string(str(template)).render(**(context or {}))
    except UndefinedError as e:
        name = str(e).split("'")[1] if "'" in str(e) else str(e)
        raise SpugError(f'模板渲染失败：变量 {name} 不存在或语法错误，请查看右侧变量面板核对可用变量')
    except TemplateSyntaxError as e:
        raise SpugError(f'模板渲染失败：变量或语法错误（第 {e.lineno} 行），请查看右侧变量面板核对可用变量')
    except Exception:
        raise SpugError('模板渲染失败：变量不存在或语法错误，请查看右侧变量面板核对可用变量')


def render_with_context(template, pipeline_id=None, host_id=None):
    context, _, _ = get_merged_context(pipeline_id, host_id)
    return render_jinja(template, context)
