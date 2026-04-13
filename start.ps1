# Start AI Ordering System
# 啟動順序：Backend(ASR) → LLM → OmniVoice → Frontend
# ASR 必須先載入 GPU，否則 VRAM 被 LLM 佔滿會載入失敗
# Usage: .\start.ps1

$Root = $PSScriptRoot
$ModelPath = "$env:USERPROFILE\.lmstudio\models\unsloth\Qwen3.5-9B-GGUF\Qwen3.5-9B-UD-Q4_K_XL.gguf"
# llama-server 透過環境變數讀 JSON，繞過 PowerShell 原生 exe argument 雙引號脫落 bug
$env:LLAMA_CHAT_TEMPLATE_KWARGS = '{"enable_thinking":false}'

# 1. Backend 先啟（ASR 載入 GPU ~3.5GB，需 30-40 秒）
Write-Host "Starting backend (FastAPI :8000) — ASR loading to GPU..."
$backend = Start-Process -NoNewWindow -PassThru -FilePath "uv" -ArgumentList "run","python","-m","uvicorn","src.api.app:app","--host","0.0.0.0","--port","8000" -WorkingDirectory $Root

# 等 ASR 載入完成
Write-Host "Waiting for ASR model to load..."
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8000/readyz" -TimeoutSec 3 -ErrorAction Stop
        if ($resp.checks.asr -eq "ok") {
            Write-Host "ASR loaded."
            break
        }
    } catch {}
    Start-Sleep -Seconds 1
}

# 2. LLM（llama-server ~8GB VRAM）
Write-Host "Starting llama-server (:1234)..."
$llm = Start-Process -NoNewWindow -PassThru -FilePath "$Root\tools\llama-server\llama-server.exe" -ArgumentList `
    "--model",$ModelPath, `
    "--host","127.0.0.1","--port","1234", `
    "--ctx-size","16384","--gpu-layers","999", `
    "--flash-attn","auto", `
    "--cache-type-k","q4_0","--cache-type-v","q4_0", `
    "--parallel","1", `
    "--jinja" `
    -WorkingDirectory "$Root\tools\llama-server"

# 3. OmniVoice TTS（~1.9GB VRAM）
Write-Host "Starting OmniVoice TTS (:8100)..."
$omnivoice = Start-Process -NoNewWindow -PassThru -FilePath "python" -ArgumentList "src/services/omnivoice_server.py" -WorkingDirectory $Root

# 4. Frontend
Write-Host "Starting frontend (Next.js :3000)..."
$frontend = Start-Process -NoNewWindow -PassThru -FilePath "cmd.exe" -ArgumentList "/c","pnpm","dev" -WorkingDirectory "$Root\src\frontend_next"

Write-Host ""
Write-Host "Backend:   http://localhost:8000 (PID: $($backend.Id))"
Write-Host "LLM:       http://localhost:1234 (PID: $($llm.Id))"
Write-Host "OmniVoice: http://localhost:8100 (PID: $($omnivoice.Id))"
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
    Wait-Process -Id $backend.Id, $llm.Id, $frontend.Id, $omnivoice.Id
} finally {
    Stop-Process -Id $llm.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $omnivoice.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $frontend.Id -ErrorAction SilentlyContinue
}
