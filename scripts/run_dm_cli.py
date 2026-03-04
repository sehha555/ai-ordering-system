from src.dm.dialogue_manager import DialogueManager

def main():
    dm = DialogueManager()
    session_id = "dev"
    print("DM CLI 測試（輸入 exit 離開）")
    while True:
        text = input("客人：").strip()
        if text.lower() in ("exit", "quit"):
            break
        reply = dm.handle(session_id, text)
        print("助手：" + reply)

if __name__ == "__main__":
    main()
