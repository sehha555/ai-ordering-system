# src/services/tts_cache.py
"""TTS 預快取層 — 啟動時對高頻固定回覆預生成音檔，命中時 TTFA ≈ 0"""

import re
from collections import OrderedDict
from typing import AsyncIterator, Dict, Optional

from loguru import logger

# 正規化：去除常見標點，統一 lookup key
_PUNCT_RE = re.compile(r"[，。？！、；：\s]+")


def _normalize(text: str) -> str:
    """去標點 + 空白，產生正規化 key"""
    return _PUNCT_RE.sub("", text)


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
    # clarify_policy.py 帶標點回覆（正規化後自動與無標點版共用快取）
    "請問還需要什麼嗎？",
    "你要冰的、溫的？",
    "大杯還中杯？",
    "請問要什麼飲料？",
    "想要哪個口味的飯糰？",
    "你要漢堡、吐司還是饅頭？",
    "請問要什麼口味？",
    "請問要什麼口味的果醬吐司？",
    "要厚片還是薄片呢？",
    "請問要什麼口味的蛋餅？",
    "請問要補充什麼？",
    # dialogue_manager.py 歡迎語
    "您可以直接說想點的品項，例如「一個鮪魚飯糰」或「大杯冰豆漿」，我會幫您加入購物車。",
    # priming demo 回覆變體（模型學到的短句格式）
    "好～還要什麼？",
    "飲料要冰的還是溫的？",
    "好，奶茶要中冰還是中溫？",
    # 套餐複合追問（combo + 規格一起問）
    "飯糰要紫米白米還是混米 飲料冰的溫的",
    "飲料要冰的溫的 大杯中杯",
    "大杯中杯 冰的溫的",
    "厚片要什麼口味 飲料冰的溫的",
    # 常見對話片段
    "你好！歡迎光臨，請問要點什麼呢？",
    "吐司還是漢堡",
    "饅頭要什麼口味",
    # 離題引導
    "不好意思我只負責點餐 還需要什麼嗎",
]


_MAX_RUNTIME_ENTRIES = 512  # runtime cache 上限（不含 warmup 預熱條目）


class TTSCache:
    """TTS 音訊預快取：啟動時預生成，查詢時直接返回 bytes

    設計：
    - _warmup_cache: 永不淘汰的高頻預熱條目（Dict）
    - _runtime_cache: 真 LRU，上限 _MAX_RUNTIME_ENTRIES（OrderedDict）
    """

    def __init__(self):
        self._warmup_cache: Dict[str, bytes] = {}
        self._runtime_cache: OrderedDict[str, bytes] = OrderedDict()

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
                    audio = b"".join(chunks)
                    self._store_warmup(phrase, audio)
                    success += 1
            except Exception as e:
                logger.warning("[TTS-Cache] 預熱失敗: '{}' → {}", phrase, e)
        logger.info(
            "[TTS-Cache] 預熱完成: {}/{} 成功, 快取條目 {}",
            success,
            len(HIGH_FREQ_PHRASES),
            len(self._warmup_cache),
        )

    def _store_warmup(self, text: str, audio: bytes) -> None:
        """存入 warmup cache（含正規化 key，永不淘汰）"""
        self._warmup_cache[text] = audio
        norm = _normalize(text)
        if norm != text:
            self._warmup_cache[norm] = audio

    def get(self, text: str) -> Optional[bytes]:
        """查詢快取：warmup 優先，再查 runtime（命中時移至末尾維持 LRU 順序）"""
        result = self._warmup_cache.get(text) or self._warmup_cache.get(_normalize(text))
        if result is not None:
            return result
        norm = _normalize(text)
        result = self._runtime_cache.get(text) or self._runtime_cache.get(norm)
        if result is not None:
            # 移至末尾（最近使用）
            key = text if text in self._runtime_cache else norm
            self._runtime_cache.move_to_end(key)
        return result

    def put(self, text: str, audio: bytes) -> None:
        """Runtime cache：TTS miss 後存入，真 LRU eviction（移除最久未用條目）"""
        keys = [text]
        norm = _normalize(text)
        if norm != text:
            keys.append(norm)
        for key in keys:
            self._runtime_cache[key] = audio
            self._runtime_cache.move_to_end(key)
        # LRU eviction
        while len(self._runtime_cache) > _MAX_RUNTIME_ENTRIES:
            self._runtime_cache.popitem(last=False)

    async def get_stream(self, text: str) -> Optional[AsyncIterator[bytes]]:
        """查詢快取並以串流方式返回（相容 run_stream 介面）"""
        audio = self.get(text)
        if audio is None:
            return None

        async def _iter():
            yield audio

        return _iter()

    @property
    def size(self) -> int:
        return len(self._warmup_cache) + len(self._runtime_cache)


# 全域單例
tts_cache = TTSCache()
