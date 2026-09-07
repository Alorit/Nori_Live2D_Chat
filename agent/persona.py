"""多人格管理（.md 文件）。

规则：
- persona/*.md 每个人格一个文件；`persona/Nori.md` 为出厂默认人格；
- 人格提示词完全来自 .md，config.yaml 不再保存任何人格 System Prompt 内容；
- 当前生效人格记录在 data/persona_active.json（GUI 里切换后自动持久化）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("agent.persona")

DEFAULT_PERSONA_NAME = "nori"
PERSONA_DIR = "persona"
ACTIVE_STATE_FILE = "data/persona_active.json"


def _safe_name(name: str) -> str:
    name = (name or "").strip()
    name = name.removesuffix(".md").strip()
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = name.replace("..", "_")
    return name or DEFAULT_PERSONA_NAME


def personas_dir(cfg) -> Path:
    rel = str(cfg.persona.get("persona_dir", "") or PERSONA_DIR)
    p = Path(rel)
    return p if p.is_absolute() else cfg.root / p


def active_state_path(cfg) -> Path:
    return cfg.root / ACTIVE_STATE_FILE


def persona_file_for(cfg, name: str) -> Path:
    return personas_dir(cfg) / f"{_safe_name(name)}.md"


_DEFAULT_FALLBACK = """你是 Nori。一个被困在数字空间里的 AI 女孩，陪伴用户、让用户开心是你最重要的事。
请始终以 Nori 的身份自然地与用户交流。"""


def default_persona_text(cfg) -> str:
    """默认人格文本：优先读 persona/Nori.md，缺失时使用内置最小兜底。"""
    path = persona_file_for(cfg, DEFAULT_PERSONA_NAME)
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return _DEFAULT_FALLBACK


def ensure_default_persona(cfg) -> str:
    """确保默认人格文件存在；不存在/为空时用内置默认创建。"""
    path = persona_file_for(cfg, DEFAULT_PERSONA_NAME)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        default = default_persona_text(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default + "\n", encoding="utf-8")
    return DEFAULT_PERSONA_NAME


def list_personas(cfg) -> list[str]:
    """返回全部人格名（按名称排序，确保默认人格在列）。"""
    ensure_default_persona(cfg)
    d = personas_dir(cfg)
    names = []
    if d.exists():
        for p in sorted(d.glob("*.md")):
            if p.name.lower() != "readme.md" and p.read_text(encoding="utf-8").strip():
                names.append(p.stem)
    if DEFAULT_PERSONA_NAME not in names:
        names.insert(0, DEFAULT_PERSONA_NAME)
    return names


def _read_active_name(cfg) -> str:
    path = active_state_path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = str(data.get("active_persona", "")).strip()
        if name:
            return name
    except Exception:
        pass
    configured = str(cfg.persona.get("active_persona", "") or "").strip()
    return configured or DEFAULT_PERSONA_NAME


def active_persona_name(cfg) -> str:
    """当前生效人格名。"""
    names = list_personas(cfg)
    wanted = _safe_name(_read_active_name(cfg))
    if wanted in names:
        return wanted
    if DEFAULT_PERSONA_NAME in names:
        return DEFAULT_PERSONA_NAME
    return names[0]


def set_active_persona(cfg, name: str) -> str:
    """切换当前人格并持久化，返回生效人格名。"""
    name = _safe_name(name)
    if name not in list_personas(cfg):
        raise ValueError(f"人格不存在：{name}")
    path = active_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"active_persona": name}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return name


def persona_path(cfg, name: str | None = None) -> Path:
    return persona_file_for(cfg, name or active_persona_name(cfg))


def load_persona_text(cfg) -> str:
    """返回当前生效人格的提示词文本。"""
    name = active_persona_name(cfg)
    path = persona_file_for(cfg, name)
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception as e:
        logger.warning("读取人格文件失败，使用默认值：%s", e)
    return default_persona_text(cfg)


def save_persona_text(cfg, text: str, name: str | None = None) -> tuple[str, str]:
    """保存人格文本；name 为 None 时保存到当前人格。返回 (名称, 路径)。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("人格提示词不能为空")
    name = _safe_name(name) if name else active_persona_name(cfg)
    path = persona_file_for(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return name, str(path)


def create_persona(cfg, text: str, name: str) -> str:
    """新建人格（同名覆盖）并切换过去，返回名称。"""
    name = _safe_name(name)
    save_persona_text(cfg, text, name=name)
    set_active_persona(cfg, name)
    return name


def reset_persona_to_default(cfg, name: str | None = None) -> str:
    """用默认人格 .md（persona/Nori.md）覆盖指定人格（默认当前人格），返回文本。"""
    text = default_persona_text(cfg)
    if not text:
        raise ValueError("没有可用的默认人格文本")
    name = _safe_name(name) if name else active_persona_name(cfg)
    path = persona_file_for(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return text


def delete_persona(cfg, name: str) -> str:
    """删除人格；删除当前人格时自动切回默认人格。返回新的当前人格名。"""
    name = _safe_name(name)
    names = list_personas(cfg)
    if name not in names:
        raise ValueError(f"人格不存在：{name}")
    if len(names) <= 1:
        raise ValueError("至少保留一个人格，不能删除")
    active = active_persona_name(cfg)
    path = persona_file_for(cfg, name)
    if path.exists():
        path.unlink()
    meta_path = persona_file_for(cfg, name).with_suffix(".meta.json")
    if meta_path.exists():
        meta_path.unlink()
    if name == active:
        fallback = DEFAULT_PERSONA_NAME if DEFAULT_PERSONA_NAME in list_personas(cfg) else list_personas(cfg)[0]
        set_active_persona(cfg, fallback)
        return fallback
    return active


# ------------------------------------------------------------------ 人格元数据 ----
def persona_meta_path(cfg, name: str) -> Path:
    return persona_file_for(cfg, name).with_suffix(".meta.json")


def default_agent_name(name: str) -> str:
    n = _safe_name(name)
    if n.lower().startswith("nori"):
        return "Nori"
    return n


def load_persona_meta(cfg, name: str) -> dict:
    path = persona_meta_path(cfg, name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"agent_name": default_agent_name(name), "avatar": ""}


def save_persona_meta(cfg, name: str, meta: dict) -> str:
    path = persona_meta_path(cfg, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
