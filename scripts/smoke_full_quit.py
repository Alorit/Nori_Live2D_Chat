# -*- coding: utf-8 -*-
"""完全退出集成测试：按钮路径应停掉 Heart/GPT-SoVITS 并退出。"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["NORI_HEART_SKIP_LIVE2D"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from agent.config import load_config
from main import AppController, setup_logging

cfg = load_config()
setup_logging(cfg.log_file)
app = QApplication(sys.argv)
ctrl = AppController(cfg, app, enable_pet=False, autostart_services=True)
time.sleep(4)
print("before:", ctrl.services.status())
assert ctrl.services.status()["heart"]

QTimer.singleShot(800, ctrl.on_quit_requested)
code = app.exec()
print("app exited", code)
print("after:", ctrl.services.status())
assert not ctrl.services.status()["heart"]
assert not ctrl.services.status()["gpt_sovits"]
print("full quit OK")
