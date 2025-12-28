from src.dm.dialogue_manager import DialogueManager

dm = DialogueManager()
sid = "dev"
print("開始模擬點餐；輸入 exit 或 quit 離開。")

while True:
    t = input("User> ").strip()
    if t.lower() in ("exit", "quit"):
        break
    print("Bot >", dm.handle(sid, t))
