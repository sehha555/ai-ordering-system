"""
用 Edge TTS 生成 ASR 測試音檔
用法: python benchmarks/test_data/asr/generate_test_audio.py
"""
import asyncio
import json
from pathlib import Path

import edge_tts

# ASR 測試案例：模擬顧客說的話
TEST_CASES = [
    {"id": "order_riceball_01", "ground_truth": "我要一個鮪魚飯糰", "category": "基本點餐"},
    {"id": "order_riceball_02", "ground_truth": "給我一個玉米飯糰", "category": "基本點餐"},
    {"id": "order_egg_pancake_01", "ground_truth": "一個起司蛋餅", "category": "基本點餐"},
    {"id": "order_combo_01", "ground_truth": "一個起司蛋餅加一杯大冰紅茶", "category": "複合點餐"},
    {"id": "order_combo_02", "ground_truth": "我要一個鮪魚飯糰還有一份薯餅", "category": "複合點餐"},
    {"id": "order_drink_01", "ground_truth": "一杯大冰紅茶", "category": "基本點餐"},
    {"id": "order_drink_02", "ground_truth": "兩杯溫豆漿", "category": "數量"},
    {"id": "modify_01", "ground_truth": "飯糰換成玉米口味", "category": "修改"},
    {"id": "modify_02", "ground_truth": "紅茶改兩杯", "category": "修改"},
    {"id": "query_01", "ground_truth": "你們有賣什麼飲料", "category": "查詢"},
    {"id": "query_02", "ground_truth": "有什麼套餐可以選", "category": "查詢"},
    {"id": "checkout_01", "ground_truth": "好就這樣幫我結帳", "category": "結帳"},
    {"id": "checkout_02", "ground_truth": "沒有了可以結帳了", "category": "結帳"},
    {"id": "greeting_01", "ground_truth": "你好我想點餐", "category": "招呼"},
    {"id": "cancel_01", "ground_truth": "蛋餅不要了幫我取消", "category": "取消"},
]

# 用不同語音模擬不同顧客
VOICES = [
    "zh-TW-HsiaoChenNeural",  # 台灣女聲
    "zh-TW-YunJheNeural",     # 台灣男聲
]


async def generate_audio(case: dict, voice: str, output_dir: Path):
    """生成單一測試音檔"""
    suffix = "f" if "HsiaoChen" in voice else "m"
    filename = f"{case['id']}_{suffix}.mp3"
    filepath = output_dir / filename

    tts = edge_tts.Communicate(case["ground_truth"], voice, rate="+0%")
    await tts.save(str(filepath))
    return filename


async def main():
    output_dir = Path(__file__).parent
    manifest = []

    print(f"開始生成 ASR 測試音檔...")
    print(f"   {len(TEST_CASES)} 個案例 x {len(VOICES)} 個語音 = {len(TEST_CASES) * len(VOICES)} 個音檔\n")

    for case in TEST_CASES:
        for voice in VOICES:
            filename = await generate_audio(case, voice, output_dir)
            suffix = "f" if "HsiaoChen" in voice else "m"
            manifest.append({
                "id": f"{case['id']}_{suffix}",
                "audio_path": f"benchmarks/test_data/asr/{filename}",
                "ground_truth": case["ground_truth"],
                "category": case["category"],
                "voice": voice,
            })
            print(f"  OK: {filename}")

    # 寫入 manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nmanifest.json 已生成（{len(manifest)} 筆）")
    print(f"路徑: {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
