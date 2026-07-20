"""VoxCPM TTS 微服務 — 獨立 process（q3tts venv，python 3.12）。

啟動方式：
    C:/Users/User/.venvs/q3tts/Scripts/python.exe src/services/voxcpm_server.py --ref-audio ref_taiwan_voxcpm.wav

預設監聽 http://127.0.0.1:8200/synthesize_stream
串流協議：chunked response，內容為連續的 [4-byte big-endian 長度][獨立可播放 MP3 段]。
首段約 1 秒音訊（快出聲），其後每段約 2 秒（少接縫）— 播放端的小緩衝。
"""

import argparse
import json
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

import lameenc
import numpy as np
import soundfile as sf
import torch
import torchaudio


# torchcodec 在 Windows 缺 ffmpeg shared DLL，改用 soundfile 讀 wav 繞過
def _sf_load(path, **kw):
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr


torchaudio.load = _sf_load

from voxcpm import VoxCPM  # patch 必須先於 voxcpm import（E402 已全域 ignore）

# 自適應段長策略：首段小緩衝快出聲；之後以「已下發未播完的餘裕（runway）」決定切點 —
# 餘裕低就儘快切段續氣、餘裕多就拉長段減少 MP3 接縫（實測 RTF 0.78-0.87 會浮動，
# 固定比例的段長無法保證不斷氣）
FIRST_SEGMENT_SEC = 1.0  # 首段緩衝，決定 TTFA
MIN_SEGMENT_SEC = 0.6  # 段太小接縫過密，至少累積到這麼多才切
MAX_SEGMENT_SEC = 3.0  # 餘裕充足時的段長上限
MIN_RUNWAY_SEC = 0.3  # 餘裕低於此值就切段續氣

_model = None
_sample_rate = 16000
_ref_audio = ""
_ref_text = ""
_inference_lock = threading.Lock()


def load_model(model_id: str, ref_audio: str, ref_text: str):
    global _model, _sample_rate, _ref_audio, _ref_text
    _ref_audio = ref_audio
    _ref_text = ref_text

    print(f"[VoxCPM] 載入模型 {model_id}...")
    t0 = time.time()
    # denoiser 只在 generate(denoise=True) 時使用，本服務不用 → 不載，省 VRAM
    _model = VoxCPM.from_pretrained(model_id, load_denoiser=False)
    _sample_rate = _model.tts_model.sample_rate
    print(f"[VoxCPM] 已載入（{time.time() - t0:.1f}s, SR={_sample_rate}, clone: {ref_audio}）")

    # 暖機：首次 generate 觸發 torch.compile，先跑掉避免第一個請求吃冷啟動
    t0 = time.time()
    for _ in _model.generate_streaming(
        text="好的", prompt_wav_path=_ref_audio, prompt_text=_ref_text
    ):
        pass
    print(f"[VoxCPM] 暖機完成（{time.time() - t0:.1f}s）")

    vram_mb = torch.cuda.memory_allocated() / 1024 / 1024
    print(f"[VoxCPM] VRAM: {vram_mb:.0f} MB")


def _encode_mp3(pcm: np.ndarray) -> bytes:
    """float32 PCM → 獨立可播放的 MP3 段"""
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(96)
    encoder.set_in_sample_rate(_sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    pcm_int16 = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
    return bytes(encoder.encode(pcm_int16.tobytes())) + bytes(encoder.flush())


def iter_mp3_segments(text: str):
    """合成並依段長策略切段，yield 獨立 MP3 段（threading lock 保護 GPU 推理）"""
    with _inference_lock:
        buf: list[np.ndarray] = []
        buffered = 0
        first_flush_at = None  # 首段下發時刻 ≈ 播放起點（localhost 傳輸延遲可忽略）
        delivered_sec = 0.0
        for chunk in _model.generate_streaming(
            text=text, prompt_wav_path=_ref_audio, prompt_text=_ref_text
        ):
            buf.append(chunk)
            buffered += len(chunk)
            buffered_sec = buffered / _sample_rate
            if first_flush_at is None:
                should_flush = buffered_sec >= FIRST_SEGMENT_SEC
            else:
                runway = first_flush_at + delivered_sec - time.monotonic()
                should_flush = buffered_sec >= MAX_SEGMENT_SEC or (
                    runway <= MIN_RUNWAY_SEC and buffered_sec >= MIN_SEGMENT_SEC
                )
            if should_flush:
                yield _encode_mp3(np.concatenate(buf))
                if first_flush_at is None:
                    first_flush_at = time.monotonic()
                delivered_sec += buffered_sec
                buf, buffered = [], 0
        if buf:
            yield _encode_mp3(np.concatenate(buf))


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # chunked transfer 必須 HTTP/1.1

    def do_GET(self):
        if self.path == "/health":
            status = 200 if _model is not None else 503
            body = json.dumps({"ok": _model is not None, "voice": "clone"}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/synthesize_stream":
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
        first = None
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for seg in iter_mp3_segments(text):
                if first is None:
                    first = time.time() - t0
                framed = struct.pack(">I", len(seg)) + seg
                self.wfile.write(f"{len(framed):X}\r\n".encode() + framed + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            print(f"[VoxCPM] 首段 {first:.2f}s / 全程 {time.time() - t0:.2f}s ({len(text)} 字)")
        except Exception as e:
            # headers 已送出，無法回錯誤碼，只能斷線讓 client 走 fallback
            print(f"[VoxCPM] 合成失敗: {e!r}")
            self.close_connection = True

    def log_message(self, format, *args):
        print(f"[VoxCPM] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="VoxCPM TTS 微服務")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--model", default="openbmb/VoxCPM-0.5B")
    parser.add_argument("--ref-audio", required=True, help="clone 參考音檔（wav）")
    parser.add_argument("--ref-text", default="", help="參考音檔文字稿；留空則讀同名 .txt")
    args = parser.parse_args()

    ref_text = (
        args.ref_text
        or Path(args.ref_audio).with_suffix(".txt").read_text(encoding="utf-8").strip()
    )

    load_model(args.model, args.ref_audio, ref_text)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[VoxCPM] 服務啟動：http://127.0.0.1:{args.port}/synthesize_stream")
    server.serve_forever()


if __name__ == "__main__":
    main()
