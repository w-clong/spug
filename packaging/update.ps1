param(
    [Parameter(Mandatory = $true)][string]$Zip,
    [string]$Target = ''
)

# Spug 便携版快速更新：只替换 app 与 web，保留 data（数据库）与 runtime（Python 运行时）。
# 相比整包解压覆盖 1.3 万个文件，这里通常只有 1 千多个文件，秒级完成。

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $Zip)) { throw "找不到更新包：$Zip" }
$Zip = (Resolve-Path $Zip).Path
if (-not $Target) { $Target = $PSScriptRoot }
if (-not (Test-Path $Target)) { throw "找不到安装目录：$Target" }

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("spug-update-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $temp | Out-Null

try {
    Write-Host "[update] 解压更新包 ..."
    Expand-Archive -Path $Zip -DestinationPath $temp -Force

    $newApp = Join-Path $temp 'app'
    $newWeb = Join-Path $temp 'web'
    if (-not (Test-Path $newApp) -or -not (Test-Path $newWeb)) {
        throw '更新包结构不正确（缺少 app / web 目录），请使用完整的 spug-win-x64.zip'
    }

    # 正在运行的话先停掉，避免文件占用
    Get-Process Spug, pythonw, python -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($Target, 'OrdinalIgnoreCase') } |
        ForEach-Object {
            Write-Host "[update] 停止进程 $($_.ProcessName) ($($_.Id))"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 1

    Write-Host "[update] 同步 app ..."
    robocopy $newApp (Join-Path $Target 'app') /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw '更新 app 失败' }

    Write-Host "[update] 同步 web ..."
    robocopy $newWeb (Join-Path $Target 'web') /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw '更新 web 失败' }

    $doc = Join-Path $temp '使用说明.md'
    if (Test-Path $doc) { Copy-Item $doc (Join-Path $Target '使用说明.md') -Force }

    Write-Host "[update] 完成。data 与 runtime 未改动，直接启动 Spug.exe 即可。"
}
finally {
    Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
}
