# 打包步骤：先打 Python 后端，再打 Electron 安装包
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[1/3] 安装后端打包依赖"
uv pip install --python ".\.venv\Scripts\python.exe" pyinstaller

Write-Host "[2/3] 打包 Python 后端 -> dist\backend"
& ".\.venv\Scripts\pyinstaller.exe" "build\backend.spec" --noconfirm --distpath "dist" --workpath "build\work"

Write-Host "[3/3] 打包 Electron 安装包 -> dist\fav2note Setup.exe"
Set-Location "desktop"
if (-not (Test-Path "node_modules")) { npm install }
npm run dist

Write-Host "完成：dist 目录"
