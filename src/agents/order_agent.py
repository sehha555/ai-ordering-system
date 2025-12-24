# src/agents/order_agent.py
"""
Order Agent - 訂單處理 (含狀態機修正版)

新增功能：
1. 狀態機接管「口味填空」：上一輪問口味，這輪短回答 → 程式直接填入，不給 LLM
2. 自動追蹤 pending item，避免載體重複問
"""

from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, Any


class OrderAgent:
    """訂單代理"""

    def __init__(self, llm_service):
        self.llm_service = llm_service
        self.system_prompt = self._load_system_prompt()

    # ========= System Prompt 載入 =========

    def _load_system_prompt(self) -> str:
        """載入 System Prompt"""
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "system_prompt.md"

        if not prompt_path.exists():
            return (
                "你是源飯糰的點餐店員，親切且專業。"
                "一次只問一個問題，等客人回答再問下一題。"
                "回覆使用繁體中文。"
            )

        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    # ========= 狀態機工具 =========

    def _is_flavor_response(self, user_input: str, order_state: dict) -> bool:
        """判斷這是不是「上一輪問口味，這輪回答口味」的狀況"""
        pending = order_state.get("pending")
        if not pending or pending.get("slot") != "flavor":
            return False
        
        # 短回答（1-6字）通常是口味
        return 1 <= len(user_input.strip()) <= 6

    def _fill_flavor_to_order(self, flavor: str, order_state: dict) -> str:
        """把口味填進訂單，返回確認語"""
        item_type = order_state["pending"]["type"]
        
        # 找第一個符合的 item 填入口味
        for item in order_state.setdefault("items", []):
            if item.get("type") == item_type and not item.get("flavor"):
                item["flavor"] = flavor.strip()
                break
        
        # 清空 pending 狀態
        order_state["pending"] = None
        
        return f"好的，{flavor}{item_type}一份。"

    # ========= 問句處理工具 =========

    def _first_question_mark_index(self, text: str) -> int:
        """回傳第一個問號（中/英）的 index，找不到回 -1"""
        idx_zh = text.find("？")
        idx_en = text.find("?")
        idxs = [i for i in (idx_zh, idx_en) if i != -1]
        return min(idxs) if idxs else -1

    def _strip_example_tail_after_question(self, text: str) -> str:
        """去掉問句後面多餘的「比如/例如/像是...」尾巴"""
        t = (text or "").strip()
        if not t:
            return t

        qidx = self._first_question_mark_index(t)
        if qidx == -1:
            return t

        tail = t[qidx + 1 :].strip()
        if not tail:
            return t

        if re.match(r"^(比如|例如|譬如|像是|像|可選|可以|有|例如說)\b", tail):
            return t[: qidx + 1].strip()

        if ("、" in tail or "或" in tail or "還是" in tail) and len(tail) <= 20:
            return t[: qidx + 1].strip()

        return t

    def _normalize_flavor_question(self, text: str, order_state: dict) -> tuple[str, Dict[str, Any]]:
        """
        識別「請問XX要什麼口味呢？」並設 pending 狀態
        返回：(處理後文字, pending狀態)
        """
        t = (text or "").strip()
        if not t:
            return t, {}

        if ("請問" not in t) or ("口味" not in t):
            return t, {}

        # 提取品項名稱
        item_match = re.search(r"請問(.+?)要什麼口味", t)
        if item_match:
            item_type = item_match.group(1).strip()
            # 清理品項名稱（去掉「的」）
            item_type = item_type.rstrip("的")
            return t, {"type": item_type, "slot": "flavor"}
        
        return t, {}

    def _force_single_question(self, text: str) -> str:
        """只保留第一個問號之前的內容"""
        if not text:
            return text

        t = text.strip()
        qidx = self._first_question_mark_index(t)
        if qidx != -1:
            return t[: qidx + 1].strip()

        if "\n" in t:
            return t.split("\n", 1)[0].strip()

        return t

    # ========= 主流程 =========

    def process_order(self, user_input: str, order_state: dict) -> str:
        """處理點餐對話"""
        
        # ========== 1. 狀態機：口味填空接管 ==========
        if self._is_flavor_response(user_input, order_state):
            flavor_confirmation = self._fill_flavor_to_order(user_input, order_state)
            return flavor_confirmation
        
        # ========== 2. LLM 生成回應 ==========
        full_prompt = (
            f"客人剛剛說：{user_input}\n"
            f"目前訂單狀態（僅供參考）：{order_state}\n"
            "請以點餐店員身分，用口語化繁體中文回覆客人。"
        )

        raw = self.llm_service.call_llm(
            user_message=full_prompt,
            system_prompt=self.system_prompt,
        )

        t = raw.strip() if raw else ""

        # ========== 3. 後處理 ==========
        # 3.1 識別並設定 pending 狀態（如果是問口味）
        t, pending_state = self._normalize_flavor_question(t, order_state)
        if pending_state:
            order_state["pending"] = pending_state

        # 3.2 去掉例子尾巴
        t = self._strip_example_tail_after_question(t)
        # 3.3 只保留第一個問號
        t = self._force_single_question(t)

        return t
