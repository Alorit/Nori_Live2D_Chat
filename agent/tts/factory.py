"""TTS 后端工厂：按可用性自动选择。

当前仅保留两个后端：
- gpt_sovits：GPT-SoVITS API（Nori 音色，主后端，由 GUI 自动静默拉起）
- system：Windows SAPI5（GPT-SoVITS 不可用时的最后兜底）

旧的 sherpa / piper / edge 后端已移除，备份见 D:/Nori_Backup/。
"""
from __future__ import annotations

import logging

from .base import TTSBackend
from .gpt_sovits_tts import GPTSoVITSTTS
from .system_tts import SystemTTS

logger = logging.getLogger("tts.factory")

_CLASSES = {
    "system": SystemTTS,
    "gpt_sovits": GPTSoVITSTTS,
}


def probe_backends(cfg) -> list[tuple[str, bool]]:
    """返回 [(backend_name, available), ...] 用于启动日志。"""
    out = []
    for name in _CLASSES:
        try:
            ok = _CLASSES[name](cfg).available()
        except Exception:
            ok = False
        out.append((name, ok))
    return out


def create_backend(name: str, cfg) -> TTSBackend:
    """按名字创建指定 TTS 后端实例（不检查可用性）。"""
    cls = _CLASSES.get(name)
    if cls is None:
        raise ValueError(f"未知 TTS 后端：{name}")
    return cls(cfg)


def create_tts(cfg) -> TTSBackend:
    """按配置选择可用的 TTS 后端。找不到可用后端时抛出 RuntimeError。"""
    order = cfg.tts.get("order", ["gpt_sovits", "system"])
    wanted = cfg.tts.get("backend", "auto")
    if wanted == "auto":
        candidates = order
    else:
        candidates = [wanted] + [x for x in order if x != wanted]

    errors = []
    for name in candidates:
        try:
            backend = create_backend(name, cfg)
            if backend.available():
                logger.info("TTS 后端选择：%s", name)
                return backend
            errors.append(f"{name}: 模型/依赖未就绪")
        except Exception as e:
            errors.append(f"{name}: {e}")

    raise RuntimeError(
        "没有可用的 TTS 后端。GPT-SoVITS 冷启动约需 1 分钟，就绪后会自动切换；"
        "也可以把 config.yaml 的 tts.backend 改为 system 使用 Windows 系统语音兜底。"
        "详情：" + "; ".join(errors))
