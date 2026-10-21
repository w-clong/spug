# -*- mode: python ; coding: utf-8 -*-
"""
Spug 单机版 PyInstaller 打包配置（onedir 目录模式）。

构建命令（在 spug_api 目录下执行）：
    ../spug_web 先执行 npm run build 产出前端产物
    ./venv/bin/pyinstaller spug-standalone.spec --noconfirm

产物：dist/spug/ 目录，包含 spug 可执行文件与 _internal 依赖目录。
运行时数据（数据库/传输/发布/repos）落在可执行文件旁 data/ 目录。
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# PyInstaller 执行 spec 时 sys.path 不含项目目录，若不补上，
# collect_submodules('apps') 会因找不到包而返回空（导致 app 模块漏打包）
sys.path.insert(0, os.getcwd())

hiddenimports = collect_submodules('apps') + collect_submodules('libs') + collect_submodules('consumer') + [
    # Django 项目包：settings/urls/asgi/wsgi 由 django.setup() 按字符串动态导入，
    # 静态分析无法发现，必须显式声明
    'spug',
    'spug.settings',
    'spug.urls',
    'spug.asgi',
    'spug.wsgi',
    # 运行期通过字符串解析加载的模块（settings 中按字符串配置）
    # 注意：这里要写模块名 channels.layers，不能写类路径
    # channels.layers.InMemoryChannelLayer（PyInstaller 只按模块解析 hiddenimports）
    'channels.layers',
    'django.core.cache.backends.locmem',
    'daphne.server',
    'daphne.endpoints',
    # Django app 动态发现的 management commands
    'apps.account.management.commands.updatedb',
    'apps.account.management.commands.user',
    'apps.exec.management.commands.runworker',
    'apps.monitor.management.commands.runmonitor',
    'apps.schedule.management.commands.runscheduler',
    # 托盘图标：pystray 按平台 importlib 动态加载后端，静态分析发现不了
    'pystray',
    'pystray._win32',
]

a = Analysis(
    ['startup.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # 前端编译产物：打进 _internal/spug_web_build（settings.FRONTEND_DIR）
        ('../spug_web/build', 'spug_web_build'),
    ],
    hiddenimports=hiddenimports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'websockets',
        'ldap',
        'django_redis',
        'redis',
        'channels_redis',
        'gunicorn',
        'tkinter',
        'pytest',
        # autobahn.nvx 是 cffi 运行时编译包装，冻结环境下会因缺失
        # _utf8validator.c 抛 FileNotFoundError；已用 AUTOBAHN_USE_NVX=0
        # 强制纯 Python 实现，这里一并排除
        'autobahn.nvx',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='spug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # 桌面模式：不弹出控制台窗口，双击启动后驻留托盘
    console=False,
    icon='../spug_web/public/favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='spug',
)
