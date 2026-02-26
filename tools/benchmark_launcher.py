"""
Benchmark 啟動器 — 輕量 HTTP server + SSE 即時輸出
用法: uv run python tools/benchmark_launcher.py
瀏覽器開 http://localhost:8088
"""
import json
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 8088
PROJECT_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = Path(__file__).resolve().parent / "benchmark_launcher.html"
CONFIG_PATH = PROJECT_ROOT / "benchmarks" / "config.yaml"


def load_models_from_config() -> dict:
    """讀 config.yaml，回傳 {type: [{id, name}, ...]}"""
    import yaml
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    result = {}
    for btype in ["asr", "tts", "llm", "e2e"]:
        if btype in config and "models" in config[btype]:
            result[btype] = [{"id": m["id"], "name": m["name"]} for m in config[btype]["models"]]
    return result


class BenchmarkHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._serve_html()
        elif parsed.path == "/api/models":
            self._serve_models()
        elif parsed.path == "/api/run":
            self._serve_sse(parsed.query)
        else:
            self.send_error(404)

    def _serve_html(self):
        content = HTML_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def _serve_models(self):
        data = json.dumps(load_models_from_config(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sse(self, query_string: str):
        """SSE 端點：spawn benchmark subprocess，逐行串流 stdout"""
        params = parse_qs(query_string)
        btype = params.get("type", ["llm"])[0]
        model = params.get("model", [None])[0]
        fast = params.get("fast", ["0"])[0] == "1"
        workers = params.get("workers", [None])[0]

        cmd = [sys.executable, "-u", "benchmarks/run_benchmark.py", "--type", btype]
        if model:
            cmd += ["--model", model]
        if fast:
            cmd += ["--fast"]
        if workers:
            cmd += ["--workers", workers]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def _send_event(data: str, event: str = "log"):
            try:
                self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
                env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
                bufsize=1,
            )

            for raw_line in iter(proc.stdout.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                _send_event(line)

            proc.wait()
            _send_event(f"結束（exit code: {proc.returncode}）", event="done")
        except Exception as e:
            _send_event(f"錯誤: {e}", event="error")

    def log_message(self, format, *args):
        """安靜一點，只印重要的"""
        if "/api/run" in str(args[0]):
            super().log_message(format, *args)


def _print(msg: str):
    """Windows cp950 安全 print"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", errors="replace").decode("utf-8"))


def main():
    server = HTTPServer(("0.0.0.0", PORT), BenchmarkHandler)
    _print(f"Benchmark Launcher: http://localhost:{PORT}")
    _print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
