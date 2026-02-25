# Start AI Ordering System (backend + frontend)
# Usage: .\start.ps1

$Root = $PSScriptRoot

Write-Host "Starting backend (FastAPI :8000)..."
$backend = Start-Process -NoNewWindow -PassThru -FilePath "uv" -ArgumentList "run","uvicorn","src.api.app:app","--reload","--reload-dir","src" -WorkingDirectory $Root

Write-Host "Starting frontend (Next.js :3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "cmd" -ArgumentList "/c","npm run dev" -WorkingDirectory "$Root\src\frontend_next"

Write-Host ""
Write-Host "Backend: http://localhost:8000 (PID: $($backend.Id))"
Write-Host "Frontend: http://localhost:3000 (PID: $($frontend.Id))"
Write-Host ""
Write-Host "Press Ctrl+C to stop all services"

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
