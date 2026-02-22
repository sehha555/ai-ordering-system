# 一鍵啟動 AI 點餐系統（後端 + 前端）
# 用法：.\start.ps1

$Root = $PSScriptRoot

Write-Host "啟動後端 (FastAPI :8000)..."
$backend = Start-Process -NoNewWindow -PassThru -FilePath "uvicorn" -ArgumentList "src.api.app:app","--reload" -WorkingDirectory $Root

Write-Host "啟動前端 (Next.js :3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "npm" -ArgumentList "run","dev" -WorkingDirectory "$Root\src\frontend_next"

Write-Host ""
Write-Host "後端: http://localhost:8000 (PID: $($backend.Id))"
Write-Host "前端: http://localhost:3000 (PID: $($frontend.Id))"
Write-Host ""
Write-Host "按 Ctrl+C 停止所有服務"

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
