# src/services/tts_cache.py
"""TTS 預快取層 — 啟動時對高頻固定回覆預生成音檔，命中時 TTFA ≈ 0"""

import asyncio
import re
from collections import OrderedDict
from typing import AsyncIterator, Dict, Optional

import httpx
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
    - key 格式："{voice_key}|{text}" 以區分不同聲音身分
    """

    def __init__(self):
        self._warmup_cache: Dict[str, bytes] = {}
        self._runtime_cache: OrderedDict[str, bytes] = OrderedDict()

    @staticmethod
    def _cache_keys(text: str, voice_key: str) -> list[str]:
        """組合 cache key（原文 + 正規化版，key 格式的唯一定義處）"""
        keys = [f"{voice_key}|{text}"]
        norm = _normalize(text)
        if norm != text:
            keys.append(f"{voice_key}|{norm}")
        return keys

    async def warmup(self, tts_service) -> None:
        """啟動時預生成高頻回覆的 TTS 音檔。
        以 last_voice_key（實際產出聲音）存入 — fallback 產物存 fallback 聲音的 key，
        不會污染本尊 backend 的快取。
        """
        logger.info("[TTS-Cache] 開始預熱 {} 條高頻回覆...", len(HIGH_FREQ_PHRASES))
        success = 0
        for phrase in HIGH_FREQ_PHRASES:
            try:
                chunks = []
                async for chunk in tts_service.run_stream(phrase):
                    chunks.append(chunk)
                if chunks:
                    audio = b"".join(chunks)
                    self._store_warmup(phrase, audio, voice_key=tts_service.last_voice_key)
                    success += 1
            except Exception as e:
                logger.warning("[TTS-Cache] 預熱失敗: '{}' → {}", phrase, e)
        logger.info(
            "[TTS-Cache] 預熱完成: {}/{} 成功, 快取條目 {}",
            success,
            len(HIGH_FREQ_PHRASES),
            len(self._warmup_cache),
        )

    def _store_warmup(self, text: str, audio: bytes, voice_key: str = "default") -> None:
        """存入 warmup cache（含正規化 key，永不淘汰）"""
        for key in self._cache_keys(text, voice_key):
            self._warmup_cache[key] = audio

    def get(self, text: str, voice_key: str = "default") -> Optional[bytes]:
        """查詢快取：warmup 優先，再查 runtime（命中時移至末尾維持 LRU 順序）"""
        keys = self._cache_keys(text, voice_key)
        # warmup（永不淘汰，不更新 LRU 順序）
        for key in keys:
            result = self._warmup_cache.get(key)
            if result is not None:
                return result
        # runtime（命中時移至末尾）
        for key in keys:
            result = self._runtime_cache.get(key)
            if result is not None:
                self._runtime_cache.move_to_end(key)
                return result
        return None

    def put(self, text: str, audio: bytes, voice_key: str = "default") -> None:
        """Runtime cache：TTS miss 後存入，真 LRU eviction（移除最久未用條目）"""
        for key in self._cache_keys(text, voice_key):
            self._runtime_cache[key] = audio
            self._runtime_cache.move_to_end(key)
        # LRU eviction
        while len(self._runtime_cache) > _MAX_RUNTIME_ENTRIES:
            self._runtime_cache.popitem(last=False)

    async def get_stream(
        self, text: str, voice_key: str = "default"
    ) -> Optional[AsyncIterator[bytes]]:
        """查詢快取並以串流方式返回（相容 run_stream 介面）"""
        audio = self.get(text, voice_key=voice_key)
        if audio is None:
            return None

        async def _iter():
            yield audio

        return _iter()

    @property
    def size(self) -> int:
        return len(self._warmup_cache) + len(self._runtime_cache)


async def wait_for_tts_health(health_url: str, max_wait: int = 180, interval: float = 2.0) -> bool:
    """輪詢 TTS 微服務 /health（OmniVoice / VoxCPM），直到回傳 200 或超時。
    回傳 True = 就緒；False = 超時。
    供 app.py warmup gate 使用，可在測試中獨立驗證。
    """
    iterations = int(max_wait / interval)
    async with httpx.AsyncClient(timeout=3.0) as hc:
        for i in range(iterations):
            try:
                resp = await hc.get(health_url)
                if resp.status_code == 200:
                    return True
            except Exception:
                pass
            if i < iterations - 1:
                await asyncio.sleep(interval)
    return False


# 全域單例
tts_cache = TTSCache()
