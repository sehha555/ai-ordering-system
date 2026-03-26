"""
壓力測試：模擬 N 個並發點餐機
用法：
  python -m tests.load.stress_test --concurrency 5 --rounds 3 --mode text
  python -m tests.load.stress_test --concurrency 2 --rounds 1 --mode voice --voice-fixture tests/fixtures/sample.webm
  python -m tests.load.stress_test --concurrency 10 --rounds 3 --mode text --base-url http://localhost:8000 --output results.json
"""

import argparse
import asyncio
import pathlib
import time
import uuid

import httpx

from tests.load.report import RequestResult, generate_report, save_json
from tests.load.scenarios import get_text_scenario


async def _parse_sse_events(response: httpx.Response) -> tuple[list[str], float | None]:
    """解析 SSE 串流，回傳 (events, ttfa_s)。

    TTFA（Time To First Audio/Text）：收到第一個 audio_chunk、text_chunk 或 reply event 的時間。
    """
    events: list[str] = []
    ttfa: float | None = None
    start = time.perf_counter()
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            events.append(event_name)
            # 第一個有意義的輸出事件才算 TTFA
            if ttfa is None and event_name in ("audio_chunk", "text_chunk", "reply"):
                ttfa = time.perf_counter() - start
    return events, ttfa


async def text_chat_client(
    client: httpx.AsyncClient,
    client_id: int,
    messages: list[str],
    results: list[RequestResult],
    base_url: str,
) -> None:
    """模擬一個 text-chat 點餐機，依序送出 messages。"""
    session_id = f"load-{client_id:03d}-{uuid.uuid4().hex[:8]}"
    for round_idx, msg in enumerate(messages):
        start = time.perf_counter()
        try:
            async with client.stream(
                "POST",
                f"{base_url}/api/text-chat",
                json={"text": msg, "session_id": session_id},
            ) as resp:
                events, ttfa = await _parse_sse_events(resp)
                total = time.perf_counter() - start
                results.append(
                    RequestResult(
                        client_id=client_id,
                        round_idx=round_idx,
                        message=msg,
                        status_code=resp.status_code,
                        total_s=round(total, 3),
                        ttfa_s=round(ttfa, 3) if ttfa is not None else None,
                        events=events,
                    )
                )
        except Exception as e:  # noqa: BLE001
            total = time.perf_counter() - start
            results.append(
                RequestResult(
                    client_id=client_id,
                    round_idx=round_idx,
                    message=msg,
                    status_code=0,
                    total_s=round(total, 3),
                    error=str(e),
                )
            )


async def voice_chat_client(
    client: httpx.AsyncClient,
    client_id: int,
    rounds: int,
    results: list[RequestResult],
    base_url: str,
    fixture_path: str,
) -> None:
    """模擬 voice-chat 點餐機，重複送出預錄音檔。"""
    audio_bytes = pathlib.Path(fixture_path).read_bytes()
    session_id = f"load-voice-{client_id:03d}-{uuid.uuid4().hex[:8]}"

    for round_idx in range(rounds):
        start = time.perf_counter()
        try:
            async with client.stream(
                "POST",
                f"{base_url}/api/voice-chat",
                files={"file": ("test.webm", audio_bytes, "audio/webm")},
                data={"session_id": session_id},
            ) as resp:
                events, ttfa = await _parse_sse_events(resp)
                total = time.perf_counter() - start
                results.append(
                    RequestResult(
                        client_id=client_id,
                        round_idx=round_idx,
                        message="[voice]",
                        status_code=resp.status_code,
                        total_s=round(total, 3),
                        ttfa_s=round(ttfa, 3) if ttfa is not None else None,
                        events=events,
                    )
                )
        except Exception as e:  # noqa: BLE001
            total = time.perf_counter() - start
            results.append(
                RequestResult(
                    client_id=client_id,
                    round_idx=round_idx,
                    message="[voice]",
                    status_code=0,
                    total_s=round(total, 3),
                    error=str(e),
                )
            )


async def run_load_test(
    concurrency: int,
    rounds: int,
    mode: str,
    base_url: str,
    voice_fixture: str | None = None,
) -> list[RequestResult]:
    """啟動 concurrency 個並發 client，收集全部結果後回傳。"""
    results: list[RequestResult] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        tasks = []
        for i in range(concurrency):
            if mode == "text":
                scenario = get_text_scenario(i)
                # 依 rounds 截切或重複場景
                messages = (scenario * ((rounds // len(scenario)) + 1))[:rounds]
                tasks.append(text_chat_client(client, i, messages, results, base_url))
            else:  # voice
                if not voice_fixture:
                    raise ValueError("voice 模式需要 --voice-fixture 參數")
                tasks.append(voice_chat_client(client, i, rounds, results, base_url, voice_fixture))

        print(f"啟動壓力測試：{concurrency} 並發 × {rounds} 輪 ({mode})")
        print(f"目標：{base_url}")
        test_start = time.perf_counter()
        await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - test_start
        print(f"測試完成，耗時 {elapsed:.1f}s")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 點餐系統壓力測試")
    parser.add_argument("--concurrency", "-c", type=int, default=5, help="並發數")
    parser.add_argument("--rounds", "-r", type=int, default=3, help="每個 client 對話輪數")
    parser.add_argument("--mode", "-m", choices=["text", "voice"], default="text", help="測試模式")
    parser.add_argument("--base-url", default="http://localhost:8000", help="後端 URL")
    parser.add_argument("--voice-fixture", help="voice 模式的音檔路徑 (.webm)")
    parser.add_argument("--output", "-o", help="結果 JSON 輸出路徑")
    args = parser.parse_args()

    results = asyncio.run(
        run_load_test(
            concurrency=args.concurrency,
            rounds=args.rounds,
            mode=args.mode,
            base_url=args.base_url,
            voice_fixture=args.voice_fixture,
        )
    )

    report = generate_report(results, args.concurrency, args.mode)
    print()
    print(report)

    if args.output:
        save_json(results, args.output)
        print(f"\n原始結果已儲存至 {args.output}")


if __name__ == "__main__":
    main()
