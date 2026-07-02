"""OmniVoice TTS 微服務 — 獨立 process，避免 transformers 版本衝突。

啟動方式（用系統 Python，omnivoice 已安裝在那）：
    python src/services/omnivoice_server.py

預設監聽 http://127.0.0.1:8100/synthesize
"""

import io
import time
import argparse

import numpy as np
import torch
from pydub import AudioSegment
from omnivoice import OmniVoice
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn  # noqa: E402
import json


import threading

_model = None
_voice_prompt = None
_instruct = "female, young adult, chinese accent, high pitch"
_inference_lock = threading.Lock()


def load_model(
    model_id: str,
    instruct: str,
    ref_audio: str = "",
    ref_text: str = "",
):
    global _model, _voice_prompt, _instruct
    _instruct = instruct

    print(f"[OmniVoice] 載入模型 {model_id}...")
    _model = OmniVoice.from_pretrained(
        model_id,
        device_map="cuda:0",
        dtype=torch.float16,
    )

    if ref_audio:
        _voice_prompt = _model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
        )
        print(f"[OmniVoice] 已載入（voice clone: {ref_audio}）")
    else:
        print(f"[OmniVoice] 已載入（voice design: {instruct}）")

    vram_mb = torch.cuda.memory_allocated() / 1024 / 1024
    print(f"[OmniVoice] VRAM: {vram_mb:.0f} MB")


def synthesize_mp3(text: str) -> bytes:
    """合成文字 → MP3 bytes（threading lock 保護 GPU 推理）"""
    with _inference_lock:
        return _synthesize_mp3_inner(text)


def _synthesize_mp3_inner(text: str) -> bytes:
    if _voice_prompt:
        audio_list = _model.generate(
            text=text, language="Chinese", voice_clone_prompt=_voice_prompt
        )
    else:
        audio_list = _model.generate(text=text, language="Chinese", instruct=_instruct)

    audio = audio_list[0]
    if hasattr(audio, "cpu"):
        audio = audio.cpu().numpy()
    audio = np.array(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = audio[0]

    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    segment = AudioSegment(
        data=audio_int16.tobytes(),
        sample_width=2,
        frame_rate=24000,
        channels=1,
    )
    buf = io.BytesIO()
    segment.export(buf, format="mp3", bitrate="128k")
    return buf.getvalue()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            status = 200 if _model is not None else 503
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # voice: clone（有 ref_audio）或 instruct（voice design 模式）
            voice_mode = "clone" if _voice_prompt else "instruct"
            self.wfile.write(json.dumps({"ok": _model is not None, "voice": voice_mode}).encode())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/synthesize":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
        text = body.get("text", "")

        if not text or len(text) > 500:
            self.send_error(400, "text missing or too long (max 500 chars)")
            return

        t0 = time.time()
        try:
            mp3 = synthesize_mp3(text)
        except Exception as e:
            self.send_error(500, str(e))
            return
        elapsed = time.time() - t0

        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3)))
        self.send_header("X-Synthesis-Time", f"{elapsed:.3f}")
        self.end_headers()
        self.wfile.write(mp3)

    def log_message(self, format, *args):
        print(f"[OmniVoice] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="OmniVoice TTS 微服務")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument(
        "--instruct",
        default="female, young adult, chinese accent, high pitch",
    )
    parser.add_argument("--ref-audio", default="")
    parser.add_argument("--ref-text", default="")
    args = parser.parse_args()

    load_model(args.model, args.instruct, args.ref_audio, args.ref_text)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[OmniVoice] 服務啟動：http://127.0.0.1:{args.port}/synthesize")
    server.serve_forever()


if __name__ == "__main__":
    main()
