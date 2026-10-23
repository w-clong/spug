# ============================================================
# Spug 便携版构建脚本（Windows）
# 产物目录：dist\Spug\
#   Spug.exe            启动器（C#，无控制台）
#   spug.ini            监听地址/端口
#   runtime\            官方 embeddable Python + 私有 site-packages
#   app\                Spug 后端源码
#   web\                前端编译产物
#   data\               运行时生成（数据库/日志/repos）
#
# 前置条件：已生成 spug_web\build（可在本脚本前执行前端构建）、
#           .venv-win（Python 3.12）或可用 uv。
# 用法：powershell -ExecutionPolicy Bypass -File .\build-portable.ps1
# ============================================================
param(
    [string]$PythonVersion = '3.12.10',
    [switch]$SkipDeps
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dist = Join-Path $root 'dist\Spug'
$runtime = Join-Path $dist 'runtime'
$app = Join-Path $dist 'app'
$web = Join-Path $dist 'web'
$cacheDir = Join-Path $root '.downloads'
$buildPy = Join-Path $root '.venv-win\Scripts\python.exe'
# uv 默认缓存在用户目录，便携/受限环境下不可写，统一放到工作区
if (-not $env:UV_CACHE_DIR) { $env:UV_CACHE_DIR = Join-Path $root '.uv-cache' }

function Step($msg) { Write-Host "[build] $msg" }

if (-not (Test-Path (Join-Path $root 'spug_web\build\index.html'))) {
    throw '缺少 spug_web\build，请先构建前端（node node_modules\react-app-rewired\scripts\build.js）'
}

Step '准备目录'
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force $dist, $runtime, $cacheDir | Out-Null

Step "下载 embeddable Python $PythonVersion"
$zip = Join-Path $cacheDir "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    if (Test-Path $buildPy) {
        & $buildPy -c "import urllib.request,sys; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" `
            "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" $zip
    } else {
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip
    }
    if ($LASTEXITCODE -ne 0) { throw '下载 Python embeddable 失败' }
}
Expand-Archive -Path $zip -DestinationPath $runtime -Force

Step '配置私有 runtime 搜索路径'
@('python312.zip', '.', 'import site', 'Lib\site-packages', '..\app') |
    Set-Content -Path (Join-Path $runtime 'python312._pth') -Encoding ascii

if (-not $SkipDeps) {
    Step '安装依赖到 runtime\Lib\site-packages'
    $target = Join-Path $runtime 'Lib\site-packages'
    New-Item -ItemType Directory -Force $target | Out-Null
    $req = Join-Path $root 'spug_api\requirements-standalone.txt'
    $uvExe = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (-not (Test-Path $uvExe)) {
        $cmd = Get-Command uv -ErrorAction SilentlyContinue
        if ($cmd) { $uvExe = $cmd.Source }
    }
    if (Test-Path $uvExe) {
        & $uvExe pip install --python $buildPy --target $target -r $req
    } elseif (Test-Path $buildPy) {
        & $buildPy -m pip install --target $target -r $req
    } else {
        throw '未找到 uv 或 .venv-win，无法安装私有 runtime 依赖'
    }
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
}

Step '复制后端与前端产物'
robocopy (Join-Path $root 'spug_api') $app /E /XD venv __pycache__ data /XF selftest_*.py e2e_linux.py debug_*.py /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw '复制 app 失败' }
robocopy (Join-Path $root 'spug_web\build') $web /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw '复制 web 失败' }

Step '精简 runtime（减少小文件数量，提升复制/解压/更新速度）'
$site = Join-Path $runtime 'Lib\site-packages'
# 1) 未使用的 Django contrib（INSTALLED_APPS 里没有任何 django.contrib）
foreach ($name in 'gis', 'admindocs', 'flatpages', 'redirects', 'sites', 'humanize',
                  'postgres', 'admin', 'sitemaps', 'syndication') {
    $p = Join-Path $site "django\contrib\$name"
    if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}
# 2) 测试目录
#    注意：不要删除 *.dist-info —— pyinfra 的 ssh 连接器等插件靠 entry_points 注册，
#    删掉包元数据会导致运行期 KeyError: 'ssh'
foreach ($name in 'tests', 'test') {
    Get-ChildItem $site -Directory -Recurse -Filter $name -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\django\\' } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}
# 3) 与运行无关的目录
foreach ($d in 'Scripts', 'share', 'Include', 'libs') {
    $p = Join-Path $runtime $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}
Get-ChildItem $runtime -Recurse -File -Include '*.pdb', '*.lib', '*.h' -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# 4) 便携包不装 Pillow：只用于托盘图标，启动器已做「无 Pillow 自动跳过托盘」降级，省约 14MB
foreach ($pkg in 'PIL', 'pillow') {
    $p = Join-Path $site $pkg
    if (Test-Path $p) { Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}
Get-ChildItem $site -Directory -Filter 'pillow-*.dist-info' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# 5) Django 只保留 en / zh_Hans 语言包（界面只有中英文），其余翻译文件删掉
$localeDir = Join-Path $site 'django\conf\locale'
if (Test-Path $localeDir) {
    Get-ChildItem $localeDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notin @('en', 'zh_Hans', '__pycache__') } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

Step '写入 spug.ini'
@"
; Spug 启动配置（修改后重启 Spug.exe 生效）
; 优先级：环境变量 SPUG_HOST / SPUG_PORT > 本文件 > 默认值
[server]
host = 0.0.0.0
port = 9000
"@ | Set-Content -Path (Join-Path $dist 'spug.ini') -Encoding UTF8

Step '复制使用说明'
Copy-Item (Join-Path $root 'docs\usage-zh.md') (Join-Path $dist '使用说明.md') -Force

Step '编译 Spug.exe 启动器'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { throw '未找到 csc.exe（.NET Framework 4.x），无法编译启动器' }
$icon = Join-Path $root 'spug_web\public\favicon.ico'
$exe = Join-Path $dist 'Spug.exe'
# 托盘图标改用 Win32 NotifyIcon 实现，需要引用 WinForms / Drawing
& $csc /nologo /target:winexe /platform:x64 "/win32icon:$icon" "/out:$exe" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll (Join-Path $root 'packaging\launcher.cs')
if ($LASTEXITCODE -ne 0) { throw '编译 Spug.exe 失败' }

Step '附带快速更新脚本'
Copy-Item (Join-Path $root 'packaging\update.ps1') (Join-Path $dist '更新程序.ps1') -Force

$size = (Get-ChildItem $dist -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
$count = (Get-ChildItem $dist -Recurse -File | Measure-Object).Count
Write-Host ('构建完成 -> {0}（{1:N1} MB，{2} 个文件）' -f $dist, $size, $count)
Write-Host '分发：整个 dist\Spug 目录拷贝到目标机，双击 Spug.exe（首次自动建库 admin/admin）'
Write-Host '更新：只替换 app/web 时用 更新程序.ps1（保留 data 与 runtime，秒级完成）'
