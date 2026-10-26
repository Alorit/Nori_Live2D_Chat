# -*- coding: utf-8 -*-
"""启动加载界面冒烟测试。"""
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

from gui.splash import SplashWindow

app = QApplication(sys.argv)
s = SplashWindow()
s.show()
for i, text in [(10, "正在加载长期记忆…"), (45, "正在构建控制台界面…"),
                (80, "正在唤醒 Nori 心脏…"), (100, "Nori 已就绪")]:
    s.set_progress(i, text)
QTimer.singleShot(400, s.finish)
QTimer.singleShot(500, app.quit)
code = app.exec()
print("splash ok", code)
