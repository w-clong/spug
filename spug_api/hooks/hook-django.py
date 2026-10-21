# -*- mode: python ; coding: utf-8 -*-
"""
本地覆盖 PyInstaller 内置 hook-django.py。

上游 PyInstaller 6.22 的 django hook 在分析阶段调用
get_module_file_attribute('django') 返回 None 并抛 TypeError
（Django 4.2 兼容问题），导致编译中断。

Spug 单机版不依赖 django.contrib 与管理站，这里改为全量收集
django 包的子模块，覆盖所有按字符串动态导入的模块
（management commands、db backends 等），其余交给内置子 hook。
"""
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules('django')

# Django 自带的 locale 数据（错误信息翻译等），体积很小，一并带上
datas = collect_data_files('django', includes=['**/locale/**/*'], include_py_files=False)

binaries = []
