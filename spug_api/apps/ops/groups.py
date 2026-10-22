# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""基于 Facts 的动态分组（对标 Ansible 动态 Inventory）。

规则存于 dynamic_groups.rules：
    [{"key": "os_family", "op": "eq", "value": "Debian"}, ...]
支持 op：eq / ne / in / not_in / gt / ge / lt / le / contains / regex
match_all=True 表示全部满足，否则任一满足。
"""
import re

from apps.ops.kernel import facts as facts_kernel


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def match_rule(rule, facts):
    key = rule.get('key')
    if not key or key not in facts:
        return False
    actual = facts.get(key)
    expected = rule.get('value')
    op = (rule.get('op') or 'eq').lower()

    if op == 'eq':
        return str(actual) == str(expected)
    if op == 'ne':
        return str(actual) != str(expected)
    if op == 'in':
        return str(actual) in [str(x) for x in (expected or [])]
    if op == 'not_in':
        return str(actual) not in [str(x) for x in (expected or [])]
    if op in ('gt', 'ge', 'lt', 'le'):
        left, right = _as_number(actual), _as_number(expected)
        if left is None or right is None:
            return False
        return {'gt': left > right, 'ge': left >= right,
                'lt': left < right, 'le': left <= right}[op]
    if op == 'contains':
        return str(expected) in str(actual)
    if op == 'regex':
        try:
            return bool(re.search(str(expected), str(actual)))
        except re.error:
            return False
    return False


def match(group_rule, facts):
    rules = group_rule.get_rules()
    if not rules:
        return False
    results = [match_rule(x, facts) for x in rules]
    return all(results) if group_rule.match_all else any(results)


def sync_host(host_id):
    """按当前缓存 Facts 维护主机在动态分组中的成员关系。"""
    from apps.host.models import Group
    from apps.ops.models import DynamicGroup

    facts = facts_kernel.load(host_id)
    if not facts:
        return
    for rule in DynamicGroup.objects.filter(enabled=True):
        group = Group.objects.filter(pk=rule.group_id, is_dynamic=True).first()
        if group is None:
            continue
        if match(rule, facts):
            group.hosts.add(host_id)
        else:
            group.hosts.remove(host_id)


def sync_hosts(host_ids):
    for host_id in host_ids:
        try:
            sync_host(host_id)
        except Exception:
            pass


def sync_all():
    from apps.host.models import Host
    sync_hosts(list(Host.objects.values_list('id', flat=True)))
