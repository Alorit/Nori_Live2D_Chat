# -*- coding: utf-8 -*-
"""GUI 冒烟测试（offscreen）：验证新页签与填充方法不崩。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from agent.config import load_config
from gui.chat_window import ChatWindow

cfg = load_config()
app = QApplication(sys.argv)
w = ChatWindow(cfg, quit_on_close=True, live2d_mode=False)
w.show()
w.set_persona("你是Nori。", str(ROOT / "persona" / "nori.md"))
w.set_memories([
    {"id": 1, "type": "semantic", "content": "用户喜欢草莓蛋糕", "importance": 0.8,
     "access_count": 2, "ts": 1786819000},
    {"id": 2, "type": "episodic", "content": "昨天一起看了电影", "importance": 0.5,
     "access_count": 0, "ts": 1786818000},
])
w.set_rules([
    {"id": 1, "rule": "不要剧透", "enabled": 1, "ts": 1786819000, "source": "test"},
    {"id": 2, "rule": "少用感叹号", "enabled": 0, "ts": 1786818000, "source": "test"},
])
w.set_service_status("heart", True)
w.set_service_status("gpt_sovits", False)
w.append_user("测试用户消息")
w.append_assistant("测试 Nori 回复")
w.set_live2d_models([
    {"path": "Nori/ariu.model3.json", "name": "Nori/ariu"},
    {"path": "Miku/miku.model3.json", "name": "Miku/miku"},
], "Nori/ariu.model3.json")
w._refresh_console()
w.append_system("冒烟测试 OK")
print("tabs:", [w.tabs.tabText(i) for i in range(w.tabs.count())])
print("console chars:", len(w.console_view.toPlainText()))
print("memory rows:", w.memory_table.rowCount(), "rules:", w.rules_list.count())
print("bubbles:", w.bubble_layout.count() - 1)
assert w.bubble_layout.count() - 1 == 2, "应有 2 个聊天气泡"
QTimer.singleShot(800, app.quit)
code = app.exec()
print("app exited", code)
sys.exit(code)
