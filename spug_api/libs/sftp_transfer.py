# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""纯 paramiko SFTP 文件传输（替代 sshfs/rsync）。

Windows 单机部署没有 sshfs/rsync，Spug 原生的「文件分发」依赖这两个外部命令，
这里改为直接走 SFTP：
  - download_tree: 从远端主机递归下载目录到本地
  - upload_tree:   把本地目录递归上传到远端主机
进度通过回调返回，便于接入原生 WebSocket 控制台。
"""
import os
import posixpath
import stat

CHUNK = 1024 * 256


def _iter_remote_files(sftp, remote_root):
    """深度优先遍历远端目录，产出 (远端绝对路径, 相对路径)。"""
    stack = [(remote_root, '')]
    while stack:
        current, rel = stack.pop()
        try:
            entries = sftp.listdir_attr(current)
        except IOError:
            continue
        for item in entries:
            child = posixpath.join(current, item.filename)
            child_rel = posixpath.join(rel, item.filename) if rel else item.filename
            if stat.S_ISDIR(item.st_mode or 0):
                stack.append((child, child_rel))
            else:
                yield child, child_rel


def download_tree(ssh, remote_dir, local_dir, on_progress=None):
    """递归下载远端目录到本地，返回下载的文件数。"""
    sftp = ssh._get_sftp()
    os.makedirs(local_dir, exist_ok=True)
    count = 0
    total = 0
    for remote_path, rel in _iter_remote_files(sftp, remote_dir):
        target = os.path.join(local_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as dst:
            sftp.getfo(remote_path, dst)
        count += 1
        if on_progress:
            on_progress(rel, count, total)
    return count


def upload_tree(ssh, local_dir, remote_dir, on_progress=None):
    """递归上传本地目录内容到远端目录，返回上传的文件数。"""
    sftp = ssh._get_sftp()
    created = set()
    _mkdirs(sftp, remote_dir, created)
    count = 0
    total = 0
    for root, _dirs, files in os.walk(local_dir):
        rel_root = os.path.relpath(root, local_dir)
        remote_root = remote_dir if rel_root == '.' else posixpath.join(
            remote_dir, rel_root.replace(os.sep, '/'))
        _mkdirs(sftp, remote_root, created)
        for name in files:
            local_path = os.path.join(root, name)
            remote_path = posixpath.join(remote_root, name)
            # putfo 走 paramiko 内部流水线，比手工 chunk 循环快很多
            with open(local_path, 'rb') as src:
                size = os.fstat(src.fileno()).st_size
                sftp.putfo(src, remote_path, confirm=False)
            total += size
            count += 1
            if on_progress and count % 20 == 0:
                on_progress(posixpath.join(rel_root, name) if rel_root != '.' else name,
                            count, total)
    if on_progress:
        on_progress('', count, total)
    return count


def upload_file(ssh, local_path, remote_path):
    sftp = ssh._get_sftp()
    _mkdirs(sftp, posixpath.dirname(remote_path), set())
    with open(local_path, 'rb') as src:
        sftp.putfo(src, remote_path, confirm=False)


def _mkdirs(sftp, path, created=None):
    """递归建目录；created 用于缓存已确认存在的目录，避免每个文件都 stat 一遍。"""
    if not path or path == '/':
        return
    if created is not None and path in created:
        return
    parts = [x for x in path.split('/') if x]
    current = '/' if path.startswith('/') else ''
    for part in parts:
        current = posixpath.join(current, part) if current else part
        if created is not None and current in created:
            continue
        try:
            sftp.stat(current)
        except IOError:
            try:
                sftp.mkdir(current)
            except IOError:
                pass
        if created is not None:
            created.add(current)
