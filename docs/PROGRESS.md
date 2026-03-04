# 開發進度紀錄

**最後更新**: 2026-02-06

---

## 目前狀態

### 已完成

#### 後端 (FastAPI)
- [x] LLM 整合 (Qwen2.5 + Function Calling)
- [x] ASR 語音轉文字 (Qwen3-ASR)
- [x] TTS 文字轉語音 (Edge TTS)
- [x] 對話管理 (DialogueManager)
- [x] 工具註冊表 (ToolRegistry)
- [x] 購物車 API (`/cart/summary`)
- [x] 菜單 API (`/api/menu`)
- [x] 店家設定 API (`/api/store-config`)
- [x] SSE 語音聊天端點 (`/api/voice-chat`)
- [x] 集中式設定檔 (`src/config/store_config.json`)
- [x] 從檔案載入 System Prompt (`prompts/system_prompt.md`)

#### 前端 - 簡單版 (`src/frontend/`)
- [x] 50/50 左右分欄版面
- [x] 淺色主題配色 (#729DAD 藍綠色調)
- [x] PDF/圖片菜單顯示
- [x] VAD 語音喚醒（自動偵測音量）
- [x] 圓形波形視覺化
- [x] 訂單列表顯示
- [x] 多步驟結帳流程

#### 前端 - Next.js 版 (`src/frontend_next/`)
- [x] 專案初始化 (Next.js 14 + TypeScript + Tailwind)
- [x] Zustand Store 設定
- [x] AudioVisualizer 元件（基礎）
- [x] VoiceController 元件（SSE 支援）
- [ ] **未完成** - 需要繼續開發

---

## 待辦事項

### 下次繼續：整合 Next.js 前端

根據 `IMPLEMENTATION_BLUEPRINT.md` 的計畫，Next.js 前端還需要：

1. **套用新配色**
   - Primary: `#729DAD`
   - Background: `#F5F7F8`
   - 參考 `src/frontend/style.css` 的配色

2. **完善 AudioVisualizer**
   - 四種狀態動畫：Idle / Listening / Thinking / Speaking
   - 使用 Canvas API 繪製波形

3. **完善 VoiceController**
   - VAD 自動偵測（參考簡單版的實作）
   - SSE 事件處理
   - 音訊播放 Queue

4. **新增 LiveReceipt 元件**
   - 顯示購物車內容
   - Framer Motion 動畫效果

5. **整合菜單顯示**
   - 顯示 PDF/圖片菜單
   - 或從 `/api/menu` 載入動態菜單

6. **結帳流程**
   - 用餐方式選擇
   - 付款方式選擇
   - 訂單確認頁
   - 取餐號碼顯示

---

## 檔案結構

```
ai-ordering-system/
├── src/
│   ├── api/
│   │   ├── app.py              # FastAPI 主程式
│   │   └── voice_router.py     # SSE 語音聊天路由
│   ├── config/
│   │   └── store_config.json   # 店家設定（店名、prompt路徑等）
│   ├── frontend/               # 簡單版前端（純 HTML/CSS/JS）
│   │   ├── index.html
│   │   ├── style.css
│   │   ├── app.js
│   │   ├── menu.pdf
│   │   └── menu.png
│   ├── frontend_next/          # Next.js 前端（開發中）
│   │   ├── app/
│   │   ├── components/
│   │   ├── store/
│   │   └── ...
│   └── tools/menu/
│       └── menu_all.json       # 菜單資料
├── prompts/
│   └── system_prompt.md        # LLM 系統提示詞
└── IMPLEMENTATION_BLUEPRINT.md # 完整實作計畫
```

---

## 快速啟動

### 後端
```bash
uvicorn src.api.app:app --reload --port 8000
```

### 簡單版前端
開啟瀏覽器：`http://localhost:8000`

### Next.js 前端
```bash
cd src/frontend_next
npm run dev
```
開啟瀏覽器：`http://localhost:3000`

---

## 決策紀錄

1. **配色主題**：採用 `#729DAD` 低飽和藍綠色，淺色背景
2. **菜單顯示**：使用 PNG 圖片（從 PDF 轉換），避免 PDF 瀏覽器黑底問題
3. **設定集中化**：店名、Prompt 路徑都放在 `store_config.json`，方便換店家
4. **兩套前端並存**：簡單版可直接使用，Next.js 版持續開發中
