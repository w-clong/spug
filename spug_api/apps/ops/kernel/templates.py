# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Jinja2 模板渲染（配置模板库 / 状态模块内容渲染共用）。"""
import json

from jinja2 import Environment, StrictUndefined, Undefined


def _env(strict=False):
    env = Environment(
        autoescape=False,
        keep_trailing_newline=True,
        undefined=StrictUndefined if strict else Undefined,
    )
    env.filters['to_json'] = lambda v: json.dumps(v, ensure_ascii=False)
    return env


def render(content, context, strict=False):
    """渲染模板，返回字符串。strict=True 时缺失变量会抛异常。"""
    if not content:
        return ''
    return _env(strict=strict).from_string(content).render(**(context or {}))


def render_template(template, context, strict=False):
    """渲染 ConfigTemplate 实例。"""
    return render(template.content, context, strict=strict)
