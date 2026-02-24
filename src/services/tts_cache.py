# src/services/tts_cache.py
"""TTS 預快取層 — 啟動時對高頻固定回覆預生成音檔，命中時 TTFA ≈ 0"""
from typing import AsyncIterator, Dict, Optional

from loguru import logger

# 高頻固定回覆清單（店員常說的短句）
HIGH_FREQ_PHRASES = [
    "好 還要嗎",
    "好的 還需要什麼嗎",
    "內用還是外帶",
    "現金還是行動支付",
    "飲料要冰的溫的",
    "紫米白米還是混米",
    "蛋餅什麼口味",
    "要加辣菜脯嗎",
    "好",
    "好的",
    "沒有這個",
    "購物車沒有東西喔",
    "還需要什麼嗎",
    "中杯還是大杯",
    "什麼口味",
    "飲料溫度呢",
    "抱歉 沒聽清楚 再說一次",
    "吐司漢堡還是饅頭",
]


class TTSCache:
    """TTS 音訊預快取：啟動時預生成，查詢時直接返回 bytes"""

    def __init__(self):
        self._cache: Dict[str, bytes] = {}

    async def warmup(self, tts_service) -> None:
        """啟動時預生成高頻回覆的 TTS 音檔"""
        logger.info("[TTS-Cache] 開始預熱 {} 條高頻回覆...", len(HIGH_FREQ_PHRASES))
        success = 0
        for phrase in HIGH_FREQ_PHRASES:
            try:
                chunks = []
                async for chunk in tts_service.run_stream(phrase):
                    chunks.append(chunk)
                if chunks:
                    self._cache[phrase] = b"".join(chunks)
                    success += 1
            except Exception as e:
                logger.warning("[TTS-Cache] 預熱失敗: '{}' → {}", phrase, e)
        logger.info("[TTS-Cache] 預熱完成: {}/{} 成功", success, len(HIGH_FREQ_PHRASES))

    def get(self, text: str) -> Optional[bytes]:
        """查詢快取，命中返回完整音訊 bytes，未命中返回 None"""
        return self._cache.get(text)

    async def get_stream(self, text: str) -> Optional[AsyncIterator[bytes]]:
        """查詢快取並以串流方式返回（相容 run_stream 介面）"""
        audio = self._cache.get(text)
        if audio is None:
            return None

        async def _iter():
            yield audio
        return _iter()

    @property
    def size(self) -> int:
        return len(self._cache)


# 全域單例
tts_cache = TTSCache()
