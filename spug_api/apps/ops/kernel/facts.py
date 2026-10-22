# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Facts 采集与缓存（方案2：pyinfra 实时采集 + 数据库持久化）。

只缓存低频静态信息：os / os_family / os_version / arch / kernel / hostname / memory / cpu。
包状态、服务状态、文件内容等动态信息不缓存，由 pyinfra 状态模块在每次执行时实时判断。
"""
import json

from pyinfra.facts import hardware, server

# fact_key -> (pyinfra Fact 类, 是否写入 _SPUG_FACT_* 环境变量)
FACT_DEFS = {
    'os': server.Os,
    # OsRelease 解析 /etc/os-release，包含 id/id_like/version_id，比 LinuxDistribution 稳定
    'os_release': server.OsRelease,
    'kernel': server.Kernel,
    'kernel_version': server.OsVersion,
    'arch': server.Arch,
    'hostname': server.Hostname,
    'memory': hardware.Memory,
    'cpu': hardware.CpuInfo,
}

# 发行版 id/name -> 包管理器族
_DEBIAN = ('debian', 'ubuntu', 'linuxmint', 'kali', 'raspbian', 'deepin')
_REDHAT = ('centos', 'redhat', 'rhel', 'fedora', 'rocky', 'almalinux', 'ol', 'oracle')
_ALPINE = ('alpine',)


def family_of(facts):
    """从 pyinfra 采集的 os_release 推导 os_family（pyinfra 3 不再提供 OsFamily）。"""
    release = facts.get('os_release') or {}
    ident = ''
    if isinstance(release, dict):
        ident = ' '.join(str(release.get(k) or '') for k in ('id', 'name', 'id_like')).lower()
    ident = ident or (facts.get('os') or '').lower()
    if any(x in ident for x in _ALPINE):
        return 'Alpine'
    if any(x in ident for x in _DEBIAN):
        return 'Debian'
    if any(x in ident for x in _REDHAT):
        return 'RedHat'
    return 'Linux'


def collect(host):
    """对单个已连接主机实时采集静态 Facts，返回 {key: value}。"""
    result = {}
    for key, fact_cls in FACT_DEFS.items():
        try:
            value = host.get_fact(fact_cls)
        except Exception:
            # 单条 fact 失败（例如精简系统缺少命令）不应影响其他 fact
            continue
        if value is None:
            continue
        try:
            json.dumps(value)
        except TypeError:
            value = str(value)
        result[key] = value
    # 统一补充一组便于模板使用的派生字段
    if result:
        result['os_family'] = family_of(result)
        release = result.get('os_release')
        if isinstance(release, dict):
            version = release.get('version_id') or release.get('version')
            if version:
                result['os_version'] = version
    if result.get('memory') and isinstance(result['memory'], dict):
        total = result['memory'].get('MemTotal') or result['memory'].get('total')
        if total:
            try:
                result['memory_total_mb'] = int(total) // 1024
            except (TypeError, ValueError):
                pass
    return result


def save(host_id, facts):
    """把采集结果持久化到 host_facts（覆盖同 key 旧值）。"""
    from apps.ops.models import HostFact
    for key, value in facts.items():
        HostFact.objects.update_or_create(
            host_id=host_id,
            fact_key=key,
            defaults={'fact_value': json.dumps(value, ensure_ascii=False)},
        )
    return facts


def load(host_id):
    """读取某主机的缓存 Facts，返回 {key: value}。"""
    from apps.ops.models import HostFact
    return {
        x.fact_key: json.loads(x.fact_value)
        for x in HostFact.objects.filter(host_id=host_id)
    }


def load_many(host_ids):
    from apps.ops.models import HostFact
    result = {x: {} for x in host_ids}
    for item in HostFact.objects.filter(host_id__in=host_ids):
        result.setdefault(item.host_id, {})[item.fact_key] = json.loads(item.fact_value)
    return result


def to_env(facts):
    """Facts -> _SPUG_FACT_* 环境变量，全平台所有执行节点统一注入。"""
    env = {}
    for key, value in facts.items():
        if isinstance(value, (dict, list)):
            env[f'_SPUG_FACT_{key.upper()}'] = json.dumps(value, ensure_ascii=False)
        else:
            env[f'_SPUG_FACT_{key.upper()}'] = '' if value is None else str(value)
    return env
