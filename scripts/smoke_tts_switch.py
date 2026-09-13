# -*- coding: utf-8 -*-
"""TTS 自动切换测试：GPT-SoVITS 就绪后，controller 应切到 Nori 音色。"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from PySide6.QtWidgets import QApplication

from agent.config import load_config
from main import AppController, setup_logging

cfg = load_config()
setup_logging(cfg.log_file)
app = QApplication(sys.argv)
ctrl = AppController(cfg, app, enable_pet=False, autostart_services=False)
print("initial tts:", ctrl.tts_name)

assert ctrl.services.start_gpt_sovits()
for i in range(180):
    try:
        if requests.get("http://127.0.0.1:9880/docs", timeout=1).status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
print("gsv ready after ~", i + 1, "s")

ctrl._check_preferred_tts()
# 探测在后台线程里跑，结果通过信号回到主线程：必须让事件循环转起来才会生效
for _ in range(60):
    app.processEvents()
    if ctrl.tts_name == "gpt_sovits":
        break
    time.sleep(0.25)
print("tts after probe:", ctrl.tts_name)
assert ctrl.tts_name == "gpt_sovits"
print("stop:", ctrl.services.stop_gpt_sovits())
