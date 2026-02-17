"""SQLite 資料庫自動備份工具"""

import shutil
import os
from datetime import datetime
from pathlib import Path
from loguru import logger


def backup_database(db_path: str = "orders.db", backup_dir: str = "backups", max_backups: int = 7) -> str | None:
    """
    備份 SQLite 資料庫檔案

    Args:
        db_path: 資料庫檔案路徑
        backup_dir: 備份目錄
        max_backups: 最多保留備份數量

    Returns:
        備份檔案路徑，或 None（如果無需備份）
    """
    if not os.path.exists(db_path):
        logger.info("[BACKUP] 資料庫檔案不存在，跳過備份: {}", db_path)
        return None

    # 建立備份目錄
    os.makedirs(backup_dir, exist_ok=True)

    # 檢查今天是否已備份
    today = datetime.now().strftime("%Y-%m-%d")
    backup_name = f"orders_{today}.db"
    backup_path = os.path.join(backup_dir, backup_name)

    if os.path.exists(backup_path):
        logger.info("[BACKUP] 今日已備份，跳過: {}", backup_path)
        return backup_path

    # 執行備份
    try:
        shutil.copy2(db_path, backup_path)
        file_size = os.path.getsize(backup_path)
        logger.info("[BACKUP] 備份成功: {} ({} bytes)", backup_path, file_size)
    except Exception as e:
        logger.error("[BACKUP] 備份失敗: {}", e)
        return None

    # 清理舊備份（保留最近 max_backups 份）
    _cleanup_old_backups(backup_dir, max_backups)

    return backup_path


def _cleanup_old_backups(backup_dir: str, max_backups: int):
    """清理超出保留數量的舊備份"""
    backup_files = sorted(
        Path(backup_dir).glob("orders_*.db"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if len(backup_files) > max_backups:
        for old_file in backup_files[max_backups:]:
            old_file.unlink()
            logger.info("[BACKUP] 已刪除舊備份: {}", old_file)
