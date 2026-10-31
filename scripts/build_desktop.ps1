# 打包桌面端：Python 后端 -> Electron 应用 -> 注入图标 -> 安装包
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "[1/5] 安装后端打包依赖"
uv pip install --python ".\.venv\Scripts\python.exe" pyinstaller

Write-Host "[2/5] 打包 Python 后端 -> dist\backend"
& ".\.venv\Scripts\pyinstaller.exe" "build\backend.spec" --noconfirm --distpath "dist" --workpath "build\work"

Write-Host "[3/5] 打包 Electron 应用 -> dist\win-unpacked"
Set-Location "desktop"
if (-not (Test-Path "node_modules")) { npm install }
$env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
# 未开 Windows 开发者模式时符号链接会失败，先跳过签名与图标改写
& npx electron-builder --win nsis

Write-Host "[4/5] 用 rcedit 把图标写进 exe"
$rcedit = Get-ChildItem "$env:LOCALAPPDATA\electron-builder\Cache\winCodeSign" -Recurse -Filter "rcedit-x64.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if ($rcedit) {
    & $rcedit "..\dist\win-unpacked\fav2note.exe" --set-icon "..\assets\icon.ico"
} else {
    Write-Host "未找到 rcedit，跳过图标注入"
}

Write-Host "[5/5] 用打好图标的应用重新封装安装包"
& npx electron-builder --prepackaged ..\dist\win-unpacked --win nsis

Set-Location $Root
Write-Host "完成：dist\fav2note Setup 0.1.0.exe"
