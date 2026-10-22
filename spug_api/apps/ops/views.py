# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""轻量化运维增强 API：状态模块 / Facts / 变量 / 动态分组 / 模板 / 基线 / 变更日志。"""
import json
from threading import Thread

from django.db import close_old_connections
from django.views.generic import View

from libs import Argument, JsonParser, auth, json_response
from apps.host.models import Host, Group
from apps.ops.models import (Baseline, ChangeRecord, ConfigTemplate, ConfigTemplateVersion,
                             DynamicGroup, GroupVariable, HostFact, HostVariable)


class ModuleView(View):
    @auth('exec.task.do')
    def get(self, request):
        from apps.ops.kernel.modules import MODULE_SCHEMA
        return json_response(MODULE_SCHEMA)


class FactView(View):
    @auth('host.host.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('host_id', type=int, required=False),
            Argument('with_meta', type=bool, default=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        from apps.ops.kernel import facts as facts_kernel
        if form.host_id:
            return json_response(facts_kernel.load(form.host_id))
        # 批量：主机列表卡片使用；with_meta=1 时附带最后采集时间
        result = {}
        for item in HostFact.objects.all():
            entry = result.setdefault(item.host_id, {} if not form.with_meta else
                                      {'facts': {}, 'updated_at': None})
            if form.with_meta:
                entry['facts'][item.fact_key] = json.loads(item.fact_value)
                updated = item.updated_at.strftime('%Y-%m-%d %H:%M:%S')
                if not entry['updated_at'] or updated > entry['updated_at']:
                    entry['updated_at'] = updated
            else:
                entry[item.fact_key] = json.loads(item.fact_value)
        return json_response(result)

    @auth('host.host.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择主机'),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        hosts = list(Host.objects.filter(id__in=form.host_ids))

        def run():
            try:
                from apps.ops.kernel.facts_runner import refresh
                refresh(hosts)
            finally:
                close_old_connections()

        Thread(target=run, daemon=True).start()
        return json_response()


class VariableView(View):
    """主机变量 / 分组变量统一入口：scope=host|group。"""

    @auth('host.host.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('scope', default='host'),
            Argument('id', type=int, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        model = HostVariable if form.scope == 'host' else GroupVariable
        key = 'host_id' if form.scope == 'host' else 'group_id'
        query = model.objects.all()
        if form.id:
            query = query.filter(**{key: form.id})
        return json_response([x.to_dict() for x in query])

    @auth('host.host.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('scope', default='host'),
            Argument('target_id', type=int, help='参数错误'),
            Argument('key', help='请输入变量名'),
            Argument('value', default=''),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        model = HostVariable if form.scope == 'host' else GroupVariable
        key = 'host_id' if form.scope == 'host' else 'group_id'
        model.objects.update_or_create(
            defaults={'value': str(form.value)},
            **{key: form.target_id, 'key': form.key})
        return json_response()

    @auth('host.host.edit')
    def delete(self, request):
        form, error = JsonParser(
            Argument('scope', default='host'),
            Argument('id', type=int, help='参数错误'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        model = HostVariable if form.scope == 'host' else GroupVariable
        model.objects.filter(pk=form.id).delete()
        return json_response()


class DynamicGroupView(View):
    @auth('host.host.view')
    def get(self, request):
        return json_response([x.to_view() for x in DynamicGroup.objects.all()])

    @auth('host.host.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('group_id', type=int, help='请选择分组'),
            Argument('name', required=False),
            Argument('enabled', type=bool, default=True),
            Argument('match_all', type=bool, default=True),
            Argument('rules', type=list, handler=json.dumps, default=[]),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        group = Group.objects.filter(pk=form.group_id).first()
        if group is None:
            return json_response(error='未找到指定分组')
        name = form.name or group.name
        if form.id:
            DynamicGroup.objects.filter(pk=form.id).update(
                group_id=form.group_id, name=name, enabled=form.enabled,
                match_all=form.match_all, rules=form.rules)
        else:
            DynamicGroup.objects.update_or_create(
                group_id=form.group_id,
                defaults=dict(name=name, enabled=form.enabled,
                              match_all=form.match_all, rules=form.rules))
        Group.objects.filter(pk=form.group_id).update(is_dynamic=True)
        from apps.ops.groups import sync_hosts
        sync_hosts(list(Host.objects.values_list('id', flat=True)))
        return json_response()

    @auth('host.host.edit')
    def delete(self, request):
        form, error = JsonParser(Argument('id', type=int, help='参数错误')).parse(request.GET)
        if error:
            return json_response(error=error)
        rule = DynamicGroup.objects.filter(pk=form.id).first()
        if rule:
            Group.objects.filter(pk=rule.group_id).update(is_dynamic=False)
            rule.delete()
        return json_response()


class TemplateView(View):
    @auth('pipeline.pipeline.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('version', type=int, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        if form.id:
            template = ConfigTemplate.objects.filter(pk=form.id).first()
            if template is None:
                return json_response(error='未找到指定模板')
            data = template.to_view()
            data['versions'] = list(template.versions.values('id', 'version', 'comment', 'created_at'))
            if form.version:
                item = template.versions.filter(version=form.version).first()
                if item:
                    data['content'] = item.content
            return json_response(data)
        return json_response([x.to_view(with_content=False) for x in ConfigTemplate.objects.all()])

    @auth('pipeline.pipeline.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', required=False),
            Argument('description', required=False),
            Argument('content', required=False),
            Argument('comment', required=False),
            Argument('variables', type=list, handler=json.dumps, default=[]),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.id:
            template = ConfigTemplate.objects.filter(pk=form.id).first()
            if template is None:
                return json_response(error='未找到指定模板')
            for key in ('name', 'description', 'content', 'variables'):
                value = getattr(form, key, None)
                if value is not None:
                    setattr(template, key, value)
            template.save()
        else:
            if not form.name:
                return json_response(error='请输入模板名称')
            template = ConfigTemplate.objects.create(
                name=form.name, description=form.description,
                content=form.content or '', variables=form.variables,
                created_by=request.user)
        version = (template.versions.first().version + 1) if template.versions.exists() else 1
        ConfigTemplateVersion.objects.create(
            template=template, version=version, content=template.content,
            comment=form.comment, created_by=request.user)
        return json_response(template.id)

    @auth('pipeline.pipeline.edit')
    def delete(self, request):
        form, error = JsonParser(Argument('id', type=int, help='参数错误')).parse(request.GET)
        if error:
            return json_response(error=error)
        ConfigTemplate.objects.filter(pk=form.id).delete()
        return json_response()


class BaselineView(View):
    @auth('pipeline.pipeline.view')
    def get(self, request):
        form, error = JsonParser(Argument('id', type=int, required=False)).parse(request.GET)
        if error:
            return json_response(error=error)
        if form.id:
            item = Baseline.objects.filter(pk=form.id).first()
            return json_response(item.to_view() if item else {})
        return json_response([x.to_view() for x in Baseline.objects.all()])

    @auth('pipeline.pipeline.edit')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('name', required=False),
            Argument('description', required=False),
            Argument('nodes', type=list, handler=json.dumps, default=[]),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        if form.id:
            Baseline.objects.filter(pk=form.id).update(
                name=form.name, description=form.description, nodes=form.nodes)
        else:
            Baseline.objects.create(
                name=form.name, description=form.description,
                nodes=form.nodes, created_by=request.user)
        return json_response()

    @auth('pipeline.pipeline.edit')
    def delete(self, request):
        form, error = JsonParser(Argument('id', type=int, help='参数错误')).parse(request.GET)
        if error:
            return json_response(error=error)
        Baseline.objects.filter(pk=form.id).delete()
        return json_response()


class BaselineRunView(View):
    """一键基线收敛 / 巡检：nodes 依次执行，结果写入 StateTask 与变更日志。"""

    @auth('pipeline.pipeline.do')
    def post(self, request):
        form, error = JsonParser(
            Argument('id', type=int, help='请选择基线'),
            Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择主机'),
            Argument('dry_run', type=bool, default=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)
        baseline = Baseline.objects.filter(pk=form.id).first()
        if baseline is None:
            return json_response(error='未找到指定基线')
        hosts = list(Host.objects.filter(id__in=form.host_ids))
        if not hosts:
            return json_response(error='未找到目标主机')
        from apps.ops.baseline_runner import run_baseline
        task = run_baseline(baseline, hosts, dry_run=form.dry_run,
                            operator=request.user.nickname, user_id=request.user.id)
        return json_response({'token': task.token, 'task_id': task.id})


class ContextView(View):
    """流水线变量上下文预览：传入 pipeline_id + 可选 host_id。"""

    @auth('pipeline.pipeline.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('pipeline_id', type=int, help='请指定流水线'),
            Argument('host_id', type=int, required=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        from apps.ops.context import get_merged_context
        _, variables, facts_updated_at = get_merged_context(form.pipeline_id, form.host_id)
        return json_response({'variables': variables, 'facts_updated_at': facts_updated_at})


class PipelineHostsView(View):
    """流水线绑定范围内的主机列表（变量预览主机下拉）。"""

    @auth('pipeline.pipeline.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('pipeline_id', type=int, help='请指定流水线'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        from apps.ops.context import get_pipeline_host_ids
        ids = get_pipeline_host_ids(form.pipeline_id)
        hosts = [{'id': x.id, 'name': x.name, 'hostname': x.hostname}
                 for x in Host.objects.filter(id__in=ids).order_by('id')]
        return json_response(hosts)


class ChangeLogView(View):
    @auth('host.host.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('page', type=int, default=1),
            Argument('page_size', type=int, default=20),
            Argument('host_id', type=int, required=False),
            Argument('source', required=False),
            Argument('only_changed', type=bool, default=False),
            Argument('only_failed', type=bool, default=False),
        ).parse(request.GET)
        if error:
            return json_response(error=error)
        query = ChangeRecord.objects.all()
        if form.host_id:
            query = query.filter(host_id=form.host_id)
        if form.source:
            query = query.filter(source=form.source)
        if form.only_changed:
            query = query.filter(changed=True)
        if form.only_failed:
            query = query.filter(failed=True)
        total = query.count()
        page_size = min(max(form.page_size, 1), 100)
        start = max(form.page - 1, 0) * page_size
        items = [x.to_dict() for x in query[start:start + page_size]]
        return json_response({'total': total, 'items': items})
