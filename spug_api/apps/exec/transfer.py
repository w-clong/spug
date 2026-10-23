# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""文件分发：纯 paramiko SFTP 实现（不依赖 sshfs / rsync）。

原版依赖服务端的 sshfs 挂载源目录、rsync 推送到目标主机；Windows 单机部署
没有这些外部命令，因此改为：
  - 源为主机：SFTP 递归下载到本地临时目录
  - 源为上传文件：直接使用已保存的本地目录
  - 分发：SFTP 递归上传到各目标主机
"""
import os
import shutil
import json
import time
import uuid
from concurrent import futures
from threading import Thread

from django.conf import settings
from django.db import close_old_connections
from django.views.generic import View

from libs import json_response, JsonParser, Argument, auth
from libs.memredis import get_redis_connection
from libs.sftp_transfer import download_tree, upload_tree
from libs.utils import human_seconds_time
from libs.validators import path_validator
from libs.locale import get_request_language, translate_console
from apps.exec.models import Transfer
from apps.account.utils import has_host_perm
from apps.host.models import Host
import shlex


class TransferView(View):
    @auth('exec.transfer.do')
    def get(self, request):
        records = Transfer.objects.filter(user=request.user)
        return json_response([x.to_view() for x in records])

    @auth('exec.transfer.do')
    def post(self, request):
        data = request.POST.get('data')
        form, error = JsonParser(
            Argument('host', type=list, required=False, help='请选择数据源主机'),
            Argument('dst_dir', filter=path_validator, help='目标路径必须为绝对路径，且不能包含空格及特殊字符'),
            Argument('host_ids', type=list, filter=lambda x: len(x), help='请选择目标主机'),
        ).parse(data)
        if error is None:
            if not has_host_perm(request.user, form.host_ids):
                return json_response(error='无权访问主机，请联系管理员')
            host_id = None
            token = uuid.uuid4().hex
            base_dir = os.path.join(settings.TRANSFER_DIR, token)
            if form.host:
                if len(form.host) != 2:
                    return json_response(error='请选择数据源主机')
                host_id, path = form.host
                if not has_host_perm(request.user, [host_id]):
                    return json_response(error='无权访问主机，请联系管理员')
                if not path_validator(path) or not path.strip().strip('/'):
                    return json_response(error='数据源路径必须为绝对路径，且不能包含空格及特殊字符')
                path = path.strip()
                host = Host.objects.get(pk=host_id)
                with host.get_ssh() as ssh:
                    code, _ = ssh.exec_command_raw(f'[ -d {shlex.quote(path)} ]')
                    if code != 0:
                        return json_response(error='数据源路径必须为该主机上已存在的目录')
                os.makedirs(base_dir)
                # 源为主机时 src_dir 存远端路径，本地临时目录用 token 推导
                src_dir = path
            else:
                os.makedirs(base_dir)
                index = 0
                while True:
                    file = request.FILES.get(f'file{index}')
                    if not file:
                        break
                    with open(os.path.join(base_dir, file.name), 'wb') as f:
                        for chunk in file.chunks():
                            f.write(chunk)
                    index += 1
                src_dir = base_dir
            Transfer.objects.create(
                user=request.user,
                digest=token,
                host_id=host_id,
                src_dir=src_dir,
                dst_dir=form.dst_dir,
                host_ids=json.dumps(form.host_ids),
            )
            return json_response(token)
        return json_response(error=error)

    @auth('exec.transfer.do')
    def patch(self, request):
        form, error = JsonParser(
            Argument('token', help='参数错误')
        ).parse(request.body)
        if error is None:
            task = Transfer.objects.get(digest=form.token)
            Thread(target=_dispatch_sync, args=(task, get_request_language(request))).start()
        return json_response(error=error)


def _local_dir(task):
    if task.host_id:
        return os.path.join(settings.TRANSFER_DIR, task.digest)
    return task.src_dir


def _dispatch_sync(task, language='zh'):
    rds = get_redis_connection()
    local_dir = _local_dir(task)
    try:
        if task.host_id:
            source = Host.objects.get(pk=task.host_id)
            rds.publish(task.digest, json.dumps({
                'key': task.host_id,
                'data': translate_console('\r\n\x1b[36m### 从数据源主机拉取文件 ...\x1b[0m\r\n', language)
            }))
            with source.get_ssh() as ssh:
                def on_download(rel, count, total):
                    if count % 20 == 0:
                        rds.publish(task.digest, json.dumps({
                            'key': task.host_id,
                            'data': f'\r\x1b[90m拉取 {rel}（{count} 个文件）\x1b[0m'
                        }))
                download_tree(ssh, task.src_dir, local_dir, on_download)
    except Exception as e:
        for host_id in json.loads(task.host_ids):
            rds.publish(task.digest, json.dumps({
                'key': host_id, 'status': -1,
                'data': translate_console(f'\r\n\x1b[31m拉取数据源失败: {e}\x1b[0m', language)
            }))
        _cleanup(local_dir, task)
        return

    threads = []
    max_workers = max(10, os.cpu_count() * 5)
    with futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for host in Host.objects.filter(id__in=json.loads(task.host_ids)):
            t = executor.submit(_do_sync, rds, task, host, local_dir, language)
            t.token = task.digest
            t.key = host.id
            threads.append(t)
        for t in futures.as_completed(threads):
            exc = t.exception()
            if exc:
                rds.publish(
                    t.token,
                    json.dumps({'key': t.key, 'status': -1,
                                'data': f'\x1b[31mException: {exc}\x1b[0m'})
                )
    _cleanup(local_dir, task)
    close_old_connections()


def _cleanup(local_dir, task):
    if task.host_id:
        shutil.rmtree(local_dir, ignore_errors=True)


def _do_sync(rds, task, host, local_dir, language='zh'):
    token = task.digest
    rds.publish(token, json.dumps({
        'key': host.id,
        'data': translate_console('\r\n\x1b[36m### 开始分发 ...\x1b[0m\r\n', language)
    }))
    flag = time.time()
    try:
        with host.get_ssh() as ssh:
            def on_progress(rel, count, total):
                if count % 10 == 0:
                    rds.publish(token, json.dumps({
                        'key': host.id,
                        'data': f'\r\x1b[90m上传 {rel}（{count} 个文件）\x1b[0m'
                    }))
            count = upload_tree(ssh, local_dir, task.dst_dir, on_progress)
        human_time = human_seconds_time(time.time() - flag)
        rds.publish(token, json.dumps({
            'key': host.id,
            'data': translate_console(
                f'\r\n\x1b[32m** 分发完成，共 {count} 个文件，耗时：{human_time} **\x1b[0m', language)
        }))
        rds.publish(token, json.dumps({'key': host.id, 'status': 0}))
    except Exception as e:
        rds.publish(token, json.dumps({
            'key': host.id,
            'data': translate_console(f'\r\n\x1b[31m分发失败: {e}\x1b[0m', language)
        }))
        rds.publish(token, json.dumps({'key': host.id, 'status': -1}))
