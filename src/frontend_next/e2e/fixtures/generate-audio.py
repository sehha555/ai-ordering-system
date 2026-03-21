"""
測試語音生成腳本
使用 Edge TTS 生成 E2E 測試用的音訊 fixture 檔案。

用法：
  uv run python src/frontend_next/e2e/fixtures/generate-audio.py

注意：
  - 品項名稱（TODO）需在拿到菜單後更新
  - 生成的 MP3 儲存於 src/frontend_next/e2e/fixtures/audio/
"""

import asyncio
from pathlib import Path

try:
    import edge_tts
except ImportError:
    raise SystemExit("請先安裝 edge-tts：uv pip install edge-tts")

VOICE = "zh-TW-HsiaoChenNeural"
OUTPUT_DIR = Path(__file__).parent / "audio"

# TODO: 拿到菜單後替換 {{品項名稱}} 為實際品項
PHRASES: dict[str, str] = {
    # ── 單品點餐 ──
    "single_item": "我要一個{{品項1}}",  # TODO: 替換
    # ── 多品點餐 ──
    "multi_item": "我要一個{{品項1}}跟一杯{{飲料1}}",  # TODO: 替換
    # ── 加單 ──
    "add_more": "再加一個",
    # ── 移除品項 ──
    "remove_item": "不要那個了",
    # ── 結帳 ──
    "checkout": "幫我結帳",
    # ── 內用 / 外帶 ──
    "dine_in": "內用",
    "take_out": "外帶",
    # ── 付款方式 ──
    "cash_payment": "付現金",
    # ── 詢問飲料 ──
    "inquiry_drinks": "有什麼飲料",
    # ── 售完品項（TODO: 換成實際售完品項） ──
    "out_of_stock": "我要一個{{售完品項}}",  # TODO: 替換
}


async def generate_all() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for name, text in PHRASES.items():
        out_path = OUTPUT_DIR / f"{name}.mp3"
        if out_path.exists():
            print(f"  skip  {name}.mp3（已存在）")
            continue
        tasks.append(_generate_one(name, text, out_path))

    if not tasks:
        print("所有音訊已存在，無需重新生成。")
        return

    await asyncio.gather(*tasks)
    print(f"\n完成！共生成 {len(tasks)} 個音訊檔案 → {OUTPUT_DIR}")


async def _generate_one(name: str, text: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(out_path))
    print(f"  ok    {name}.mp3  「{text}」")


if __name__ == "__main__":
    asyncio.run(generate_all())
