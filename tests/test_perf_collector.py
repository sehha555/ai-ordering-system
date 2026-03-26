# tests/test_perf_collector.py
"""測試 PerfCollector SQLite 持久化功能"""

import time

import pytest

from src.utils.perf_collector import PerfCollector


def test_record_persists_to_sqlite(tmp_path):
    """record() 應將資料寫入 SQLite，query_history 可讀回"""
    db = tmp_path / "test.db"
    pc = PerfCollector(db_path=str(db))

    pc.record(asr_s=1.0, dm_s=2.0, ttfa_s=0.5, tts_s=1.5, total_s=5.0)

    history = pc.query_history(hours=1)
    assert len(history) == 1
    assert history[0]["asr_s"] == 1.0
    assert history[0]["dm_s"] == 2.0
    assert history[0]["ttfa_s"] == 0.5
    assert history[0]["tts_s"] == 1.5
    assert history[0]["total_s"] == 5.0


def test_query_history_time_filter(tmp_path):
    """hours 篩選：超出時間範圍的資料不應回傳"""
    import sqlite3

    db = tmp_path / "test.db"
    pc = PerfCollector(db_path=str(db))

    # 插入一筆「2 小時前」的舊資料（直接寫 DB 繞過 record()）
    old_ts = time.time() - 7200  # 2 小時前
    with sqlite3.connect(str(db)) as conn:
        conn.execute(
            "INSERT INTO perf_metrics (timestamp, asr_s, dm_s, ttfa_s, tts_s, total_s) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (old_ts, 0.5, 1.0, 0.3, 0.8, 2.6),
        )

    # 查最近 1 小時 → 舊資料不在範圍內
    history_1h = pc.query_history(hours=1)
    assert len(history_1h) == 0

    # 查最近 3 小時 → 舊資料應出現
    history_3h = pc.query_history(hours=3)
    assert len(history_3h) == 1
    assert history_3h[0]["asr_s"] == 0.5


def test_query_history_empty(tmp_path):
    """空 DB 時 query_history 應回傳空 list"""
    db = tmp_path / "test.db"
    pc = PerfCollector(db_path=str(db))
    assert pc.query_history() == []


def test_record_multiple_persists(tmp_path):
    """多筆 record() 應全部持久化，limit 參數正常運作"""
    db = tmp_path / "test.db"
    pc = PerfCollector(db_path=str(db))

    for i in range(10):
        pc.record(total_s=float(i))

    history_all = pc.query_history(hours=1)
    assert len(history_all) == 10

    history_limited = pc.query_history(hours=1, limit=3)
    assert len(history_limited) == 3


def test_record_null_fields_persist(tmp_path):
    """欄位為 None 時也能正常持久化與讀回"""
    db = tmp_path / "test.db"
    pc = PerfCollector(db_path=str(db))

    pc.record(total_s=3.0)  # 其餘欄位皆為 None

    history = pc.query_history(hours=1)
    assert len(history) == 1
    assert history[0]["total_s"] == pytest.approx(3.0)
    assert history[0]["asr_s"] is None
    assert history[0]["dm_s"] is None


def test_inmemory_stats_unaffected_by_db_error(tmp_path):
    """DB 路徑不可寫時，in-memory stats 仍正常運作"""
    # 使用不存在目錄模擬 DB 失敗
    bad_db = str(tmp_path / "nonexistent_dir" / "test.db")
    pc = PerfCollector(db_path=bad_db)

    # record 不應拋出例外
    pc.record(asr_s=0.5, total_s=1.0)

    # in-memory stats 仍有資料
    stats = pc.get_stats()
    assert stats["count"] == 1
    assert stats["averages"]["total_s"] == pytest.approx(1.0)

    # query_history 失敗時回傳空 list
    history = pc.query_history(hours=1)
    assert history == []
