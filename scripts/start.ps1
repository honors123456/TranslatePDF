# 一键启动 TranslationPDF：后端 uvicorn + 前端 next start，并打开浏览器。
# 用法：双击根目录 start.bat，或 powershell -ExecutionPolicy Bypass -File scripts\start.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$backendPython = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $backendPython)) {
    Write-Host "未找到 backend\.venv，请先创建 venv 并安装 backend\requirements.txt" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# 前端没有生产构建产物时先构建一次（首次或代码更新后）
if (-not (Test-Path (Join-Path $root "frontend\.next\BUILD_ID"))) {
    Write-Host "首次运行，构建前端（约 1 分钟）..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "frontend")
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        Read-Host "前端构建失败，按回车退出"
        exit 1
    }
    Pop-Location
}

Write-Host "启动后端 http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process -FilePath $backendPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend")

Write-Host "启动前端 http://localhost:3000 ..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" `
    -ArgumentList "/c", "npm start" `
    -WorkingDirectory (Join-Path $root "frontend")

Start-Sleep -Seconds 4
Start-Process "http://localhost:3000"
Write-Host "已启动。关闭弹出的两个窗口即停止服务。" -ForegroundColor Green
