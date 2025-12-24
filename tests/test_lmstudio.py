import os
import time
from openai import OpenAI
from dotenv import load_dotenv

def test_lm_studio_connection():
    """
    Tests the connection to the LM Studio local LLM service and gets a response.
    """
    try:
        # --- 1. 設定與環境變數載入 ---
        load_dotenv()
        base_url = os.getenv("LM_STUDIO_BASE_URL")
        
        if not base_url:
            print("❌ 錯誤: .env 檔案中找不到 LM_STUDIO_BASE_URL。")
            print("請確認 .env 檔案存在,且包含 'LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1'")
            return

        # --- 2. 初始化 OpenAI 用戶端 ---
        # LM Studio 不需要 API 金鑰,但 openai SDK 需要一個值,可以是任何字串。
        client = OpenAI(base_url=base_url, api_key="lm-studio")
        
        # --- 3. 發送測試訊息 ---
        test_message = "你好,我想點一份飯糰"
        history = [
            {"role": "system", "content": "你是一個點餐系統,請使用繁體中文回答。"},
            {"role": "user", "content": test_message},
        ]
        
        print("🚀 正在連接到 LM Studio...")
        print(f"Given: LM Studio 在 {base_url} 運行")
        print(f"When:  發送測試訊息「{test_message}」")
        print("-" * 40)

        start_time = time.time()

        completion = client.chat.completions.create(
            model="local-model", # 對於本地模型,此名稱可為任意值
            messages=history,
            temperature=0.7,
        )

        end_time = time.time()
        
        # --- 4. 處理並顯示回應 ---
        response_message = completion.choices[0].message.content
        response_time = end_time - start_time
        
        history.append({"role": "assistant", "content": response_message})

        print("Then:  應收到繁體中文回應")
        print("-" * 40)
        print("🖥️  終端顯示完整對話:")
        for message in history:
            role_display = "使用者" if message['role'] == 'user' else '小幫手' if message['role'] == 'assistant' else '系統'
            print(f"  [{role_display}]: {message['content']}")
        print("-" * 40)
        
        print(f"⏱️  回應時間: {response_time:.2f} 秒")
        
        if response_time <= 5:
            print("✅ 成功: 回應時間在 5 秒內。 সন")
        else:
            print("⚠️  注意: 回應時間超過 5 秒。 সন")

    except Exception as e:
        print(f"\n❌ 失敗: 連接或請求時發生錯誤。 সন")
        print(f"   請確認 LM Studio 正在 http://127.0.0.1:1234 運行,並且 Qwen2.5:7B 模型已完全載入。 সন")
        print(f"   錯誤詳細資訊: {e}")

if __name__ == "__main__":
    test_lm_studio_connection()
