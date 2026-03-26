# src/utils/perf_collector.py
"""效能數據收集器 — in-memory circular buffer + SQLite 持久化，供 /api/perf-stats 使用"""

import sqlite3
import time
from collections import deque
from typing import Optional

from loguru import logger


class _PerfEntry:
    __slots__ = ("timestamp", "asr_s", "dm_s", "ttfa_s", "tts_s", "total_s")

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
    def __init__(self, maxlen: int = 50, db_path: str = "orders.db"):
        self._entries: deque[_PerfEntry] = deque(maxlen=maxlen)
        self._db_path = db_path
        self._init_table()

    # ── SQLite 初始化 ──────────────────────────────────────────────

    def _init_table(self) -> None:
        """建立 perf_metrics 資料表（若不存在）"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS perf_metrics (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL    NOT NULL,
                        asr_s     REAL,
                        dm_s      REAL,
                        ttfa_s    REAL,
                        tts_s     REAL,
                        total_s   REAL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_ts ON perf_metrics(timestamp)")
        except Exception as e:
            logger.warning("[PerfCollector] 初始化資料表失敗（不影響主流程）: {}", e)

    def _persist(self, entry: _PerfEntry) -> None:
        """將效能紀錄寫入 SQLite，失敗只 log warning"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO perf_metrics (timestamp, asr_s, dm_s, ttfa_s, tts_s, total_s) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        entry.timestamp,
                        entry.asr_s,
                        entry.dm_s,
                        entry.ttfa_s,
                        entry.tts_s,
                        entry.total_s,
                    ),
                )
        except Exception as e:
            logger.warning("[PerfCollector] 寫入 SQLite 失敗（不影響主流程）: {}", e)

    # ── 公開介面 ───────────────────────────────────────────────────

    def record(
        self,
        asr_s: Optional[float] = None,
        dm_s: Optional[float] = None,
        ttfa_s: Optional[float] = None,
        tts_s: Optional[float] = None,
        total_s: Optional[float] = None,
    ) -> None:
        entry = _PerfEntry(asr_s=asr_s, dm_s=dm_s, ttfa_s=ttfa_s, tts_s=tts_s, total_s=total_s)
        self._entries.append(entry)
        self._persist(entry)

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

    def query_history(self, hours: float = 24, limit: int = 500) -> list[dict]:
        """從 SQLite 查詢歷史效能紀錄（預設最近 24 小時，最多 500 筆）"""
        cutoff = time.time() - hours * 3600
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT timestamp, asr_s, dm_s, ttfa_s, tts_s, total_s "
                    "FROM perf_metrics "
                    "WHERE timestamp > ? "
                    "ORDER BY timestamp DESC "
                    "LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("[PerfCollector] 查詢歷史失敗: {}", e)
            return []


# 全域單例
perf_collector = PerfCollector()
