#!/bin/bash
# ============================================================
# Spug 单机免 Redis 版 一键构建脚本（幂等，可重复执行）
# 前置要求：git / python3.10+ / node18+ / npm，已联网
# 产物：spug_api/dist/spug/（onedir 目录式可执行包）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[1/3] 后端依赖..."
if [ ! -d spug_api/venv ]; then
    python3 -m venv spug_api/venv
fi
spug_api/venv/bin/pip install -q --upgrade pip
spug_api/venv/bin/pip install -q -r spug_api/requirements-standalone.txt pyinstaller

echo "[2/3] 前端构建..."
cd spug_web
if [ ! -d node_modules ]; then
    npm install --no-audit --no-fund
fi
NODE_OPTIONS='--openssl-legacy-provider' GENERATE_SOURCEMAP=false npm run build
cd "$ROOT"

echo "[3/3] PyInstaller 打包（onedir）..."
cd spug_api
rm -rf build dist
./venv/bin/pyinstaller spug-standalone.spec --noconfirm
cd "$ROOT"

echo "构建完成 → spug_api/dist/spug/"
echo "部署：把 dist/spug/ 整个目录拷到目标机器，执行 ./spug init && ./spug start"
#（注：内容由AI生成）
