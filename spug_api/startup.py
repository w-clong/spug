#!/usr/bin/env python3
# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
Spug 单进程一体化启动器（免 MySQL / 免 Redis）。

用法：
    spug.exe            桌面模式：初始化 + 启动服务 + 自动打开浏览器 + 托盘常驻
    spug.exe init       初始化数据库并创建管理员（重复执行安全）
    spug.exe start      无界面模式：只启动服务（适合服务器/开机自启）

环境变量：
    SPUG_HOST        监听地址，默认 0.0.0.0
    SPUG_PORT        监听端口，默认 9000
    SPUG_DATA_DIR    数据目录（数据库/传输/发布/repos/日志），默认 <运行根>/data
    SPUG_ADMIN_USER  初始管理员用户名，默认 admin
    SPUG_ADMIN_PASSWORD  初始管理员密码，默认 admin
    SPUG_SECRET_KEY  Django 密钥
    SPUG_DEBUG       置为 1 开启 Django DEBUG
    SPUG_NO_BROWSER  置为 1 时桌面模式不自动打开浏览器
    SPUG_NO_TRAY     置为 1 时桌面模式不创建托盘图标
    SPUG_BROWSER_CMD 自定义打开浏览器命令，%s 会替换为地址（可选）

官方 4 进程（gunicorn + daphne + worker + monitor）在此合并为单进程：
    - HTTP API 与 WebSocket 由 daphne 一个端口提供（ASGI 应用同时处理两者）
    - 任务计划调度器、监控调度器、执行 worker 以守护线程运行
    - Redis 队列/缓存/通道全部由 libs.memredis 内存层替代
"""
import os
import sys
import time
import socket
import threading
from pathlib import Path

# 冻结环境（PyInstaller）：以可执行文件所在目录为运行根；源码运行以仓库根为运行根
_FROZEN = getattr(sys, 'frozen', False)
_ROOT = Path(sys.executable).resolve().parent if _FROZEN else Path(__file__).resolve().parent.parent

os.environ.setdefault('SPUG_DATA_DIR', str(_ROOT / 'data'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
# autobahn 的 NVX 原生加速在 PyInstaller 冻结环境下会误走 cffi 运行时编译回退
# （需要读取 _utf8validator.c 源码），强制使用纯 Python 实现（功能等价，性能差异可忽略）
os.environ.setdefault('AUTOBAHN_USE_NVX', '0')

_log_file = None


def _log(msg):
    print(f'[spug] {msg}', flush=True)


def _redirect_streams(reason):
    """无控制台（windowed）或桌面模式下，把 stdout/stderr 落到 data/spug.log。"""
    global _log_file
    if _log_file is not None:
        return
    try:
        data_dir = Path(os.environ['SPUG_DATA_DIR'])
        data_dir.mkdir(parents=True, exist_ok=True)
        _log_file = open(data_dir / 'spug.log', 'a', encoding='utf-8', errors='replace', buffering=1)
    except OSError as e:
        # 连日志都写不了时只能放弃，但不要因此阻止启动
        print(f'[spug] 无法写入日志文件: {e!r}', file=sys.stderr if sys.stderr else None)
        return
    _log_file.write(f'\n===== {time.strftime("%Y-%m-%d %H:%M:%S")} {reason} =====\n')
    _log_file.flush()
    sys.stdout = sys.stderr = _log_file


import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402


def _ensure_dirs():
    for p in (settings.DATA_DIR,
              Path(settings.TRANSFER_DIR),
              Path(settings.DEPLOY_DIR),
              Path(settings.REPOS_DIR),
              Path(settings.BUILD_DIR)):
        p.mkdir(parents=True, exist_ok=True)


def _ensure_admin():
    """创建初始管理员（幂等），默认 admin / admin。"""
    from apps.account.models import User
    if User.objects.filter(is_deleted=False).exists():
        _log('已存在用户，跳过管理员创建')
        return
    username = os.environ.get('SPUG_ADMIN_USER', 'admin')
    password = os.environ.get('SPUG_ADMIN_PASSWORD', 'admin')
    User.objects.create(
        username=username,
        nickname='管理员',
        password_hash=User.make_password(password),
        is_supper=True,
    )
    _log('管理员创建完成: %s / %s' % (username, password))
    _log('（默认口令仅用于首次登录，请登录后立即修改）')


def cmd_init():
    """初始化数据库 + 创建管理员（幂等）。"""
    _ensure_dirs()
    _log('数据目录: %s' % settings.DATA_DIR)
    _log('SQLite 数据库: %s' % settings.DB_FILE)
    from django.core.management import call_command
    apps = [x.split('.')[-1] for x in settings.INSTALLED_APPS if x.startswith('apps.')]
    _log('生成迁移文件 ...')
    call_command('makemigrations', *apps, interactive=False, verbosity=1)
    _log('应用迁移 ...')
    call_command('migrate', verbosity=1)
    # SQLite WAL 模式：降低单进程多线程下的写锁冲突
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=30000')
    _ensure_admin()


def _start_threads():
    from apps.schedule.scheduler import Scheduler as ScheduleScheduler
    from apps.monitor.scheduler import Scheduler as MonitorScheduler
    from apps.exec.management.commands.runworker import Worker
    targets = [
        ('spug-schedule', ScheduleScheduler().run),
        ('spug-monitor', MonitorScheduler().run),
        ('spug-worker', Worker().run),
    ]
    for name, fn in targets:
        t = threading.Thread(target=fn, name=name, daemon=True)
        t.start()
        _log('%s 线程已启动' % name)


def _build_server(host, port, signal_handlers):
    from spug.asgi import application
    from daphne.server import Server
    from daphne.endpoints import build_endpoint_description_strings
    return Server(
        application=application,
        endpoints=build_endpoint_description_strings(host=host, port=port),
        signal_handlers=signal_handlers,
    )


def _run_daphne(host, port, signal_handlers=True):
    _log('Spug 服务启动: http://%s:%s  （HTTP API + WebSocket 同一端口）' % (host, port))
    _build_server(host, port, signal_handlers).run()


def cmd_start():
    _ensure_dirs()
    _start_threads()
    host = os.environ.get('SPUG_HOST', '0.0.0.0')
    port = int(os.environ.get('SPUG_PORT', '9000'))
    _run_daphne(host, port)


# ---------------------------------------------------------------- 桌面模式

def _port_open(port, host='127.0.0.1'):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _is_spug(port):
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as r:
            return b'<title>Spug' in r.read(4096)
    except Exception:
        return False


def _wait_until_ready(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.2)
    return False


def _alert(message):
    """无控制台时的错误提示（只依赖 Win32 MessageBox，避免额外依赖）。"""
    _log(message)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'Spug', 0x40)
    except Exception:
        pass


def _tray_image():
    from PIL import Image
    ico = Path(settings.FRONTEND_DIR) / 'favicon.ico'
    if ico.is_file():
        try:
            return Image.open(ico)
        except Exception:
            pass
    img = Image.new('RGBA', (64, 64), (22, 119, 255, 255))
    from PIL import ImageDraw
    ImageDraw.Draw(img).text((24, 22), 'S', fill=(255, 255, 255, 255))
    return img


def _open_browser(url):
    """打开默认浏览器；SPUG_BROWSER_CMD 可用于指定浏览器（如便携版/指定 Chrome）。"""
    cmd = os.environ.get('SPUG_BROWSER_CMD')
    if cmd:
        try:
            import subprocess
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
            subprocess.Popen(cmd.replace('%s', url), shell=True, creationflags=flags)
            return
        except Exception as e:
            _log('SPUG_BROWSER_CMD 执行失败（%r），回退到默认浏览器' % (e,))
    import webbrowser
    webbrowser.open(url)


def _start_tray(url):
    """创建托盘图标（菜单：打开界面 / 退出），返回 icon 对象或 None。"""
    if os.environ.get('SPUG_NO_TRAY') == '1':
        _log('SPUG_NO_TRAY=1，跳过托盘')
        return None
    try:
        import pystray
    except Exception as e:
        _log('托盘组件不可用（%r），服务继续运行' % (e,))
        return None

    def on_open(icon=None, item=None):
        _open_browser(url)

    def on_quit(icon=None, item=None):
        _log('收到退出请求，正在停止服务 ...')
        try:
            if icon is not None:
                icon.stop()
        finally:
            try:
                from twisted.internet import reactor
                if reactor.running:
                    reactor.callFromThread(reactor.stop)
                else:
                    reactor.callWhenRunning(reactor.stop)
            except Exception as e:
                _log('停止服务失败: %r' % (e,))
            # 兜底：3 秒后仍未退出则强制结束，避免托盘退出后进程残留
            threading.Timer(3.0, lambda: os._exit(0)).start()

    menu = pystray.Menu(
        pystray.MenuItem('打开 Spug 界面', on_open, default=True),
        pystray.MenuItem('退出', on_quit),
    )
    icon = pystray.Icon('spug', _tray_image(), 'Spug 运维平台', menu)
    try:
        icon.run_detached()
    except Exception as e:
        _log('托盘启动失败: %r' % (e,))
        return None
    _log('托盘图标已就绪（右键菜单：打开界面 / 退出）')
    return icon


def _db_ready():
    """数据库是否已初始化（有表且至少一个用户）。"""
    db = Path(settings.DB_FILE)
    if not db.is_file() or db.stat().st_size == 0:
        return False
    try:
        from apps.account.models import User
        return User.objects.filter(is_deleted=False).exists()
    except Exception:
        return False


def _auto_init():
    from django.core.management import call_command
    _log('首次运行，正在初始化数据库 ...')
    call_command('migrate', interactive=False, verbosity=0)
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute('PRAGMA journal_mode=WAL')
        cur.execute('PRAGMA busy_timeout=30000')
    _ensure_admin()


def cmd_desktop():
    """双击启动：自动建库、起服务、开浏览器、驻留托盘。"""
    _redirect_streams('桌面模式启动')
    _ensure_dirs()
    host = os.environ.get('SPUG_HOST', '0.0.0.0')
    port = int(os.environ.get('SPUG_PORT', '9000'))
    url = f'http://127.0.0.1:{port}/'

    if _port_open(port):
        if _is_spug(port):
            _log('检测到已有实例在 %s 运行，直接打开界面' % url)
            _open_browser(url)
            return
        _alert(f'端口 {port} 已被其他程序占用，Spug 无法启动。\n\n'
               f'可以设置环境变量 SPUG_PORT 换一个端口后重试。')
        return

    try:
        if not _db_ready():
            _auto_init()
        _start_threads()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _alert(f'Spug 启动失败：{e}\n\n详细信息见 data\\spug.log')
        return

    icon = _start_tray(url)

    def open_browser_when_ready():
        if os.environ.get('SPUG_NO_BROWSER') == '1':
            _log('SPUG_NO_BROWSER=1，跳过打开浏览器')
            return
        if _wait_until_ready(port):
            _log('打开浏览器: %s' % url)
            _open_browser(url)
        else:
            _log('等待服务就绪超时（%s）' % url)

    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    _log('Spug 已启动，日志: %s' % (Path(os.environ['SPUG_DATA_DIR']) / 'spug.log'))
    try:
        _run_daphne(host, port, signal_handlers=False)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _alert(f'Spug 服务异常退出：{e}\n\n详细信息见 data\\spug.log')
    finally:
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'desktop'
    if cmd in ('desktop', 'gui'):
        cmd_desktop()
    elif cmd == 'init':
        if sys.stdout is None or sys.stderr is None:
            _redirect_streams('init')
        cmd_init()
    elif cmd in ('start', 'run'):
        if sys.stdout is None or sys.stderr is None:
            _redirect_streams('start')
        cmd_start()
    else:
        _log('用法: spug.exe [init|start]（不带参数为桌面模式）')
        sys.exit(2)


if __name__ == '__main__':
    main()
