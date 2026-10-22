# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""动态分组自检（使用伪造 Facts，不连接主机）。"""
import json
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django  # noqa: E402

django.setup()

from apps.account.models import User  # noqa: E402
from apps.host.models import Group, Host  # noqa: E402
from apps.ops.groups import sync_hosts  # noqa: E402
from apps.ops.models import DynamicGroup, HostFact  # noqa: E402


def main():
    user = User.objects.filter(username='dyn-tester').first() or User.objects.create(
        username='dyn-tester', nickname='dyn', password_hash='x', is_supper=True)
    debian = Host.objects.filter(name='dyn-debian').first() or Host.objects.create(
        name='dyn-debian', hostname='10.9.9.1', port=22, username='root', pkey='x', created_by=user)
    redhat = Host.objects.filter(name='dyn-redhat').first() or Host.objects.create(
        name='dyn-redhat', hostname='10.9.9.2', port=22, username='root', pkey='x', created_by=user)
    for host, family, version in ((debian, 'Debian', '24.04'), (redhat, 'RedHat', '9.7')):
        HostFact.objects.update_or_create(host_id=host.id, fact_key='os_family',
                                          defaults={'fact_value': json.dumps(family)})
        HostFact.objects.update_or_create(host_id=host.id, fact_key='os_version',
                                          defaults={'fact_value': json.dumps(version)})

    group, _ = Group.objects.get_or_create(name='dyn-test-debian')
    DynamicGroup.objects.update_or_create(
        group_id=group.id,
        defaults=dict(name='Debian 系', enabled=True, match_all=True,
                      rules=json.dumps([{'key': 'os_family', 'op': 'eq', 'value': 'Debian'}])))
    Group.objects.filter(pk=group.id).update(is_dynamic=True)

    sync_hosts([debian.id, redhat.id])
    members = set(group.hosts.values_list('id', flat=True))
    assert debian.id in members and redhat.id not in members, members
    print('dynamic group ok: members =', members)

    # 清理
    DynamicGroup.objects.filter(group_id=group.id).delete()
    group.delete()
    debian.delete()
    redhat.delete()
    print('dynamic group selftest passed')


if __name__ == '__main__':
    main()
