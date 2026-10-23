# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""Spug 主机对象 -> pyinfra Inventory 的转换层。

安全约束：
  - 私钥只在内存中通过 Spug 原生 paramiko 的 load_pkey 解析成 PKey 对象，
    再注入 pyinfra State.private_keys 缓存；
  - 不写临时文件、不把私钥拼进命令行、不落库。

实现说明：
  pyinfra 的 SSH 连接器要求 ssh_key 是「文件路径」，它内部用
  get_private_key(state, key_filename, key_password) 读取并缓存到
  state.private_keys。这里传入一个 spug:// 伪路径，并预先填充
  state.private_keys，让连接器直接命中缓存，从而避开落盘。
"""
from pathlib import Path

from pyinfra.api import Inventory


def _empty_known_hosts():
    """返回一个空的 known_hosts 文件路径（进程内只需创建一次）。"""
    try:
        from django.conf import settings
        base = Path(settings.DATA_DIR) / 'tmp'
    except Exception:
        import tempfile
        base = Path(tempfile.gettempdir()) / 'spug'
    base.mkdir(parents=True, exist_ok=True)
    path = base / 'empty_known_hosts'
    if not path.exists():
        path.write_text('', encoding='utf-8')
    return str(path)


_EMPTY_KNOWN_HOSTS = _empty_known_hosts()

# 与 Spug 原生 SSH 行为保持一致：不校验 known_hosts
SSH_DATA = {
    'ssh_forward_agent': False,
    'ssh_allow_agent': False,
    'ssh_look_for_keys': False,
    # 与 Spug 原生 AutoAddPolicy 对齐；pyinfra 该字段是枚举字符串
    'ssh_strict_host_key_checking': 'no',
    # pyinfra 的 paramiko 连接器在未指定 known_hosts 文件时会读取用户的
    # ~/.ssh/known_hosts，主机重装后密钥变化会直接导致连接失败（BadHostKeyException）。
    # 指向一个空的临时文件，等价于 Spug 原生「不校验」的行为。
    'ssh_known_hosts_file': _EMPTY_KNOWN_HOSTS,
}


def key_ref(host):
    return f'spug://key/{host.id}'


def build_inventory(hosts):
    """把 Spug Host 列表转换为 pyinfra Inventory，返回 (inventory, name_map)。"""
    entries = []
    name_map = {}
    for host in hosts:
        name = host.name or host.hostname
        # pyinfra 主机名需唯一，同名主机追加 id 后缀
        if name in name_map.values():
            name = f'{name}#{host.id}'
        name_map[host.id] = name
        data = dict(SSH_DATA)
        data.update({
            'spug_id': host.id,
            'spug_name': host.name,
            'ssh_hostname': host.hostname,
            'ssh_port': host.port or 22,
            'ssh_user': host.username or 'root',
        })
        password = getattr(host, 'password', None)
        if password:
            # 密码认证：pyinfra 连接器直接使用 paramiko 的 password 参数
            data['ssh_password'] = password
        else:
            data['ssh_key'] = key_ref(host)
        entries.append((name, data))
    return Inventory((entries, {})), name_map


def inject_private_keys(state, hosts):
    """把私钥解析为 paramiko PKey 注入 pyinfra 缓存，避免写入磁盘。

    密码认证的主机不注入私钥，由 pyinfra 的 ssh_password 处理。
    """
    from libs.ssh import SSH
    default_key = None
    for host in hosts:
        if getattr(host, 'password', None):
            continue
        pkey = host.pkey
        if not pkey:
            if default_key is None:
                from apps.setting.utils import AppSetting
                # get_default 而非 get：从未生成过全局密钥时应给出可读错误，
                # 而不是在这里抛 KeyError
                default_key = AppSetting.get_default('private_key') or ''
            pkey = default_key
        if not pkey:
            raise ValueError(f'主机 {host.name} 未配置可用的 SSH 私钥或密码，请先在主机管理中验证该主机')
        state.private_keys[key_ref(host)] = SSH.load_pkey(pkey)
