"""GPT-SoVITS 可选 TTS 后端（需先启动它的 API 服务）。

启动方式见 scripts/start_gpt_sovits_api.bat。
API 默认：http://127.0.0.1:9880
"""
from __future__ import annotations

import logging
import os
import tempfile

import requests

from .base import TTSBackend
from utils.audio import play_wav

logger = logging.getLogger("tts.gpt_sovits")


class GPTSoVITSTTS(TTSBackend):
    name = "gpt_sovits"

    def __init__(self, cfg):
        g = cfg.tts.get("gpt_sovits", {})
        self.api_url = str(g.get("api_url", "http://127.0.0.1:9880")).rstrip("/") if isinstance(g, dict) else "http://127.0.0.1:9880"
        self.text_lang = str(g.get("text_lang", "auto")) if isinstance(g, dict) else "auto"
        self.ref_audio_path = str(g.get("ref_audio_path", "")) if isinstance(g, dict) else ""
        self.prompt_text = str(g.get("prompt_text", "")) if isinstance(g, dict) else ""
        self.prompt_lang = str(g.get("prompt_lang", "zh")) if isinstance(g, dict) else "zh"
        # 语速：优先 gpt_sovits.speed，未设置时回退到全局 tts.speed（语速滑块写这里）
        speed = g.get("speed") if isinstance(g, dict) else None
        if speed is None:
            speed = cfg.tts.get("speed", 1.0) if cfg is not None else 1.0
        self.speed_factor = float(speed or 1.0)
        self.timeout = 120

    def available(self) -> bool:
        if not self.ref_audio_path or not os.path.isfile(self.ref_audio_path):
            return False
        try:
            import socket
            from urllib.parse import urlparse
            u = urlparse(self.api_url)
            host = u.hostname or "127.0.0.1"
            port = u.port or 9880
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except Exception:
            return False

    def set_speed(self, speed: float):
        self.speed_factor = float(speed)

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if not os.path.isfile(self.ref_audio_path):
            raise RuntimeError(f"GPT-SoVITS 参考音频不存在：{self.ref_audio_path}")

        payload = {
            "text": text,
            "text_lang": self.text_lang,
            "ref_audio_path": self.ref_audio_path,
            "prompt_text": self.prompt_text,
            "prompt_lang": self.prompt_lang,
            "speed_factor": self.speed_factor,
            "streaming_mode": False,
        }
        r = requests.post(self.api_url + "/tts", json=payload, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"GPT-SoVITS 合成失败（HTTP {r.status_code}）：{r.text[:200]}")

        fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="neuro_gsv_")
        os.close(fd)
        try:
            with open(wav_path, "wb") as f:
                f.write(r.content)
            play_wav(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
