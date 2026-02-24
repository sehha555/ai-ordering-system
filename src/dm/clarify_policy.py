from typing import Dict, Any, List

RICE_CHOICES_TEXT = "還差米種，你要紫米、白米還是混米？"


def recompute_missing_slots(rtype: str, frame: Dict[str, Any]) -> List[str]:
    """計算品項缺少的必填欄位"""
    if frame.get("_price_driven_confirm"):
        return ["_price_driven_confirm"]
    missing = []
    if rtype == "riceball":
        if not frame.get("flavor"):
            missing.append("flavor")
        if not frame.get("rice"):
            missing.append("rice")
    elif rtype == "drink":
        if not frame.get("drink"):
            missing.append("drink")
        if not frame.get("temp"):
            missing.append("temp")
        if not frame.get("size"):
            missing.append("size")
    elif rtype == "carrier":
        if not frame.get("carrier"):
            missing.append("carrier")
        if not frame.get("flavor"):
            missing.append("flavor")
    elif rtype == "jam_toast":
        if not frame.get("jam_toast") and not frame.get("flavor"):
            missing.append("flavor")
        if not frame.get("size"):
            missing.append("size")
    elif rtype == "egg_pancake":
        if not frame.get("flavor"):
            missing.append("flavor")
    elif rtype == "snack":
        if not frame.get("snack"):
            missing.append("snack")
    return missing


def clarify_message(rtype: str, missing: List[str], pending_frame: Dict[str, Any] = None) -> str:
    """根據品項類型和缺少欄位產生澄清問題"""
    if not missing:
        return "請問還需要什麼嗎？"
    f = missing[0]
    if f == "_price_driven_confirm" and pending_frame:
        return pending_frame.get("_price_driven_msg", "確認換杯型嗎？")

    if rtype == "drink":
        if f == "temp":
            return "你要冰的、溫的？"
        if f == "size":
            return "大杯還中杯？"
        return "請問要什麼飲料？"
    if rtype == "riceball":
        if f == "rice":
            return RICE_CHOICES_TEXT
        if f == "flavor":
            return "想要哪個口味的飯糰？"
    if rtype == "carrier":
        if f == "carrier":
            return "你要漢堡、吐司還是饅頭？"
        if f == "flavor":
            return "請問要什麼口味？"
    if rtype == "jam_toast":
        if f == "flavor":
            return "請問要什麼口味的果醬吐司？"
        if f == "size":
            return "要厚片還是薄片呢？"
    if rtype == "egg_pancake":
        if f == "flavor":
            return "請問要什麼口味的蛋餅？"
    return "請問要補充什麼？"


def question_for_missing_slot(frame: Dict[str, Any], missing_slots: List[str]) -> str:
    """向後相容：舊有的 riceball 專用介面"""
    if 'price_confirm' in missing_slots:
        return '你想要包多少錢的？（最低35元、5元級距，例如35/40/45）'
    if 'rice' in missing_slots:
        flavor = frame.get('flavor') or '這個飯糰'
        return f'{flavor}請問要白米、紫米還是混米？'
    if 'flavor' in missing_slots:
        return '請問要什麼口味的飯糰？（例如：源味傳統、醬燒里肌…）'
    return '請再說清楚一點～'
