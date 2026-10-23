from libs.utils import str_decode, NO_WINDOW
import subprocess
import shutil
import sys
import re
import os


class Executor:
    def __init__(self, default_env=None):
        self.regex = re.compile(r'(?<!echo )Spug EOF 2108111926 (-?\d+)[\r\n]?')
        self.default_env = default_env
        self.task = None

    @property
    def pid(self):
        if self.task:
            return self.task.pid
        return None

    def get_envs(self):
        envs = {}
        _, output = self.exec_command('env | grep SPUG_')
        if output:
            for item in output.splitlines():
                if '=' in item:
                    key, val = item.split('=', 1)
                    envs[key] = val
        return envs

    def exec_command_with_stream(self, command):
        command += '\necho Spug EOF 2108111926 $?\n'
        self.task.stdin.write(command.encode())
        self.task.stdin.flush()
        exit_code, message,  = -1, b''
        while True:
            output = self.task.stdout.read(1)
            if not output:
                exit_code, message = self.task.wait(), ''
                break
            if output in (b'\r', b'\n'):
                message += b'\r\n' if output == b'\n' else b'\r'
                message = str_decode(message)
                match = self.regex.search(message)
                if match:
                    exit_code = int(match.group(1))
                    message = message[:match.start()]
                    break
                yield exit_code, message
                message = b''
            else:
                message += output
        yield exit_code, message

    def exec_command(self, command):
        exit_code, message = -1, ''
        for exit_code, line in self.exec_command_with_stream(command):
            message += line
        return exit_code, message

    def __enter__(self):
        env = None
        if self.default_env is not None:
            env = dict(os.environ)
            env.update({k: str(v) for k, v in self.default_env.items()})
        # 构建/发布/流水线的本地步骤都按 POSIX shell 语义书写（依赖 bash）。
        # Windows 上 os.setsid/preexec_fn 不可用，且 bash 通常不在 PATH，
        # 这里显式定位 Git for Windows 自带的 bash.exe，找不到时给出可操作的错误。
        if sys.platform == 'win32':
            exe = shutil.which('bash') or next(
                (p for p in (
                    r'C:\Program Files\Git\bin\bash.exe',
                    r'C:\Program Files\Git\usr\bin\bash.exe',
                    r'C:\Program Files (x86)\Git\bin\bash.exe',
                ) if os.path.isfile(p)),
                None
            )
            if not exe:
                raise RuntimeError(
                    '未找到 bash：Windows 下构建/发布/流水线的本地步骤依赖 bash，'
                    '请安装 Git for Windows 并确保其 bin 目录在 PATH 中'
                )
            program, popen_kwargs = f'"{exe}"', dict(NO_WINDOW)
        else:
            program, popen_kwargs = 'bash', {'preexec_fn': os.setsid}
        self.task = subprocess.Popen(
            program,
            env=env,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **popen_kwargs
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.task:
            self.task.kill()
