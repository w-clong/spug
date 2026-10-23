# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.conf import settings
from libs.memredis import get_redis_connection
from libs.utils import human_seconds_time, wrap_python_command
from libs.ssh import SSH
from libs.locale import translate_console
import threading
import socket
import json
import time
import logging


def exec_worker_handler(job):
    try:
        job = Job(**json.loads(job))
    except Exception as e:
        # 工作线程里的异常不会有人捕获，前端只会一直停在“Waiting for scheduling”。
        # 这里把失败原因回写到该任务的输出通道，并在日志中留下堆栈。
        data = json.loads(job)
        logging.exception('exec job init failed')
        try:
            rds = get_redis_connection()
            rds.publish(data.get('token'), json.dumps({
                'key': data.get('key'),
                'data': f'\r\n\x1b[31m### Exception {e}\x1b[0m',
                'status': 1,
            }))
        except Exception:
            pass
        return
    threading.Thread(target=job.run).start()


class Job:
    def __init__(self, token, key, name, hostname, port, username, pkey=None, command=None, interpreter='sh',
                 params=None, term=None, language='zh', record=False, password=None):
        self.ssh = SSH(hostname, port, username, pkey, password=password, term=term)
        self.key = key
        self.command = self._handle_command(command, interpreter)
        self.token = token
        self.rds = get_redis_connection()
        self.rds_key = f'PID:{self.token}:{self.key}'
        # 开放 API 触发的任务没有 WebSocket 订阅者，需把输出与状态落到 redis 供结果接口查询
        self.record_key = f'{settings.EXEC_RESULT_KEY}:{self.token}' if record else None
        # 发起执行的用户界面语言，仅用于翻译 Spug 自身产生的提示，命令输出原样透传
        self.language = language
        self.env = dict(
            SPUG_HOST_ID=str(self.key),
            SPUG_HOST_NAME=name,
            SPUG_HOST_HOSTNAME=hostname,
            SPUG_SSH_PORT=str(port),
            SPUG_SSH_USERNAME=username,
            SPUG_INTERPRETER=interpreter
        )
        if isinstance(params, dict):
            self.env.update({f'_SPUG_{k}': str(v) for k, v in params.items()})
        # 统一注入 Facts 与主机/分组变量（_SPUG_FACT_* / _SPUG_VAR_*）
        try:
            from apps.host.models import Host
            from apps.ops.kernel import variables as var_kernel
            host_obj = Host.objects.filter(pk=self.key).first()
            if host_obj:
                _, extra_env = var_kernel.collect(host_obj)
                self.env.update(extra_env)
        except Exception:
            pass

    def _send(self, message):
        self.rds.publish(self.token, json.dumps(message))
        if self.record_key:
            if message.get('data'):
                self.rds.append(f'{self.record_key}:{self.key}', message['data'])
                self.rds.expire(f'{self.record_key}:{self.key}', 3600)
            if 'status' in message:
                self.rds.hset(self.record_key, f'status:{self.key}', message['status'])

    def _handle_command(self, command, interpreter):
        if interpreter == 'python':
            return wrap_python_command(command)
        return command

    def send(self, data):
        self._send({'key': self.key, 'data': data})

    def send_status(self, code):
        self._send({'key': self.key, 'status': code})

    def run(self):
        flag = time.time()
        self.send('\r\n\x1b[36m### Executing ...\x1b[0m\r\n')
        code = -1
        try:
            with self.ssh:
                pid = self.ssh.get_pid()
                if pid:
                    self.rds.set(self.rds_key, pid, 3600)
                for code, out in self.ssh.exec_command_with_stream(self.command, self.env):
                    self.send(out)
            human_time = human_seconds_time(time.time() - flag)
            self.send(translate_console(f'\r\n\x1b[36m** 执行结束，耗时：{human_time} **\x1b[0m', self.language))
        except socket.timeout:
            code = 130
            self.send('\r\n\x1b[31m### Time out\x1b[0m')
        except Exception as e:
            code = 131
            self.send(f'\r\n\x1b[31m### Exception {e}\x1b[0m')
            raise e
        finally:
            self.rds.delete(self.rds_key)
            self.send_status(code)
