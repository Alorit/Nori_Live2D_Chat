"""原生 Live2D 控制客户端（对接 Nori-Desktop-Pet 的 PetControlServer）。

直接通过本地 HTTP 控制 .NET Avalonia 原生 Live2D 桌宠。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("agent.live2d_native")

DEFAULT_PORT = 47835
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP_PATH = str(PROJECT_ROOT / "vendor" / "nori_desktop_pet" / "Nori.Desktop.exe")
DEFAULT_DOTNET_PATH = "dotnet"


class Live2DNativeError(RuntimeError):
    pass


class Live2DNativeClient:
    def __init__(self, cfg):
        m = cfg.live2d if hasattr(cfg, "live2d") else None
        self.base_url = "http://127.0.0.1:47835"
        self.app_path = str(
            (m.get("native_app_path") if m else "") or DEFAULT_APP_PATH
        )
        self.dotnet_path = str(
            (m.get("native_dotnet_path") if m else "") or DEFAULT_DOTNET_PATH
        )
        self._proc: subprocess.Popen | None = None
        self._log_file = None
        self._models = [
            {"path": "arg-nori", "name": "arg-nori"},
            {"path": "nori", "name": "nori"},
        ]

    # ------------------------------------------------------------------
    def _open_pet_log(self):
        """桌宠进程的 stdout/stderr 落到 data/logs/live2d_native.log。"""
        try:
            log_dir = PROJECT_ROOT / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            return open(log_dir / "live2d_native.log", "ab")
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None,
                 timeout: float = 5.0) -> Any:
        url = self.base_url + path
        try:
            if method == "GET":
                r = requests.get(url, timeout=timeout)
            else:
                r = requests.post(url, json=payload or {}, timeout=timeout)
            if r.status_code >= 400:
                raise Live2DNativeError(f"HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
        except requests.RequestException as e:
            raise Live2DNativeError(f"Live2D 控制服务请求失败：{e}") from e

    def available(self, timeout: float = 1.0) -> bool:
        try:
            self._request("GET", "/state", timeout=timeout)
            return True
        except Exception:
            return False

    def ensure_running(self, wait_sec: float = 30.0) -> bool:
        if self.available():
            return True
        if not Path(self.app_path).is_file():
            logger.warning("未找到原生 Live2D 应用：%s", self.app_path)
            return False
        try:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            if self.app_path.lower().endswith(".dll"):
                cmd = [self.dotnet_path, self.app_path, "--pet-only"]
            else:
                cmd = [self.app_path, "--pet-only"]
            # 桌宠是独立进程，之前的 Popen 没有接 stdout/stderr：
            # 启动失败或崩溃时 Python 侧什么都看不到，控制台「live2d」来源也永远是空的。
            self._log_file = self._open_pet_log()
            popen_kwargs: dict[str, Any] = {}
            if self._log_file is not None:
                popen_kwargs["stdout"] = self._log_file
                popen_kwargs["stderr"] = subprocess.STDOUT
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(Path(self.app_path).parent),
                creationflags=creationflags,
                **popen_kwargs,
            )
        except Exception as e:
            logger.warning("启动原生 Live2D 应用失败：%s", e)
            return False

        deadline = time.time() + wait_sec
        while time.time() < deadline:
            if self.available():
                logger.info("原生 Live2D 控制服务已就绪：%s", self.base_url)
                return True
            time.sleep(0.5)
        logger.warning("等待原生 Live2D 控制服务超时")
        return False

    # ------------------------------------------------------------------
    def get_state(self) -> dict:
        return self._request("GET", "/state")

    def play_motion(self, group: str, index: int | None = None,
                    priority: int | None = None) -> bool:
        if index is None:
            data = self._request("POST", "/motion", {"name": group})
        else:
            data = self._request("POST", "/motion", {"group": group, "index": int(index)})
        return bool(data.get("ok", False))

    def set_expression(self, expression: str) -> bool:
        if not expression:
            return False
        data = self._request("POST", "/expression", {"name": expression})
        return bool(data.get("ok", False))

    def switch_model(self, model_path: str) -> dict:
        model_id = model_path.split("/")[0] if "/" in model_path else model_path
        data = self._request("POST", "/model", {"modelId": model_id})
        return {"ok": bool(data.get("ok", False)), "modelId": data.get("modelId", model_id)}

    def list_models(self) -> dict:
        state = self.get_state()
        models = state.get("models") or self._models
        return {
            "models": models,
            "current": state.get("modelId", "arg-nori"),
        }

    def import_model(self, path: str) -> list[str]:
        """从本地文件夹或 ZIP 导入 Live2D 模型，返回规范化后的模型 ID 列表。"""
        data = self._request("POST", "/model/import", {"path": path})
        return list(data.get("models") or [])

    def set_speaking(self, speaking: bool) -> bool:
        """切换说话状态（口型由 audio_level 驱动）。"""
        try:
            self._request("POST", "/mouth", {"level": 0.0, "speaking": bool(speaking)})
            return True
        except Exception:
            return False

    def set_scale(self, scale: float) -> bool:
        scale = max(0.1, min(2.0, float(scale)))
        try:
            self._request("POST", "/scale", {"scale": scale})
            return True
        except Exception:
            return False

    def audio_level(self, level: float) -> bool:
        level = max(0.0, min(1.0, float(level)))
        try:
            self._request("POST", "/mouth", {"level": level, "speaking": level > 0.01})
            return True
        except Exception:
            return False

    def show_window(self) -> bool:
        if not self.ensure_running():
            return False
        try:
            self._request("POST", "/window", {"action": "show"})
            return True
        except Exception:
            return False

    def control_window(self, action: str) -> bool:
        action = (action or "").lower()
        if action not in {"show", "hide", "toggle"}:
            return False
        try:
            self._request("POST", "/window", {"action": action})
            return True
        except Exception:
            return False

    def look_at(self, x: float, y: float) -> bool:
        return True

    def set_parameter(self, param_id: str, value: float) -> bool:
        return True

    def reset(self) -> bool:
        return True

    def shutdown(self) -> bool:
        if self._proc and self._proc.poll() is None:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=15)
                else:
                    self._proc.terminate()
            except Exception as e:
                logger.warning("关闭原生 Live2D 进程失败：%s", e)
        self._proc = None
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        return not self.available(timeout=0.5)
