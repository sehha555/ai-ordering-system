"""
合併 LoRA adapter 到 base model，儲存為 HF 格式
後續再用 llama.cpp convert_hf_to_gguf.py 轉 GGUF
"""
import os
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen3.5-4B"
ADAPTER_PATH = os.path.join(os.path.dirname(__file__), "lora_output", "checkpoint-120")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "merged_model")


def main():
    print("=" * 60)
    print("LoRA Merge: 合併 adapter 到 base model")
    print("=" * 60)

    # 用 CPU 合併，省 VRAM
    print(f"\n[1/4] 載入 base model (CPU): {BASE_MODEL}")
    start = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    print(f"  完成 ({time.time() - start:.0f}s)")

    print(f"\n[2/4] 載入 LoRA adapter: {ADAPTER_PATH}")
    start = time.time()
    model = PeftModel.from_pretrained(model, ADAPTER_PATH)
    print(f"  完成 ({time.time() - start:.0f}s)")

    print("\n[3/4] 合併 LoRA 權重...")
    start = time.time()
    model = model.merge_and_unload()
    print(f"  完成 ({time.time() - start:.0f}s)")

    print(f"\n[4/4] 儲存合併模型到: {OUTPUT_PATH}")
    start = time.time()
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    model.save_pretrained(OUTPUT_PATH, safe_serialization=True)

    # 儲存 tokenizer
    tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH, trust_remote_code=True)
    tokenizer.save_pretrained(OUTPUT_PATH)
    print(f"  完成 ({time.time() - start:.0f}s)")

    # 確認檔案
    total_size = sum(
        os.path.getsize(os.path.join(OUTPUT_PATH, f))
        for f in os.listdir(OUTPUT_PATH)
        if f.endswith((".safetensors", ".json", ".jinja"))
    )
    print(f"\n合併模型大小: {total_size / 1024**3:.2f} GB")
    print("下一步: 用 llama.cpp convert_hf_to_gguf.py 轉 GGUF")
    print("=" * 60)


if __name__ == "__main__":
    main()
