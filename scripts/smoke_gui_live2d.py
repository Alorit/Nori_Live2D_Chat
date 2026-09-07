# -*- coding: utf-8 -*-
"""GUI Live2D 模式冒烟：设置页模型下拉框可用，关闭窗口即完全退出。"""
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

app = QApplication(sys.argv)
w = ChatWindow(load_config(), quit_on_close=True, live2d_mode=True)
w.show()
w.set_live2d_models([{"path": "Nori/ariu.model3.json", "name": "Nori/ariu"}],
                    "Nori/ariu.model3.json")
assert w.model_combo.currentData() == "Nori/ariu.model3.json"
assert not w.model_combo.isHidden()
# 右上角 × 即完全退出：close() 应发出 quit_requested 信号
got = []
w.quit_requested.connect(lambda: got.append(True))
w.close()
assert got and got[0]
print("live2d settings page OK")
QTimer.singleShot(300, app.quit)
app.exec()
