from typing import Dict, Any, List

def question_for_missing_slot(frame: Dict[str, Any], missing_slots: List[str]) -> str:
    # 只處理你目前最重要的兩個 slot；之後再擴充
    if 'price_confirm' in missing_slots:
        return '你想要包多少錢的？（最低35元、5元級距，例如35/40/45）'
    if 'rice' in missing_slots:
        flavor = frame.get('flavor') or '這個飯糰'
        return f'{flavor}請問要白米、紫米還是混米？'
    if 'flavor' in missing_slots:
        return '請問要什麼口味的飯糰？（例如：源味傳統、醬燒里肌…）'
    return '請再說清楚一點～'
