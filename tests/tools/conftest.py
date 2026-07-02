# tests/tools/conftest.py
# 將 repo 根目錄加入 sys.path，讓 tools/ 下的模組可被 import
import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parents[2])
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
