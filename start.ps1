# Start AI Ordering System (backend + frontend + OmniVoice TTS)
# Usage: .\start.ps1

$Root = $PSScriptRoot

Write-Host "Starting OmniVoice TTS (:8100)..."
$omnivoice = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList "src/services/omnivoice_server.py","--ref-audio","ref_voice.wav" -WorkingDirectory $Root

Write-Host "Starting backend (FastAPI :8000)..."
$backend = Start-Process -NoNewWindow -PassThru -FilePath "uv" -ArgumentList "run","python","-m","uvicorn","src.api.app:app","--host","0.0.0.0","--port","8000" -WorkingDirectory $Root

Write-Host "Starting frontend (Next.js :3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "pnpm" -ArgumentList "dev" -WorkingDirectory "$Root\src\frontend_next"

Write-Host ""
Write-Host "OmniVoice: http://localhost:8100 (PID: $($omnivoice.Id))"
Write-Host "Backend:   http://localhost:8000 (PID: $($backend.Id))"
Write-Host "Frontend:  http://localhost:3000 (PID: $($frontend.Id))"
Write-Host ""
Write-Host "Press Ctrl+C to stop all services"

try {
    Wait-Process -Id $backend.Id, $frontend.Id, $omnivoice.Id
} finally {
    Stop-Process -Id $omnivoice.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
