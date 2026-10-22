# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""统一变量上下文自检：优先级、Facts 只读、无主机模式、渲染报错提示。"""
import json
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Group, Host  # noqa: E402
from apps.pipeline.models import Pipeline  # noqa: E402
from apps.setting.utils import AppSetting  # noqa: E402
from apps.ops.context import get_merged_context, render_jinja, render_with_context  # noqa: E402
from apps.ops.models import GroupVariable, HostFact, HostVariable  # noqa: E402
from libs.utils import SpugError  # noqa: E402


def main():
    user = User.objects.filter(username='ctx-tester').first() or User.objects.create(
        username='ctx-tester', nickname='ctx', password_hash='x', is_supper=True)
    group, _ = Group.objects.get_or_create(name='ctx-group')
    host, _ = Host.objects.get_or_create(
        name='ctx-host', defaults=dict(hostname='10.8.8.8', port=22, username='root',
                                       pkey='x', created_by=user))
    host.groups.set([group])

    AppSetting.set('global_variables', {'shared': 'global', 'global_only': 'g'})
    GroupVariable.objects.update_or_create(group_id=group.id, key='shared', defaults={'value': 'env'})
    GroupVariable.objects.update_or_create(group_id=group.id, key='env_only', defaults={'value': 'e'})
    HostVariable.objects.update_or_create(host_id=host.id, key='shared', defaults={'value': 'host'})
    HostVariable.objects.update_or_create(host_id=host.id, key='host_only', defaults={'value': 'h'})
    # 故意用 host_var 覆盖同名 Fact，验证 Facts 只读优先
    HostVariable.objects.update_or_create(host_id=host.id, key='os_family', defaults={'value': 'HACK'})
    for key, value in (('os_family', 'Debian'), ('os_version', '24.04'),
                       ('hostname', 'ctx-host'), ('dirty_key', 'should-not-appear')):
        HostFact.objects.update_or_create(host_id=host.id, fact_key=key,
                                          defaults={'fact_value': json.dumps(value)})

    Pipeline.objects.filter(name='ctx-pipeline').delete()
    pipe = Pipeline.objects.create(
        name='ctx-pipeline', created_by=user,
        nodes=json.dumps([
            {'id': 1, 'module': 'parameter', 'static_params': [['shared', 'pipeline'], ['pipe_only', 'p']]},
            {'id': 2, 'module': 'ssh_exec', 'targets': [host.id]},
        ]))

    context, variables, _ = get_merged_context(pipe.id, host.id)
    assert context['shared'] == 'host', context
    assert context['env_only'] == 'e' and context['global_only'] == 'g'
    assert context['pipe_only'] == 'p' and context['host_only'] == 'h'
    assert context['os_family'] == 'Debian', 'Facts 应覆盖 host_var'
    assert 'dirty_key' not in context, '未注册 Facts 不应出现'
    labels = {x['name']: x['source'] for x in variables}
    assert labels['shared'] == 'host' and labels['os_family'] == 'fact'
    print('priority/facts ok:', {k: context[k] for k in ('shared', 'os_family', 'env_only')})

    # 无主机模式：应包含 Facts 元信息，不包含主机变量
    _, no_host_vars, _ = get_merged_context(pipe.id, None)
    names = {x['name'] for x in no_host_vars}
    assert 'os_family' in names and 'host_only' not in names
    print('no-host mode ok:', sorted(names)[:5])

    # 渲染：正常 + 报错提示
    assert render_with_context('{{ shared }}-{{ os_family }}', pipe.id, host.id) == 'host-Debian'
    try:
        render_jinja('{{ missing_var }}', context)
        raise AssertionError('should raise')
    except SpugError as e:
        assert '模板渲染失败' in str(e) and '变量面板' in str(e), str(e)
        print('render error ok:', str(e)[:40])

    # 清理
    pipe.delete()
    host.delete()
    group.delete()
    print('context selftest passed')


if __name__ == '__main__':
    main()
