# 源飯糰 - 開發環境啟動腳本
# 用法: .\scripts\dev.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  源飯糰 語音點餐系統 - 開發模式" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 取得專案根目錄
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# 啟動 FastAPI 後端
Write-Host "[1/2] 啟動 FastAPI 後端 (port 8000)..." -ForegroundColor Yellow
$backend = Start-Process -PassThru -NoNewWindow -FilePath "uvicorn" -ArgumentList "src.api.app:app", "--reload", "--port", "8000" -WorkingDirectory $ProjectRoot

Write-Host "  PID: $($backend.Id)" -ForegroundColor Gray
Start-Sleep -Seconds 2

# 啟動 Next.js 前端
Write-Host "[2/2] 啟動 Next.js 前端 (port 3000)..." -ForegroundColor Yellow
$frontend = Start-Process -PassThru -NoNewWindow -FilePath "npm" -ArgumentList "run", "dev" -WorkingDirectory "$ProjectRoot\src\frontend_next"

Write-Host "  PID: $($frontend.Id)" -ForegroundColor Gray
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  後端: http://localhost:8000" -ForegroundColor Green
Write-Host "  前端: http://localhost:3000" -ForegroundColor Green
Write-Host "  API 文件: http://localhost:8000/docs" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "按 Ctrl+C 停止所有服務" -ForegroundColor Gray

# 等待任一行程結束
try {
    $backend | Wait-Process
} finally {
    # 清理
    Write-Host "`n正在停止服務..." -ForegroundColor Yellow
    if (!$backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    if (!$frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "已停止所有服務" -ForegroundColor Green
}
