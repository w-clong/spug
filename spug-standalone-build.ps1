# ============================================================
# Spug 单机免 Redis 版 一键构建脚本（Windows / PowerShell）
# 产物：spug_api\dist\spug\（onedir 目录式可执行包，含 spug.exe）
#
# 前置要求：Python 3.10+（推荐 3.12）、Node.js 18+、已联网
# 用法：powershell -ExecutionPolicy Bypass -File .\spug-standalone-build.ps1
#
# 运行产物：
#   双击 spug.exe        桌面模式：自动建库(admin/admin) + 打开浏览器 + 托盘常驻
#   spug.exe init        仅初始化数据库并创建管理员（重复执行安全）
#   spug.exe start       无界面模式：只启动服务，默认 http://0.0.0.0:9000
# ============================================================
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv-win'
$py = Join-Path $venv 'Scripts\python.exe'

Set-Location $root

Write-Host '[1/3] 后端依赖 ...'
if (-not (Test-Path $py)) {
    $base = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $base) { throw '未找到 python，请先安装 Python 3.10+ 并加入 PATH' }
    & $base.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败（Python 3.10+ 必需）' }
}
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r (Join-Path $root 'spug_api\requirements-standalone.txt') pyinstaller
if ($LASTEXITCODE -ne 0) { throw '后端依赖安装失败' }

Write-Host '[2/3] 前端构建 ...'
if (Test-Path (Join-Path $root 'spug_web\build\index.html')) {
    Write-Host '      已存在 spug_web\build，跳过（如需重建请先删除该目录）'
} else {
    Push-Location (Join-Path $root 'spug_web')
    try {
        if (-not (Test-Path 'node_modules')) {
            npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm install 失败' }
        }
        # package.json 里的 build 脚本使用 POSIX 环境变量写法，Windows 下改为直接调用
        $env:NODE_OPTIONS = '--openssl-legacy-provider'
        $env:GENERATE_SOURCEMAP = 'false'
        npx react-app-rewired build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
    } finally {
        Pop-Location
    }
}

Write-Host '[3/3] PyInstaller 打包（onedir）...'
Push-Location (Join-Path $root 'spug_api')
try {
    Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
    & (Join-Path $venv 'Scripts\pyinstaller.exe') spug-standalone.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 打包失败' }
} finally {
    Pop-Location
}

$out = Join-Path $root 'spug_api\dist\spug'
$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ('构建完成 -> {0}（{1:N1} MB）' -f $out, $size)
Write-Host '部署：把整个 spug 目录拷到目标机器，执行 spug.exe init 后 spug.exe start'
