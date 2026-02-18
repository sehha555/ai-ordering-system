# src/utils/perf_collector.py
"""效能數據收集器 — in-memory circular buffer，供 /api/perf-stats 使用"""

import time
from collections import deque
from typing import Optional


class _PerfEntry:
    __slots__ = ('timestamp', 'asr_s', 'dm_s', 'ttfa_s', 'tts_s', 'total_s')

    def __init__(
        self,
        asr_s: Optional[float] = None,
        dm_s: Optional[float] = None,
        ttfa_s: Optional[float] = None,
        tts_s: Optional[float] = None,
        total_s: Optional[float] = None,
    ):
        self.timestamp = time.time()
        self.asr_s = asr_s
        self.dm_s = dm_s
        self.ttfa_s = ttfa_s
        self.tts_s = tts_s
        self.total_s = total_s

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "asr_s": round(self.asr_s, 3) if self.asr_s is not None else None,
            "dm_s": round(self.dm_s, 3) if self.dm_s is not None else None,
            "ttfa_s": round(self.ttfa_s, 3) if self.ttfa_s is not None else None,
            "tts_s": round(self.tts_s, 3) if self.tts_s is not None else None,
            "total_s": round(self.total_s, 3) if self.total_s is not None else None,
        }


class PerfCollector:
    def __init__(self, maxlen: int = 50):
        self._entries: deque[_PerfEntry] = deque(maxlen=maxlen)

    def record(
        self,
        asr_s: Optional[float] = None,
        dm_s: Optional[float] = None,
        ttfa_s: Optional[float] = None,
        tts_s: Optional[float] = None,
        total_s: Optional[float] = None,
    ) -> None:
        self._entries.append(_PerfEntry(asr_s=asr_s, dm_s=dm_s, ttfa_s=ttfa_s, tts_s=tts_s, total_s=total_s))

    def get_stats(self) -> dict:
        entries = list(self._entries)
        if not entries:
            return {"recent": [], "averages": {}, "count": 0}

        def _avg(field: str) -> Optional[float]:
            vals = [getattr(e, field) for e in entries if getattr(e, field) is not None]
            return round(sum(vals) / len(vals), 3) if vals else None

        return {
            "recent": [e.to_dict() for e in entries],
            "averages": {
                "asr_s": _avg("asr_s"),
                "dm_s": _avg("dm_s"),
                "ttfa_s": _avg("ttfa_s"),
                "tts_s": _avg("tts_s"),
                "total_s": _avg("total_s"),
            },
            "count": len(entries),
        }


# 全域單例
perf_collector = PerfCollector()
