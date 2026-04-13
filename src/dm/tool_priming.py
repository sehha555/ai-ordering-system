"""
Few-shot priming messages — 讓本地 LLM 學會使用 text tag 格式輸出行動。

根因：LM Studio + Qwen3/2.5 需要示範對話才能正確判斷
何時輸出 [ADD:...] tag、何時直接追問、何時用 [QUERY:...] tag。

架構改變（text tag vs tool_calls）：
- 不再使用 tool_calls 欄位與 role:tool response
- 模型直接在 content 中輸出 tag（[ADD:...]、[QUERY:...]）
- backend 解析 tag 後自行執行，模型不需要看執行結果
- ok:false 場景改為「缺必填資訊就不加 tag，直接追問」

注意：demo 數量控制在 13 個以內，避免 few-shot collapse
"""

from src.config.config_loader import load_json_config

# LLM 回覆中的結帳標記（voice_router 攔截用）
_priming_cfg = load_json_config("priming_demos.json")
CHECKOUT_TAG = _priming_cfg.get("checkout_tag", "[CHECKOUT]")


def get_priming_messages() -> list[dict]:
    """精選 priming 示範，教模型用 text tag 格式輸出點餐行動。從 priming_demos.json 載入。"""
    cfg = load_json_config("priming_demos.json")
    msgs: list[dict] = []
    for demo in cfg["demos"]:
        msgs.append({"role": "user", "content": demo["user"]})
        msgs.append({"role": "assistant", "content": demo["assistant"]})
    return msgs
