#!/usr/bin/env python
"""Agent Team Dashboard — 即時觀察團隊互動的 Terminal TUI

用法：
    # 在另一個 terminal 啟動 Dashboard
    uv run python tools/team_dashboard.py

    # 指定自訂 log 檔
    uv run python tools/team_dashboard.py path/to/team-chat.jsonl

快捷鍵：
    q — 退出
    c — 清除畫面
    s — 切換自動捲動
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, RichLog

# Agent 顏色映射
AGENT_COLORS: dict[str, str] = {
    "team-lead": "bright_white",
    "backend-dev": "dodger_blue1",
    "frontend-dev": "green3",
    "architect": "gold1",
    "market-analyst-1": "medium_orchid1",
    "market-analyst-2": "dark_turquoise",
    "code-writer": "bright_blue",
    "reviewer": "bright_red",
    "test-runner": "bright_cyan",
}

# 角色顯示名稱
AGENT_ICONS: dict[str, str] = {
    "team-lead": "👑",
    "backend-dev": "⚙️",
    "frontend-dev": "🎨",
    "architect": "🏗️",
    "market-analyst-1": "📊",
    "market-analyst-2": "💰",
    "code-writer": "✍️",
    "reviewer": "🔍",
    "test-runner": "🧪",
}

DEFAULT_LOG_FILE = Path(".claude/team-chat.jsonl")


class TeamDashboard(App):
    """Agent Team 即時 Dashboard"""

    CSS = """
    Screen {
        layout: horizontal;
    }

    #chat-panel {
        width: 62%;
        border: solid $accent;
        border-title-color: $accent;
        border-title-style: bold;
    }

    #summary-panel {
        width: 38%;
        border: solid $warning;
        border-title-color: $warning;
        border-title-style: bold;
    }
    """

    TITLE = "🤖 Agent Team Dashboard"

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("c", "clear_all", "清除"),
        Binding("s", "toggle_scroll", "自動捲動"),
    ]

    def __init__(self, log_file: Path = DEFAULT_LOG_FILE) -> None:
        super().__init__()
        self.log_file = log_file
        self.last_pos = 0
        self.msg_count = 0
        self.auto_scroll = True
        self.summaries: dict[str, list[str]] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        chat = RichLog(id="chat-panel", wrap=True, highlight=True, markup=True)
        chat.border_title = "💬 團隊討論"
        summary = RichLog(id="summary-panel", wrap=True, highlight=True, markup=True)
        summary.border_title = "📋 即時總結"
        yield chat
        yield summary
        yield Footer()

    def on_mount(self) -> None:
        """啟動時載入既有訊息並開始監聽"""
        chat = self.query_one("#chat-panel", RichLog)
        summary = self.query_one("#summary-panel", RichLog)

        # 歡迎訊息
        chat.write(
            "[bold bright_white]━━━ Agent Team Dashboard ━━━[/bold bright_white]"
        )
        chat.write(f"[dim]監聽檔案: {self.log_file.absolute()}[/dim]")
        chat.write("")

        summary.write("[bold bright_white]━━━ 等待報告 ━━━[/bold bright_white]")
        summary.write("[dim]長訊息和報告會自動歸類到這裡[/dim]")
        summary.write("")

        # 載入既有訊息
        self._load_existing()

        # 每 0.5 秒檢查新訊息
        self.set_interval(0.5, self._check_new_messages)

    def _load_existing(self) -> None:
        """載入 log 檔中已有的訊息"""
        if not self.log_file.exists():
            chat = self.query_one("#chat-panel", RichLog)
            chat.write("[dim italic]尚無訊息，等待團隊啟動...[/dim italic]")
            return

        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self._process_message(line)
            self.last_pos = f.tell()

    def _check_new_messages(self) -> None:
        """檢查是否有新訊息"""
        if not self.log_file.exists():
            return

        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                f.seek(self.last_pos)
                new_lines = f.readlines()
                self.last_pos = f.tell()
        except OSError:
            return

        for line in new_lines:
            line = line.strip()
            if line:
                self._process_message(line)

    def _process_message(self, line: str) -> None:
        """處理一條訊息"""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        chat = self.query_one("#chat-panel", RichLog)

        sender = msg.get("from", "unknown")
        target = msg.get("to", "all")
        content = msg.get("msg", "")
        msg_type = msg.get("type", "chat")
        ts = msg.get("ts", "")

        self.msg_count += 1

        # 解析時間
        try:
            time_str = datetime.fromisoformat(ts).strftime("%H:%M:%S")
        except (ValueError, TypeError):
            time_str = "??:??:??"

        sender_color = AGENT_COLORS.get(sender, "white")
        target_color = AGENT_COLORS.get(target, "white")
        sender_icon = AGENT_ICONS.get(sender, "💬")

        # Chat panel 標頭
        if target == "all":
            header = (
                f"[{sender_color} bold]{sender_icon} {sender}[/{sender_color} bold]"
                f" [dim]→ 全體[/dim]"
                f"  [dim]{time_str}[/dim]"
            )
        else:
            target_icon = AGENT_ICONS.get(target, "💬")
            header = (
                f"[{sender_color} bold]{sender_icon} {sender}[/{sender_color} bold]"
                f" [dim]→[/dim] [{target_color}]{target_icon} {target}[/{target_color}]"
                f"  [dim]{time_str}[/dim]"
            )

        # 訊息類型標記
        type_badge = ""
        if msg_type == "report":
            type_badge = " [bold red]📝 REPORT[/bold red]"
        elif msg_type == "summary":
            type_badge = " [bold green]📋 SUMMARY[/bold green]"
        elif msg_type == "status":
            type_badge = " [bold yellow]📡 STATUS[/bold yellow]"

        chat.write(f"{header}{type_badge}")

        # 訊息內容
        lines = content.strip().split("\n")
        max_lines = 30 if msg_type == "report" else 15
        for ln in lines[:max_lines]:
            # 保留 markdown 格式化
            if ln.strip().startswith("#"):
                chat.write(f"  [bold]{ln}[/bold]")
            elif ln.strip().startswith("- "):
                chat.write(f"  {ln}")
            elif ln.strip().startswith("|"):
                chat.write(f"  [dim]{ln}[/dim]")
            else:
                chat.write(f"  {ln}")

        if len(lines) > max_lines:
            chat.write(f"  [dim]... 還有 {len(lines) - max_lines} 行[/dim]")

        # 分隔線
        chat.write("[dim]─────────────────────────────────────[/dim]")

        # 更新 summary panel
        if msg_type in ("report", "summary") or len(content) > 300:
            self._update_summary(sender, content, msg_type)

        # 更新標題顯示訊息數
        chat.border_title = f"💬 團隊討論 ({self.msg_count} 則)"

    def _update_summary(self, sender: str, content: str, msg_type: str) -> None:
        """更新 summary panel"""
        lines = content.strip().split("\n")

        # 提取重點（markdown 標題、粗體、列表項目）
        key_points: list[str] = []
        for ln in lines:
            stripped = ln.strip()
            if (
                stripped.startswith("##")
                or stripped.startswith("**")
                or (stripped.startswith("- ") and len(stripped) > 5)
            ):
                key_points.append(stripped)
            if len(key_points) >= 8:
                break

        if key_points:
            self.summaries[sender] = key_points
            self._refresh_summary()

    def _refresh_summary(self) -> None:
        """重繪 summary panel"""
        panel = self.query_one("#summary-panel", RichLog)
        panel.clear()
        panel.write("[bold bright_white]━━━ 關鍵發現 ━━━[/bold bright_white]")
        panel.write("")

        for role, items in self.summaries.items():
            color = AGENT_COLORS.get(role, "white")
            icon = AGENT_ICONS.get(role, "💬")
            panel.write(f"[{color} bold]{icon} {role}[/{color} bold]")
            for item in items:
                # 縮排並格式化
                if item.startswith("##"):
                    panel.write(f"  [bold]{item}[/bold]")
                elif item.startswith("**"):
                    panel.write(f"  {item}")
                else:
                    panel.write(f"  {item}")
            panel.write("")

        panel.border_title = f"📋 即時總結 ({len(self.summaries)} 份報告)"

    def action_clear_all(self) -> None:
        """清除畫面"""
        self.query_one("#chat-panel", RichLog).clear()
        self.query_one("#summary-panel", RichLog).clear()
        self.summaries.clear()
        self.msg_count = 0

    def action_toggle_scroll(self) -> None:
        """切換自動捲動"""
        self.auto_scroll = not self.auto_scroll
        chat = self.query_one("#chat-panel", RichLog)
        chat.auto_scroll = self.auto_scroll
        status = "開" if self.auto_scroll else "關"
        self.notify(f"自動捲動: {status}")


def main() -> None:
    log_file = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG_FILE
    app = TeamDashboard(log_file=log_file)
    app.run()


if __name__ == "__main__":
    main()
