import os
import re
import json
from fastapi import FastAPI, HTTPException, Security, Depends, File, UploadFile, Form
from fastapi.security.api_key import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
from pydantic import BaseModel
from src.repository.order_repository import order_repo
from src.dm.dialogue_manager import DialogueManager
from src.dm.session_store import InMemorySessionStore
from src.services.asr_service import ASRService
from src.services.tts_service import TTSService
from src.services.llm_tool_caller import LLMToolCaller
from src.dm.tool_registry import ToolRegistry

# ============================================================================
# 載入店家設定
# ============================================================================

def load_store_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "store_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_system_prompt(config):
    """從檔案載入系統提示詞"""
    prompt_cfg = config.get("prompt", {})

    # 優先使用檔案路徑
    if "file_path" in prompt_cfg:
        prompt_path = prompt_cfg["file_path"]
        # 支援相對路徑（從專案根目錄）
        if not os.path.isabs(prompt_path):
            prompt_path = os.path.join(os.path.dirname(__file__), "..", "..", prompt_path)

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    # 否則使用預設提示詞
    store_name = config["store"]["name"]
    return f"你是「{store_name}」的點餐助手，負責幫客人點餐。請使用繁體中文回覆。"

# 載入設定
STORE_CONFIG = load_store_config()
SYSTEM_PROMPT = load_system_prompt(STORE_CONFIG)
from src.api.voice_router import router as voice_router

app = FastAPI(title="Yuan Rice Ball Order API")

# 註冊語音聊天路由
app.include_router(voice_router, prefix="/api", tags=["voice"])

# 掛載靜態檔案
app.mount("/static", StaticFiles(directory="src/frontend"), name="static")

# 初始化服務
_session_store = InMemorySessionStore()
_llm_caller = LLMToolCaller(
    base_url="http://127.0.0.1:1234/v1/chat/completions",
    model="qwen2.5-14b-instruct-1m",
    timeout=120,  # 增加超時時間
)
_dialogue_manager = DialogueManager(llm=_llm_caller, store=_session_store)
_tool_registry = ToolRegistry(_dialogue_manager, _session_store)
_asr_service = ASRService(model_size="turbo", language="zh")  # 使用 Qwen3-ASR-Turbo
_tts_service = TTSService(voice="female", rate="+0%")



class TextDialogueRequest(BaseModel):
    """文本對話請求"""
    session_id: str
    text: str


class TextDialogueResponse(BaseModel):
    """文本對話響應"""
    session_id: str
    response: str
    status: str = "ok"

API_KEY = os.getenv("API_KEY", "yuan-secret-key")
api_key_header = APIKeyHeader(name="X-API-Key")

def get_api_key(api_key: str = Security(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

def validate_order_id(order_id: str):
    if not re.match(r"^[A-Z0-9-]+$", order_id) or len(order_id) > 20:
        raise HTTPException(status_code=400, detail="Invalid Order ID format")

@app.get("/")
async def serve_frontend():
    """根路徑返回前端頁面"""
    return FileResponse("src/frontend/index.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


# ============================================================================
# 店家設定 API
# ============================================================================

@app.get("/api/store-config")
async def get_store_config():
    """取得店家設定（前端用）"""
    return {
        "store": STORE_CONFIG["store"],
        "ui": STORE_CONFIG["ui"]
    }


# ============================================================================
# 菜單 API
# ============================================================================

@app.get("/api/menu")
async def get_menu():
    """
    取得完整菜單供前端渲染
    按分類組織，包含圖示
    """
    import json

    # 讀取菜單數據
    menu_path = os.path.join(os.path.dirname(__file__), "..", "tools", "menu", "menu_all.json")
    with open(menu_path, "r", encoding="utf-8-sig") as f:
        menu_items = json.load(f)

    # 分類圖示對應
    category_icons = {
        "飯糰": "🍙",
        "蛋餅": "🥞",
        "吐司": "🍞",
        "漢堡": "🍔",
        "饅頭": "🥟",
        "蔥抓餅": "🫓",
        "鐵板麵": "🍝",
        "點心": "🍟",
        "果醬吐司": "🍯",
        "飲品": "🥤",
        "套餐": "🍱",
    }

    # 按分類組織
    categories_dict = {}
    for item in menu_items:
        cat = item["category"]
        if cat not in categories_dict:
            categories_dict[cat] = {
                "name": cat,
                "icon": category_icons.get(cat, "📦"),
                "items": []
            }
        categories_dict[cat]["items"].append({
            "name": item["name"],
            "price": item["price"]
        })

    # 按固定順序排列分類
    category_order = ["飯糰", "蛋餅", "吐司", "漢堡", "饅頭", "蔥抓餅", "鐵板麵", "點心", "果醬吐司", "飲品", "套餐"]
    categories = []
    for cat_name in category_order:
        if cat_name in categories_dict:
            categories.append(categories_dict[cat_name])

    return {"categories": categories}

@app.get("/orders/{order_id}")
async def get_order(order_id: str, api_key: str = Depends(get_api_key)):
    validate_order_id(order_id)
    order = order_repo.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/orders")
async def list_orders(
    date: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    api_key: str = Depends(get_api_key)
):
    orders = order_repo.list_orders(date=date, status=status, limit=limit, offset=offset)
    return {"items": orders, "count": len(orders)}


# ============================================================================
# 購物車 API
# ============================================================================

@app.get("/cart/summary")
async def get_cart_summary(
    session_id: str,
    api_key: str = Depends(get_api_key)
):
    """
    取得購物車摘要
    """
    try:
        session = _session_store.get(session_id)
        cart = session.get("cart", [])

        if not cart:
            return {
                "ok": True,
                "cart_count": 0,
                "items": [],
                "total_price": 0,
                "message": "購物車為空",
            }

        items = []
        total_price = 0

        for i, item in enumerate(cart, 1):
            qty = int(item.get("quantity", 1) or 1)

            # 格式化品項名稱
            name = _dialogue_manager.format_item(item)

            # 計算價格
            price_info = _dialogue_manager.get_price_info(item)
            if price_info and price_info.get("status") == "success":
                item_total = _dialogue_manager.extract_total_from_price_info(price_info, qty)
                total_price += item_total
                price_str = f"${item_total}"
            else:
                price_str = ""

            items.append({
                "index": i,
                "name": name,
                "quantity": qty,
                "price": price_str,
            })

        return {
            "ok": True,
            "cart_count": len(cart),
            "items": items,
            "total_price": total_price,
            "message": f"購物車共 {len(cart)} 項，總計 ${total_price}",
        }

    except Exception as e:
        return {"ok": False, "error": str(e), "items": [], "total_price": 0}


# ============================================================================
# 語音對話 API 端點
# ============================================================================

@app.post("/dialogue/text", response_model=TextDialogueResponse)
async def text_dialogue(request: TextDialogueRequest, api_key: str = Depends(get_api_key)):
    """
    文本對話端點（文字輸入，文字輸出）
    使用 LLM + Function Calling 處理點餐邏輯
    """
    import sys

    def debug(msg):
        print(f"[TEXT] {msg}", file=sys.stderr, flush=True)

    try:
        session_id = request.session_id
        user_text = request.text

        debug(f"收到文字: '{user_text}'")

        # 設置當前會話
        _tool_registry.set_session_id(session_id)

        # 確保會話存在
        session = _session_store.get(session_id)
        session.setdefault("llm_history", [])

        # 調用 LLM
        result = _llm_caller.run_turn(
            system_prompt=SYSTEM_PROMPT,
            user_text=user_text,
            history=session["llm_history"],
            tools_schema=_tool_registry.get_tools_schema(),
            tool_map=_tool_registry.get_tool_map(),
            allowed_args=_tool_registry.get_allowed_args(),
        )

        if result.get("ok"):
            session["llm_history"] = result.get("history", [])
            response_text = result.get("assistant_text", "")
            if not response_text:
                response_text = "好的，還需要什麼嗎？"
            debug(f"LLM 回應: '{response_text}'")
            return TextDialogueResponse(
                session_id=session_id,
                response=response_text,
                status="ok"
            )
        else:
            debug(f"LLM 錯誤: {result.get('error')}")
            return TextDialogueResponse(
                session_id=session_id,
                response="抱歉，系統暫時無法處理，請稍後再試。",
                status="error"
            )

    except Exception as e:
        import traceback
        debug(f"異常: {e}\n{traceback.format_exc()}")
        return TextDialogueResponse(
            session_id=request.session_id,
            response=f"錯誤: {str(e)}",
            status="error"
        )


@app.post("/dialogue/llm")
async def llm_dialogue(request: TextDialogueRequest, api_key: str = Depends(get_api_key)):
    """
    LLM 對話端點（使用 Qwen2.5 + Function Calling）

    用例：
        curl -X POST http://localhost:8000/dialogue/llm \
          -H "X-API-Key: yuan-secret-key" \
          -H "Content-Type: application/json" \
          -d '{"session_id": "user123", "text": "我要一個紫米傳統飯糰"}'
    """
    import sys

    def debug(msg):
        print(f"[LLM] {msg}", file=sys.stderr, flush=True)

    try:
        session_id = request.session_id
        user_text = request.text

        debug(f"收到請求: session={session_id}, text={user_text}")

        # 設置當前會話
        _tool_registry.set_session_id(session_id)

        # 確保會話存在
        session = _session_store.get(session_id)
        session.setdefault("llm_history", [])

        # 調用 LLM
        result = _llm_caller.run_turn(
            system_prompt=SYSTEM_PROMPT,
            user_text=user_text,
            history=session["llm_history"],
            tools_schema=_tool_registry.get_tools_schema(),
            tool_map=_tool_registry.get_tool_map(),
            allowed_args=_tool_registry.get_allowed_args(),
        )

        debug(f"LLM 結果: ok={result.get('ok')}, tool_trace={len(result.get('tool_trace', []))} calls")

        if result.get("ok"):
            # 更新歷史
            session["llm_history"] = result.get("history", [])
            response_text = result.get("assistant_text", "")

            # 如果 LLM 沒有回覆，給一個預設回覆
            if not response_text:
                response_text = "好的，還需要什麼嗎？"

            return {
                "session_id": session_id,
                "response": response_text,
                "status": "ok",
                "tool_calls": len(result.get("tool_trace", [])),
            }
        else:
            return {
                "session_id": session_id,
                "response": "抱歉，處理請求時發生錯誤",
                "status": "error",
                "error": result.get("error"),
            }

    except Exception as e:
        import traceback
        debug(f"異常: {e}\n{traceback.format_exc()}")
        return {
            "session_id": request.session_id,
            "response": f"錯誤: {str(e)}",
            "status": "error",
        }


@app.post("/dialogue/voice")
async def voice_dialogue(
    session_id: str = Form(...),
    audio_file: UploadFile = File(...),
    api_key: str = Depends(get_api_key)
):
    """
    語音對話端點（語音輸入，語音輸出）
    """
    import tempfile
    import subprocess
    import sys

    def debug(msg):
        print(f"[DEBUG] {msg}", file=sys.stderr, flush=True)

    try:
        debug(f"=== 開始處理語音請求 ===")
        debug(f"session_id: {session_id}")
        debug(f"audio_file.filename: {audio_file.filename}")
        debug(f"audio_file.content_type: {audio_file.content_type}")

        # 從檔名取得副檔名
        ext = ".webm"
        if audio_file.filename:
            ext = "." + audio_file.filename.split(".")[-1] if "." in audio_file.filename else ".webm"

        content = await audio_file.read()
        debug(f"收到音訊大小: {len(content)} bytes, 副檔名: {ext}")

        if len(content) < 1000:
            debug(f"警告: 音訊檔案太小，可能是空的或錄音失敗")
            return {
                "session_id": session_id,
                "status": "error",
                "error": "音訊檔案太小，請重新錄音",
                "response": None,
                "audio_url": None
            }

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        debug(f"已保存到: {tmp_path}")

        # 保存一份到桌面用於調試
        debug_file = "C:/Users/User/Desktop/debug_recording.webm"
        with open(debug_file, "wb") as f:
            f.write(content)
        debug(f"已保存調試檔案到: {debug_file}")

        # 如果是 webm 格式，用 ffmpeg 轉換為 wav
        if ext.lower() == ".webm":
            wav_path = tmp_path.replace(".webm", ".wav")
            debug(f"開始 ffmpeg 轉換: {tmp_path} -> {wav_path}")
            try:
                result = subprocess.run([
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-ar", "16000", "-ac", "1", "-f", "wav", wav_path
                ], capture_output=True, check=True)
                debug(f"ffmpeg 轉換成功")
                debug(f"刪除原始檔案: {tmp_path}")
                os.unlink(tmp_path)
                tmp_path = wav_path
                debug(f"更新路徑為: {tmp_path}")
            except subprocess.CalledProcessError as e:
                debug(f"ffmpeg 轉換失敗: {e.stderr.decode()}")
                return {
                    "session_id": session_id,
                    "status": "error",
                    "error": f"音訊轉換失敗: {e.stderr.decode()[:200]}",
                    "response": None,
                    "audio_url": None
                }

        # 檢查轉換後的檔案
        debug(f"準備檢查檔案: {tmp_path}")
        debug(f"檔案是否存在: {os.path.exists(tmp_path)}")
        wav_size = os.path.getsize(tmp_path)
        debug(f"WAV 檔案大小: {wav_size} bytes")

        try:
            # 使用 ASR 將語音轉為文字
            debug(f"開始 ASR 轉錄...")
            asr_result = _asr_service.transcribe(tmp_path)
            debug(f"ASR 結果: {asr_result}")

            if asr_result.get("error"):
                return {
                    "session_id": session_id,
                    "status": "error",
                    "asr_error": asr_result.get("error"),
                    "response": None,
                    "audio_url": None
                }

            user_text = asr_result.get("text", "")
            debug(f"識別到的文字: '{user_text}'")

            if not user_text:
                return {
                    "session_id": session_id,
                    "status": "error",
                    "error": "無法識別語音內容",
                    "response": None,
                    "audio_url": None
                }

            # 調用 LLM 對話
            debug(f"調用 LLM 處理: '{user_text}'")
            _tool_registry.set_session_id(session_id)

            # 確保會話存在
            session = _session_store.get(session_id)
            session.setdefault("llm_history", [])

            llm_result = _llm_caller.run_turn(
                system_prompt=SYSTEM_PROMPT,
                user_text=user_text,
                history=session["llm_history"],
                tools_schema=_tool_registry.get_tools_schema(),
                tool_map=_tool_registry.get_tool_map(),
                allowed_args=_tool_registry.get_allowed_args(),
            )

            if llm_result.get("ok"):
                session["llm_history"] = llm_result.get("history", [])
                dialogue_response = llm_result.get("assistant_text", "")
                if not dialogue_response:
                    dialogue_response = "好的，還需要什麼嗎？"
                debug(f"LLM 回應: '{dialogue_response}'")
            else:
                debug(f"LLM 錯誤: {llm_result.get('error')}")
                dialogue_response = "抱歉，系統暫時無法處理，請稍後再試。"

            # 使用 TTS 將回應轉為語音
            tts_result = _tts_service.speak(dialogue_response)

            return {
                "session_id": session_id,
                "status": "ok",
                "user_text": user_text,
                "response": dialogue_response,
                "audio_url": tts_result.get("file_path")
            }

        finally:
            # 清理臨時文件
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        import traceback
        debug(f"!!! 發生異常: {type(e).__name__}: {e}")
        debug(f"異常追蹤:\n{traceback.format_exc()}")
        return {
            "session_id": session_id,
            "status": "error",
            "error": str(e),
            "response": None,
            "audio_url": None
        }


@app.get("/llm/test")
async def test_llm(api_key: str = Depends(get_api_key)):
    """
    測試 LLM 服務狀態
    """
    try:
        import requests
        resp = requests.get("http://127.0.0.1:1234/v1/models", timeout=5)
        models = resp.json().get("data", [])
        return {
            "service": "LLM (LM Studio)",
            "status": "ready",
            "model": _llm_caller.model,
            "available_models": [m.get("id") for m in models],
        }
    except Exception as e:
        return {
            "service": "LLM (LM Studio)",
            "status": "error",
            "error": str(e),
        }


@app.get("/asr/test")
async def test_asr(api_key: str = Depends(get_api_key)):
    """
    測試 ASR 服務狀態
    """
    return {
        "service": "ASR (faster-whisper)",
        "status": "ready" if _asr_service.model else "not_loaded",
        "model": _asr_service.model_name,
        "language": "zh"
    }


@app.get("/tts/test")
async def test_tts(api_key: str = Depends(get_api_key)):
    """
    測試 TTS 服務狀態
    """
    return {
        "service": "TTS (Edge TTS)",
        "status": "ready" if _tts_service.engine else "not_loaded",
        "properties": _tts_service.get_properties()
    }


@app.post("/tts/speak")
async def tts_speak(
    text: str,
    api_key: str = Depends(get_api_key)
):
    """
    直接調用 TTS 將文字轉為語音
    """
    result = _tts_service.speak(text)
    return result


@app.get("/tts/play")
async def tts_play(
    path: str,
    api_key: str = Depends(get_api_key)
):
    """
    播放 TTS 生成的音訊檔案
    """
    from fastapi.responses import FileResponse

    # 安全檢查：只允許播放 TTS 輸出目錄的檔案
    import tempfile
    tts_dir = os.path.join(tempfile.gettempdir(), "tts_output")

    # 正規化路徑
    normalized_path = os.path.normpath(path)

    if not normalized_path.startswith(tts_dir):
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(
        normalized_path,
        media_type="audio/mpeg",
        filename="response.mp3"
    )
