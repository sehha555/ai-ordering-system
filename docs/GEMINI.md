# GEMINI.md

#ai_fixable #專案首頁 #gemini_cli

## 專案概覽 (Project Overview)

「源飯糰 AI 語音點餐系統」是一個專為台灣餐飲業設計的 AI 語音點餐原型。系統結合了語音識別 (ASR)、自然語言處理 (NLP)、以及語音合成 (TTS)，提供流暢且具備領域知識的點餐體驗。

### 核心技術棧
- **後端 (Backend)**: Python 3.10+, FastAPI, Uvicorn, SQLite
- **前端 (Frontend)**: Next.js (App Router), React 19, Zustand, Tailwind CSS 4
- **AI/NLP**: 
  - 對話管理: 自定義 Slot-filling 狀態機
  - 語音處理: OpenAI Whisper (ASR), Edge-TTS (TTS)
  - LLM: 支援 OpenAI 相容接口 (如 LM Studio)
- **工具/流程**: uv (包管理), pytest (測試框架), GitHub Actions (CI)

### 系統架構
1. **Dialogue Manager (src/dm/)**: 核心狀態機，負責維持購物車、處理補槽 (Slot-filling) 與多品項拆分。
2. **Order Router (src/tools/order_router.py)**: 將用戶輸入路由至對應的商品解析工具或操作指令。
3. **Product Tools (src/tools/)**: 各類商品（飯糰、飲料、漢堡、套餐等）的解析邏輯與定價計算。
4. **API (src/api/)**: 提供 WebSocket 與 RESTful API 供前端與外部系統對接。

---

## 建構與執行 (Building and Running)

### 環境設置
專案建議使用 `uv` 進行依賴管理：
```powershell
# 安裝依賴
uv pip sync --all-features
```

### 執行命令
- **後端 API**: `uv run uvicorn src.api.app:app --reload`
- **前端 (Next.js)**: 
  ```powershell
  cd src/frontend_next
  npm install
  npm run dev
  ```
- **CLI 測試工具**:
  - 互動式 CLI: `uv run python src/main.py`
  - DM 測試 CLI: `uv run python scripts/run_dm_cli.py`

### 測試執行
```powershell
# 運行所有測試
uv run pytest -q

# 分類測試
uv run pytest -m bdd        # BDD 測試
uv run pytest -m security   # 安全性測試
uv run pytest -m contract   # 契約測試
```

---

## 開發慣例 (Development Conventions)

### 代碼風格
- 使用 **Traditional Chinese (繁體中文)** 撰寫程式碼註釋與 Commit 訊息。
- 遵循 **Clean Code** 與 **DRY** 原則，優先重用現有的工具類。
- 定價邏輯應統一透過 `src/tools/menu/menu_price_service.py` 查詢。

### 測試慣例
- 新功能開發必須包含對應的測試檔案或 Gherkin feature 文件。
- BDD 測試文件位於 `tests/features/`。
- 修改 DM 或 Router 邏輯後，必須確保 `pytest -m bdd` 通過。

### 提交規範
- Commit 格式: `type: 簡短描述` (例如: `fix: 修正飯糰加蛋價格計算`)
- 在進行重大變更前，應先執行測試套件。

---

## 關鍵檔案說明 (Key Files)
- `src/dm/dialogue_manager.py`: 對話控制中樞。
- `src/tools/order_router.py`: 意圖路由與正規化。
- `src/tools/menu/menu_all.json`: 完整菜單定義。
- `src/frontend_next/store/useStore.ts`: 前端全域狀態管理。

---

## 修改紀錄 (Audit Trail)
- 2026-02-09: 初始建立 GEMINI.md，定義專案架構與開發規範。 #AuditTrail by gemini-cli
