"""ASR 輸出後處理：簡轉繁 + 領域詞彙修正 + 無意義文本過濾"""

import re
import opencc
from src.config.config_loader import load_json_config

_converter = opencc.OpenCC("s2twp")  # 簡體→繁體（台灣用語偏好）
_PUNCTUATION_RE = re.compile(r"[，。？！、；：「」,.?!\s]")

# 語氣詞黑名單：單獨出現時無意義，不應觸發 LLM 呼叫（單字元，用 character class 一次比對）
_FILLER_RE = re.compile(r"[嗯啊呃喔哦欸唉嘿哈呀噯誒吖嘎嗚啦]")

# 領域詞彙修正表：從 asr_corrections.json 載入
_asr_cfg = load_json_config("asr_corrections.json")
_CORRECTIONS = _asr_cfg["corrections"]


def postprocess(text: str) -> str:
    """ASR 輸出後處理：簡轉繁 + 詞彙修正 + 無意義文本過濾"""
    # Step 1: opencc 簡轉繁
    text = _converter.convert(text)
    # Step 2: 領域詞彙修正（opencc 轉完可能仍有錯）
    for wrong, correct in _CORRECTIONS.items():
        if wrong in text:
            text = text.replace(wrong, correct)
    text = text.strip()
    # Step 2.5: 語氣詞過濾（只用於判斷，不修改原始文本）
    content_check = _FILLER_RE.sub("", text)
    # Step 3: 過濾無意義結果（純標點、單字、純語氣詞）
    content_check = _PUNCTUATION_RE.sub("", content_check)
    if len(content_check) < 2:
        return ""
    return text
