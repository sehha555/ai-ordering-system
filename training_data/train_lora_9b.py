"""
Qwen3.5-9B QLoRA 微調腳本 — Tool Calling 點餐系統
使用 TRL SFTTrainer + PEFT QLoRA (4-bit NF4)，bf16 compute
RTX 5070 Ti 16GB VRAM 限制，必須用 4-bit 量化
"""
import json
import logging
import os
import sys
import time

import torch
from datasets import Dataset
from peft import LoraConfig, TaskType
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ========== 設定 ==========
MODEL_ID = "Qwen/Qwen3.5-9B"
DATA_PATH = os.path.join(os.path.dirname(__file__), "all_training_data.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "lora_output_9b")

# LoRA 參數（QLoRA 模式，rank 維持 32）
LORA_R = 32
LORA_ALPHA = 64
LORA_DROPOUT = 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]

# 訓練參數
NUM_EPOCHS = 1       # 4B 經驗：1 epoch 已收斂（loss 0.916→0.033）
BATCH_SIZE = 1
GRAD_ACCUM = 8       # effective batch = 8
LEARNING_RATE = 2e-4
MAX_SEQ_LENGTH = 1600
WARMUP_RATIO = 0.05
SEED = 42

# QLoRA 4-bit（9B bf16 需 ~17GB，超過 16GB VRAM）
USE_QLORA = True


def load_training_data(path: str) -> list[dict]:
    """載入 JSONL 訓練資料"""
    data = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line.strip())
            data.append(item)
    logger.info(f"載入 {len(data)} 筆訓練資料")
    return data


def format_for_training(examples: dict, tokenizer) -> dict:
    """將 OpenAI 格式 messages+tools 轉成模型原生 chat template"""
    texts = []
    for messages, tools in zip(examples["messages"], examples["tools"]):
        text = tokenizer.apply_chat_template(
            messages,
            tools=tools if tools else None,
            tokenize=False,
            add_generation_prompt=False,
        )
        texts.append(text)
    return {"text": texts}


def main():
    start_time = time.time()

    # 確認 CUDA
    if not torch.cuda.is_available():
        logger.error("CUDA 不可用，需要 GPU")
        sys.exit(1)

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
    logger.info(f"GPU: {gpu_name}, VRAM: {vram_gb:.1f} GB")

    # 1. 載入 tokenizer
    logger.info(f"[1/5] 載入 tokenizer: {MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. 載入模型（QLoRA 4-bit）
    logger.info(f"[2/5] 載入模型 (QLoRA 4-bit): {MODEL_ID}")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        trust_remote_code=True,
        quantization_config=bnb_config,
        device_map="auto",
        attn_implementation="sdpa",
    )
    model.config.use_cache = False  # 訓練時關閉 KV cache

    # 顯示 VRAM 使用
    allocated = torch.cuda.memory_allocated() / 1024**3
    logger.info(f"模型載入後 VRAM: {allocated:.1f} GB")

    # 3. 準備資料
    logger.info("[3/5] 準備訓練資料")
    raw_data = load_training_data(DATA_PATH)

    # 轉成 HuggingFace Dataset
    dataset = Dataset.from_list(raw_data)

    # 套用 chat template
    dataset = dataset.map(
        lambda examples: format_for_training(examples, tokenizer),
        batched=True,
        remove_columns=dataset.column_names,
        desc="格式化訓練資料",
    )

    # 不分 eval（16GB VRAM 限制，eval 會 OOM）
    train_dataset = dataset
    logger.info(f"訓練: {len(train_dataset)} 筆（無驗證集，避免 OOM）")

    # 4. 設定 LoRA + Trainer
    logger.info("[4/5] 設定 QLoRA 和 Trainer")
    lora_config = LoraConfig(
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=TARGET_MODULES,
        task_type=TaskType.CAUSAL_LM,
        bias="none",
    )

    # 計算步數
    effective_batch = BATCH_SIZE * GRAD_ACCUM
    steps_per_epoch = len(train_dataset) // effective_batch
    total_steps = steps_per_epoch * NUM_EPOCHS
    logging_steps = max(1, steps_per_epoch // 10)
    save_steps = max(1, steps_per_epoch // 2)

    logger.info(f"每 epoch {steps_per_epoch} 步, 共 {total_steps} 步")

    training_args = SFTConfig(
        output_dir=OUTPUT_DIR,
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        lr_scheduler_type="cosine",
        warmup_ratio=WARMUP_RATIO,
        bf16=True,
        logging_steps=logging_steps,
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=2,
        eval_strategy="no",          # 關閉 eval，省 VRAM
        max_length=MAX_SEQ_LENGTH,
        dataset_text_field="text",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_8bit",
        weight_decay=0.01,
        seed=SEED,
        report_to="none",
        remove_unused_columns=True,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    # 顯示可訓練參數
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    logger.info(f"可訓練參數: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    # 5. 開始訓練
    logger.info("[5/5] 開始訓練")
    allocated = torch.cuda.memory_allocated() / 1024**3
    logger.info(f"訓練前 VRAM: {allocated:.1f} GB")

    try:
        result = trainer.train()
        train_time = time.time() - start_time

        logger.info(f"訓練完成！耗時: {train_time / 60:.1f} 分鐘")
        logger.info(f"Final train loss: {result.metrics.get('train_loss', 'N/A')}")

        # 儲存 LoRA adapter
        logger.info(f"儲存 LoRA adapter 到 {OUTPUT_DIR}")
        trainer.save_model(OUTPUT_DIR)
        tokenizer.save_pretrained(OUTPUT_DIR)

        logger.info("完成！")

    except torch.cuda.OutOfMemoryError:
        logger.error("VRAM 不足！建議：")
        logger.error("1. 減少 LORA_R（32→16 或 8）")
        logger.error("2. 減少 MAX_SEQ_LENGTH（1600→1024）")
        logger.error("3. 減少 GRAD_ACCUM（8→4）")
        sys.exit(1)


if __name__ == "__main__":
    main()
