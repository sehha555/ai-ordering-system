# Start AI Ordering System (LLM + ASR backend + frontend + OmniVoice TTS)
# Usage: .\start.ps1

$Root = $PSScriptRoot
$ModelPath = "$env:USERPROFILE\.lmstudio\models\unsloth\Qwen3.5-9B-GGUF\Qwen3.5-9B-UD-Q4_K_XL.gguf"

Write-Host "Starting llama-server (:1234)..."
$llm = Start-Process -NoNewWindow -PassThru -FilePath "$Root\tools\llama-server\llama-server.exe" -ArgumentList `
    "--model",$ModelPath, `
    "--host","127.0.0.1","--port","1234", `
    "--ctx-size","16384","--gpu-layers","999", `
    "--flash-attn","auto", `
    "--cache-type-k","q4_0","--cache-type-v","q4_0", `
    "--parallel","1", `
    "--jinja","--chat-template-kwargs","{`"enable_thinking`":false}" `
    -WorkingDirectory "$Root\tools\llama-server"

Write-Host "Starting OmniVoice TTS (:8100)..."
$omnivoice = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList "src/services/omnivoice_server.py" -WorkingDirectory $Root

Write-Host "Starting backend (FastAPI :8000)..."
$backend = Start-Process -NoNewWindow -PassThru -FilePath "uv" -ArgumentList "run","python","-m","uvicorn","src.api.app:app","--host","0.0.0.0","--port","8000" -WorkingDirectory $Root

Write-Host "Starting frontend (Next.js :3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "pnpm" -ArgumentList "dev" -WorkingDirectory "$Root\src\frontend_next"

Write-Host ""
Write-Host "LLM:       http://localhost:1234 (PID: $($llm.Id))"
Write-Host "OmniVoice: http://localhost:8100 (PID: $($omnivoice.Id))"
Write-Host "Backend:   http://localhost:8000 (PID: $($backend.Id))"
Write-Host "Frontend:  http://localhost:3000 (PID: $($frontend.Id))"
Write-Host ""

# 等 Next.js 就緒後開瀏覽器
Write-Host "Waiting for frontend to be ready..."
for ($i = 0; $i -lt 30; $i++) {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 2 -ErrorAction Stop
        Start-Process "http://localhost:3000"
        Write-Host "Browser opened."
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

Write-Host "Press Ctrl+C to stop all services"

try {
    Wait-Process -Id $llm.Id, $backend.Id, $frontend.Id, $omnivoice.Id
} finally {
    Stop-Process -Id $llm.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $omnivoice.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
