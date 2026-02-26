#!/usr/bin/env python
"""Agent Team 討論板 — 寫入 + 讀取訊息

寫訊息：
    uv run python ~/.claude/tools/team_log.py write --from backend-dev --to architect --msg "SSE 確認正確"
    uv run python ~/.claude/tools/team_log.py write --from architect --to all --type report --msg "架構評價 B+..."

讀訊息（讀取發給自己的新訊息）：
    uv run python ~/.claude/tools/team_log.py read --me architect
    uv run python ~/.claude/tools/team_log.py read --me architect --since 5

讀全部（不過濾）：
    uv run python ~/.claude/tools/team_log.py read --all

清空討論板：
    uv run python ~/.claude/tools/team_log.py clear
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

LOG_FILE = Path(".claude/team-chat.jsonl")


def write_message(sender: str, target: str, content: str, msg_type: str = "chat") -> None:
    """寫入一條訊息到討論板"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "from": sender,
        "to": target,
        "msg": content,
        "type": msg_type,
    }

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[OK] [{sender} → {target}] 已寫入討論板")


def read_messages(me: str | None = None, read_all: bool = False, since_minutes: int = 0) -> None:
    """從討論板讀取訊息"""
    if not LOG_FILE.exists():
        print("討論板是空的，還沒有任何訊息。")
        return

    cutoff = None
    if since_minutes > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

    messages = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 時間過濾
            if cutoff:
                try:
                    msg_time = datetime.fromisoformat(msg["ts"])
                    if msg_time < cutoff:
                        continue
                except (ValueError, KeyError):
                    pass

            # 收件人過濾
            if me and not read_all:
                target = msg.get("to", "")
                if target != me and target != "all":
                    continue

            messages.append(msg)

    if not messages:
        if me:
            print(f"沒有發給 {me} 的新訊息。")
        else:
            print("沒有新訊息。")
        return

    # 格式化輸出
    print(f"--- 共 {len(messages)} 則訊息 ---\n")
    for msg in messages:
        ts = msg.get("ts", "")
        try:
            time_str = datetime.fromisoformat(ts).strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = "??:??:??"

        sender = msg.get("from", "?")
        target = msg.get("to", "?")
        content = msg.get("msg", "")
        msg_type = msg.get("type", "chat")

        type_badge = ""
        if msg_type == "report":
            type_badge = " [REPORT]"
        elif msg_type == "summary":
            type_badge = " [SUMMARY]"

        print(f"[{time_str}] {sender} → {target}{type_badge}")
        print(f"  {content}")
        print()


def clear_board() -> None:
    """清空討論板"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")
    print("[OK] 討論板已清空")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Team 討論板")
    subparsers = parser.add_subparsers(dest="command", help="指令")

    # write 子指令
    write_parser = subparsers.add_parser("write", help="寫入訊息")
    write_parser.add_argument("--from", dest="sender", required=True, help="發送者")
    write_parser.add_argument("--to", required=True, help="接收者（或 'all'）")
    write_parser.add_argument("--msg", default=None, help="訊息內容（省略從 stdin）")
    write_parser.add_argument(
        "--type", default="chat",
        choices=["chat", "report", "summary", "status"],
        help="訊息類型",
    )

    # read 子指令
    read_parser = subparsers.add_parser("read", help="讀取訊息")
    read_parser.add_argument("--me", default=None, help="只顯示發給我的訊息")
    read_parser.add_argument("--all", dest="read_all", action="store_true", help="顯示全部訊息")
    read_parser.add_argument("--since", type=int, default=0, help="只顯示最近 N 分鐘的訊息")

    # clear 子指令
    subparsers.add_parser("clear", help="清空討論板")

    args = parser.parse_args()

    if args.command == "write":
        content = args.msg
        if content is None:
            content = sys.stdin.read().strip()
        if not content:
            print("錯誤：沒有訊息內容", file=sys.stderr)
            sys.exit(1)
        write_message(args.sender, args.to, content, args.type)

    elif args.command == "read":
        read_messages(me=args.me, read_all=args.read_all, since_minutes=args.since)

    elif args.command == "clear":
        clear_board()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
