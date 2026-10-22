# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""轻量化运维增强模块（State 模块 / Facts / 变量 / 模板 / 基线 / 变更日志）。

设计原则（与项目整体一致）：
  - 只服务单机个人运维场景，不引入工单/审批/RBAC/CMDB 等企业级概念；
  - Facts 只缓存低频静态信息，动态信息由 pyinfra 模块实时判断；
  - 所有执行结果统一 changed / failed / diff / msg 四元组。
"""
from django.db import models

from libs.mixins import ModelMixin
from apps.account.models import User


class HostFact(models.Model, ModelMixin):
    """主机 Facts 持久化缓存（方案2：pyinfra 实时采集 + 数据库缓存）。"""
    host_id = models.IntegerField(db_index=True)
    fact_key = models.CharField(max_length=64)
    # 统一 JSON 编码，字符串也会被 json.dumps，取值时 json.loads 还原类型
    fact_value = models.TextField(default='null')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'host_facts'
        unique_together = (('host_id', 'fact_key'),)
        indexes = [models.Index(fields=['fact_key'])]


class HostVariable(models.Model, ModelMixin):
    """主机变量（对标 Ansible host_vars）。"""
    host_id = models.IntegerField(db_index=True)
    key = models.CharField(max_length=64)
    value = models.TextField(default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'host_variables'
        unique_together = (('host_id', 'key'),)


class GroupVariable(models.Model, ModelMixin):
    """主机分组变量（对标 Ansible group_vars）。"""
    group_id = models.IntegerField(db_index=True)
    key = models.CharField(max_length=64)
    value = models.TextField(default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'group_variables'
        unique_together = (('group_id', 'key'),)


class DynamicGroup(models.Model, ModelMixin):
    """基于 Facts 的动态分组规则，命中后自动维护 host_groups 的成员关系。

    rules 为 JSON 数组，每项形如：
        {"key": "os_family", "op": "eq", "value": "Debian"}
    支持 op: eq / ne / in / not_in / gt / ge / lt / le / contains
    """
    group_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=50)
    enabled = models.BooleanField(default=True)
    match_all = models.BooleanField(default=True)
    rules = models.TextField(default='[]')
    updated_at = models.DateTimeField(auto_now=True)

    def get_rules(self):
        import json
        return json.loads(self.rules or '[]')

    def to_view(self):
        tmp = self.to_dict()
        tmp['rules'] = self.get_rules()
        return tmp

    class Meta:
        db_table = 'dynamic_groups'


class ConfigTemplate(models.Model, ModelMixin):
    """Jinja2 配置模板（对标 Ansible template），保留历史版本。"""
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, null=True)
    content = models.TextField(default='')
    # 声明模板变量，仅用于前端提示，实际渲染以运行时变量池为准
    variables = models.TextField(default='[]')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def to_view(self, with_content=True):
        import json
        tmp = self.to_dict(excludes=() if with_content else ('content',))
        tmp['variables'] = json.loads(self.variables or '[]')
        return tmp

    class Meta:
        db_table = 'config_templates'
        ordering = ('-id',)


class ConfigTemplateVersion(models.Model, ModelMixin):
    template = models.ForeignKey(ConfigTemplate, on_delete=models.CASCADE, related_name='versions')
    version = models.IntegerField()
    content = models.TextField()
    comment = models.CharField(max_length=255, null=True)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'config_template_versions'
        unique_together = (('template', 'version'),)
        ordering = ('-version',)


class Baseline(models.Model, ModelMixin):
    """基线模板（轻量 Role 平替）：一组状态模块节点的可视化组合。"""
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, null=True)
    nodes = models.TextField(default='[]')
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def to_view(self):
        import json
        tmp = self.to_dict()
        tmp['nodes'] = json.loads(self.nodes or '[]')
        return tmp

    class Meta:
        db_table = 'baselines'
        ordering = ('-id',)


class StateTask(models.Model, ModelMixin):
    """批量执行页的「状态模块」任务记录（与 Shell/Python 任务并列展示）。"""
    STATUS = (
        (0, '执行中'),
        (1, '成功'),
        (2, '失败'),
        (3, '已中断'),
    )
    token = models.CharField(max_length=32, unique=True)
    module = models.CharField(max_length=32)
    params = models.TextField(default='{}')
    host_ids = models.TextField(default='[]')
    dry_run = models.BooleanField(default=False)
    status = models.SmallIntegerField(choices=STATUS, default=0)
    total = models.IntegerField(default=0)
    changed_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    def to_view(self):
        import json
        tmp = self.to_dict()
        tmp['params'] = json.loads(self.params or '{}')
        tmp['host_ids'] = json.loads(self.host_ids or '[]')
        tmp['status_alias'] = self.get_status_display()
        return tmp

    class Meta:
        db_table = 'state_tasks'
        ordering = ('-id',)


class StateTaskHost(models.Model, ModelMixin):
    task = models.ForeignKey(StateTask, on_delete=models.CASCADE, related_name='hosts')
    host_id = models.IntegerField()
    host_name = models.CharField(max_length=100)
    changed = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)
    diff = models.TextField(default='')
    msg = models.TextField(default='')
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'state_task_hosts'
        unique_together = (('task', 'host_id'),)


class ChangeRecord(models.Model, ModelMixin):
    """全局变更日志：所有 changed / failed 的统一时间线。"""
    SOURCES = (
        ('batch', '批量执行'),
        ('pipeline', '流水线'),
        ('schedule', '定时任务'),
        ('baseline', '基线收敛'),
        ('api', '开放接口'),
        ('facts', 'Facts采集'),
    )
    host_id = models.IntegerField(db_index=True, null=True)
    host_name = models.CharField(max_length=100, null=True)
    module = models.CharField(max_length=32)
    action = models.CharField(max_length=16, default='changed')  # changed / failed / ok
    changed = models.BooleanField(default=False)
    failed = models.BooleanField(default=False)
    diff = models.TextField(default='')
    msg = models.TextField(default='')
    operator = models.CharField(max_length=100, null=True)
    source = models.CharField(max_length=16, choices=SOURCES, default='batch', db_index=True)
    source_id = models.IntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'change_records'
        ordering = ('-id',)
