# ASR 測試資料

將測試音檔放在這個目錄，並建立 `manifest.json`。

## manifest.json 格式

```json
[
  {
    "id": "order_riceball_01",
    "audio_path": "benchmarks/test_data/asr/order_riceball_01.wav",
    "ground_truth": "我要一個鮪魚飯糰",
    "category": "點餐"
  }
]
```

## 建議測試案例

1. **基本點餐**：「我要一個鮪魚飯糰」
2. **複雜組合**：「一個起司蛋餅加一杯大冰紅茶」
3. **修改訂單**：「把飯糰換成玉米口味」
4. **數量變更**：「紅茶改兩杯」
5. **結帳**：「好，就這樣，結帳」
6. **噪音環境**：（有背景音的錄音）
7. **口音/語速變化**：快速/慢速/不同口音
