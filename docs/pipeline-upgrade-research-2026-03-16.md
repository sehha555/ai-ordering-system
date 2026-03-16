# Pipeline 升級調查報告（2026-03-16）

## 架構判斷：Cascaded 仍是正確選擇

所有商用點餐系統（SoundHound 10,000+ 門市、McDonald's、VOICEplug）都用 **streaming cascaded pipeline**。End-to-end speech-to-speech（Moshi、Qwen-Omni）在 2026 年仍不支援可靠的 multi-turn tool calling。不換架構，優化現有 pipeline。

## 延遲分析

| 階段 | 現在 | 優化後目標 | 怎麼達到 |
|------|------|-----------|---------|
| Turn detection | 1500ms silence | 300-500ms | SmartTurn v3 語意端點偵測 |
| ASR | 170ms | 50-80ms | SenseVoice 已夠快 |
| LLM TTFT | 300-500ms | 150-250ms | Qwen3 8B + warm cache |
| LLM→TTS | 等完整句 | 逐 token 送 | 已做（streaming-with-tools） |
| TTS | 300-800ms (Edge, cloud) | 100-150ms (local) | CosyVoice 3 或 Qwen3-TTS |
| **端對端** | **2-4s** | **500-900ms** | — |

**最大的單一改善：把 TTS 從 cloud 換成 local（省 300-800ms）。**

---

## ASR 調查

### 現用：SenseVoice-Small
- 234M 參數，~1-2GB VRAM
- CTC 非自回歸，RTF 0.007（3-5 秒音訊約 35ms）
- AISHELL-1 CER 2.96%
- 缺點：輸出簡體需 opencc + 修正表

### 首選升級：Breeze-ASR-25（MediaTek Research）
- 2B 參數，~4-5GB VRAM（faster-whisper FP16）
- 基於 Whisper-large-v2 微調，原生台灣華語
- CommonVoice zh-TW WER 7.97%（vs Whisper-large-v2 9.84%，-19%）
- 中英混語 CSZS WER 13.01%（vs 29.49%，**-55.88%**）
- **免 opencc、免修正表**
- 缺點：自回歸解碼，估計 150-400ms（需實測）
- 部署：`SoybeanMilk/faster-whisper-Breeze-ASR-25`（CTranslate2 FP16）

### 其他候選
| 模型 | 大小 | VRAM | 速度(5s) | 台灣華語 | 原生繁中 |
|---|---|---|---|---|---|
| SenseVoice-Small | 234M | ~1-2GB | **~35ms** | 一般 | ❌ |
| **Breeze-ASR-25** | 2B | ~4-5GB | ~150-400ms | SOTA | **✅** |
| Whisper-large-v3-turbo | 809M | ~2.5GB | ~120ms | 無特化 | ❌ |
| FireRedASR-AED-L | 1.1B | ~2-4GB | 未知 | AISHELL 0.55% | ❌ |
| Qwen3-ASR-1.7B | ~2B | ~4-6GB | ~200ms+ | CV-zhTW 3.77% | 未確認 |

### ASR 決策
- 短期：維持 SenseVoice（速度無敵）
- 中期：測試 Breeze-ASR-25（免 opencc + 混語 SOTA）
- 門檻：Breeze 3s 音訊延遲 < 400ms 且繁體輸出正確 → 替換

---

## LLM 調查

### 重要發現：Qwen3 8B vs Qwen3.5-9B

Qwen3.5-9B 是 Gated DeltaNet 混合架構（邊緣部署導向），Qwen3 8B 是標準 Transformer（tool calling RLHF 訓練）。**兩者不是線性升級關係。**

| | Qwen3.5-9B (現用) | Qwen3 8B | Qwen3 14B |
|---|---|---|---|
| 架構 | Gated DeltaNet 混合 | 標準 Transformer | 標準 Transformer |
| Tool calling | 93% (靠 priming) | **F1 0.933 (BFCL)** | **F1 0.971** |
| VRAM (Q4) | ~8GB | **~5-6GB** | ~10GB |
| 上下文 | 262K | 32K (YaRN 128K) | 32K |
| 速度 | 已知穩定 | 快 ~1.3x | 慢 ~1.5x |
| LM Studio | ✅ | ✅ | ✅ |

### 其他模型（不推薦）
- **Llama 4 Scout**：109B MoE，16GB 不可行
- **Mistral Small 3.2 24B**：Q4 ~14-15GB 太緊，中文弱
- **Gemma 3 12B**：BFCLv3 僅 16.3（Qwen3 系列 52+），LM Studio 有問題

### LLM 決策
- 優先測 Qwen3 8B：tool calling 原生強，可能不需 few-shot priming
- 若需更高精度：Qwen3 14B（F1 0.971），16GB 可跑 Q4
- 遷移風險低：同廠商、同 tool format（Qwen XML）

---

## TTS 調查

### 現用：Edge TTS
- 零 VRAM、免費、`zh-TW-HsiaoChenNeural` 台灣口音
- 缺點：cloud 延遲 300-800ms、無 SLA

### 首選升級：CosyVoice 3 (0.5B)
- 2-3GB VRAM，150ms 串流延遲
- 全雙向串流（text-in + audio-out 同時）
- 18+ 中文方言，Apache 2.0
- 缺點：非台灣口音（中性普通話），可用 voice cloning 補償

### 技術最強：Qwen3-TTS (0.6B)
- 3-4GB VRAM，**97ms** 串流延遲（RTX 4090）
- 自然語言聲音描述（"用老年男性的聲音"）
- 缺點：**License 待確認**

### 台灣口音最佳：BreezyVoice
- 3-4GB VRAM，MediaTek Research
- 唯一專為台灣華語訓練的 TTS
- 注音控制、多音字消歧
- 缺點：串流未確認，社群維護有限

### TTS 比較表
| 模型 | VRAM | 首音延遲 | 串流 | 台灣口音 | License |
|---|---|---|---|---|---|
| Edge TTS (現用) | 0 | 300-800ms | ✅ | 最佳 | 免費 |
| **CosyVoice 3** | 2-3GB | **150ms** | **全雙向** | 中性 | Apache 2.0 |
| **Qwen3-TTS** | 3-4GB | **97ms** | **全串流** | 中性 | 待確認 |
| BreezyVoice | 3-4GB | 300-600ms | 未確認 | **專為台灣** | Apache 2.0 |
| F5-TTS | 2-6GB | ~500ms | chunk only | 無 | CC-BY-NC ❌ |
| Fish Speech 1.5 | 4-6GB | 150ms | ✅ | 無 | CC-BY-NC-SA ❌ |
| Kokoro-82M | <2GB | 1-2s | chunked | 弱 | Apache 2.0 |

### TTS 決策
- CosyVoice 3 首選（成熟+串流+Apache 2.0+低 VRAM）
- Qwen3-TTS license 確認後可能更好
- BreezyVoice 可作為預生成固定語句（不需串流的場景）

---

## Pipeline 架構調查

### 商用點餐系統架構
- **SoundHound**（10,000+ 門市）：Polaris "speech-to-meaning" + text-based tool execution
- **McDonald's**（Google Cloud）：GPU edge 部署，<90ms inference
- **IBM**（已失敗）：通用 voice AI 無法處理 menu 複雜度
- **所有商用系統都用 cascaded pipeline + POS 整合**

### End-to-End 語音模型評估
| 模型 | 延遲 | VRAM | 中文 | Tool calling | 結論 |
|---|---|---|---|---|---|
| Moshi | 160ms | 24GB+ | ❌ 英文only | ❌ | 不可行 |
| GLM-4-Voice | — | ~8GB | ✅ | ❌ | 無 tool calling |
| Qwen2.5-Omni | 257ms | ~10GB(Q4) | ✅ | ✅(Thinker層) | 最可行但風險高 |
| Qwen3-Omni | — | 未知 | ✅ | ✅(串流only) | 觀察 |

**結論：E2E 模型不適合 2026 年的 tool calling 點餐系統。**

### 關鍵新發現

#### SmartTurn v3（Pipecat，語意端點偵測）
- 分析音訊波形判斷使用者是否真的說完（不是只看靜音）
- CPU 推理 12ms，支援 14 語言含中文
- 可把 endpointing 從 1500ms 降到 300-500ms
- **比換任何模型都省更多延遲**

#### Speculative Tool Calling + Filler
- Tool call 時先說「好的，幫你加上～」（filler 立即送 TTS）
- 同時並行執行 tool，使用者感知延遲 ~0ms
- 現有 early_tts 機制可強化

#### Pipecat 框架
- 最成熟的開源 voice AI 框架
- `pipecat-flows` 提供結構化對話狀態機（類似 checkout flow）
- SmartTurn v3 是一等公民組件
- 有 food ordering 範例（`pipecat-flows/examples/food_ordering.py`）
- 代價：需要重構為 frame-passing pipeline 模型
- **建議：選擇性採用（SmartTurn、speculative pattern），不全面遷移**

---

## VRAM 預算（RTX 5070 Ti 16GB）

| 組件 | 現在 | 優化後 |
|------|------|--------|
| ASR (SenseVoice) | 1-2GB | 1-2GB |
| LLM (Qwen3 8B Q4) | 8GB → | 5-6GB |
| TTS (CosyVoice 3) | 0 → | 2-3GB |
| System overhead | 1GB | 1GB |
| **合計** | ~10GB | ~10-12GB |
| **剩餘** | 6GB | 4-5GB |

---

## 執行優先順序

| 順序 | 改動 | 延遲改善 | 風險 | 工作量 |
|------|------|---------|------|--------|
| 1 | TTS → CosyVoice 3 (local) | -300~800ms | 低 | 2-3 天 |
| 2 | SmartTurn v3 端點偵測 | -500~1000ms | 低 | 1-2 天 |
| 3 | LLM → Qwen3 8B 測試 | tool calling ↑, VRAM ↓ | 中 | 2 天 |
| 4 | 強化 speculative filler | 感知延遲 ~0 | 低 | 1 天 |
| 5 | Breeze-ASR-25 測試 | 免 opencc, 混語 ↑ | 中 | 2-3 天 |
| 6 | Qwen3 14B 測試 | F1 0.971 | 中 | 2 天 |

**前 4 項做完，端對端 2-4s → 500-900ms，使用者感知接近即時。**

---

## 研究來源

### ASR
- [MediaTek-Research/Breeze-ASR-25 - HuggingFace](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)
- [faster-whisper-Breeze-ASR-25 - SoybeanMilk](https://huggingface.co/SoybeanMilk/faster-whisper-Breeze-ASR-25)
- [FunAudioLLM SenseVoice-Small](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)
- [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- [FireRedASR-AED-L](https://huggingface.co/FireRedTeam/FireRedASR-AED-L)

### LLM
- [Berkeley Function Calling Leaderboard (BFCL) V4](https://gorilla.cs.berkeley.edu/leaderboard.html)
- [Docker Local LLM Tool Calling Evaluation](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/)
- [Qwen3 Blog](https://qwenlm.github.io/blog/qwen3/)
- [Qwen3.5 Small Models - MarkTechPost](https://www.marktechpost.com/2026/03/02/alibaba-just-released-qwen-3-5-small-models/)

### TTS
- [BreezyVoice - MediaTek Research](https://huggingface.co/MediaTek-Research/BreezyVoice)
- [CosyVoice 3 - FunAudioLLM](https://github.com/FunAudioLLM/CosyVoice)
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- [F5-TTS](https://github.com/SWivid/F5-TTS)
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)

### Pipeline 架構
- [Toward Low-Latency End-to-End Voice Agents (arxiv 2508.04721)](https://arxiv.org/html/2508.04721v1)
- [Pipecat Framework](https://github.com/pipecat-ai/pipecat)
- [Pipecat SmartTurn v3](https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/)
- [SoundHound AI Platform for Restaurants](https://www.soundhound.com/newsroom/press-releases/soundhound-ai-unveils-next-generation-ai-platform-for-restaurants/)
- [Qwen2.5-Omni](https://github.com/QwenLM/Qwen2.5-Omni)
- [Hamming AI: Are S2S Models Ready?](https://hamming.ai/blog/are-speech-to-speech-models-ready-to-replace-cascade-models)
- [Speculative Tool Calling - GetStream](https://getstream.io/blog/speculative-tool-calling-voice/)
