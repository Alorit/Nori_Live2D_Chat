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


def candidate_names(cfg, allow_fallback: bool = True) -> list[str]:
    """按配置算出后端尝试顺序。

    allow_fallback=False 时只用首选后端（冷启动阶段用：宁可在提示文案里排队等
    GPT-SoVITS 就绪，也不要先用系统音色把话念出来）。
    """
    order = [str(x) for x in (cfg.tts.get("order", ["gpt_sovits", "system"]) or [])]
    wanted = str(cfg.tts.get("backend", "auto") or "auto")
    if wanted == "auto":
        chain = order or ["gpt_sovits"]
    else:
        chain = [wanted] + [x for x in order if x != wanted]
    if not allow_fallback:
        return chain[:1]
    candidates = list(chain)
    # 兜底后端：config.yaml 的 order 只写了主后端时也保证 SAPI5 能救场
    # （tts.allow_system_fallback: false 可显式关闭）
    if bool(cfg.tts.get("allow_system_fallback", True)):
        if SystemTTS.name not in candidates:
            candidates.append(SystemTTS.name)
    return candidates


def create_tts(cfg, allow_fallback: bool = True) -> TTSBackend:
    """按配置选择可用的 TTS 后端。找不到可用后端时抛出 RuntimeError。"""
    candidates = candidate_names(cfg, allow_fallback=allow_fallback)

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
        "已尝试：" + "、".join(candidates) + "。详情：" + "; ".join(errors))
