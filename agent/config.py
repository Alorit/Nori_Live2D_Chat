"""配置加载与解析。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _resolve_path(base: Path, value: str) -> str:
    """把相对路径转成基于项目根目录的绝对路径（原样保留空字符串）。"""
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str(base / p)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base（返回 base）。"""
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    """薄封装：提供属性访问的配置对象。"""

    def __init__(self, data: dict[str, Any], root: Path = PROJECT_ROOT,
                 config_path: Path | None = None):
        self.data = data
        self.root = root
        self.config_path = Path(config_path) if config_path else (root / "config.yaml")
        self.overrides_path = root / "data" / "settings_overrides.json"
        self.llm = _DictObj(data.get("llm", {}))
        self.vision = _DictObj(data.get("vision", {}))
        self.search = _DictObj(data.get("search", {}))
        self.persona = _DictObj(data.get("persona", {}))
        self.live2d = _DictObj(data.get("live2d", {}))
        self.tts = _DictObj(data.get("tts", {}))
        self.memory = _DictObj(data.get("memory", {}))
        self.gui = _DictObj(data.get("gui", {}))
        self.heart = _DictObj(data.get("heart", {}))
        self.advanced = _DictObj(data.get("advanced", {}))

        # 常用路径解析成绝对路径
        self.live2d_model_path = _resolve_path(root, self.live2d.get("model_path", ""))
        self.data_dir = root / "data"
        self.db_path = str(self.data_dir / "memory.db")
        self.log_file = _resolve_path(root, self.advanced.get("log_file", "data/agent.log"))

    @property
    def working_memory_size(self) -> int:
        return int(self.llm.get("working_memory_size", 30))

    @property
    def api_key(self) -> str:
        key = self.llm.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")
        key = str(key).strip()
        if not key:
            provider = str(self.llm.get("provider", "") or "").lower()
            base = str(self.llm.get("base_url", "") or "").lower()
            if provider == "ollama" or "localhost" in base or "127.0.0.1" in base:
                return "ollama"
        return key

    @property
    def model(self) -> str:
        return str(self.llm.get("model", "deepseek-chat"))

    @property
    def base_url(self) -> str:
        return str(self.llm.get("base_url", "https://api.deepseek.com"))

    @property
    def is_local_llm(self) -> bool:
        """是否使用本地 Ollama / localhost 模型，用于降低上下文与后台负载。"""
        provider = str(self.llm.get("provider", "") or "").lower()
        base = str(self.llm.get("base_url", "") or "").lower()
        return provider == "ollama" or "localhost" in base or "127.0.0.1" in base

    @property
    def temperature(self) -> float:
        return float(self.llm.get("temperature", 1.0))

    @property
    def max_tokens(self) -> int:
        return int(self.llm.get("max_tokens", 300))

    # ------------------------------------------------------------------
    def set_runtime(self, section: str, key: str, value: Any) -> None:
        """运行时修改配置（不落盘）。"""
        if section not in self.data:
            self.data[section] = {}
        if isinstance(value, dict):
            self.data[section].setdefault(key, {}).update(value)
        else:
            self.data[section][key] = value
        # 同步 _DictObj
        self.__dict__[section] = _DictObj(self.data[section])

    def save_overrides(self, overrides: dict[str, Any]) -> str:
        """把面板改动保存到 data/settings_overrides.json（与已有覆盖合并，不丢其它设置）。"""
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)
        merged: dict[str, Any] = {}
        if self.overrides_path.exists():
            try:
                merged = json.loads(self.overrides_path.read_text(encoding="utf-8"))
            except Exception:
                merged = {}
        _deep_merge(merged, overrides)
        self.overrides_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(self.overrides_path)


class _DictObj:
    """允许用 .attr 访问 dict，也保留 [] 访问。"""

    def __init__(self, data: Any):
        if isinstance(data, dict):
            self._data = data
        else:
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        v = self._data.get(item)
        if isinstance(v, dict):
            return _DictObj(v)
        return v

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def as_dict(self) -> dict:
        return self._data


def load_config(path: str | os.PathLike | None = None) -> Config:
    """加载 config.yaml。相对路径优先按项目根目录解析。"""
    if path:
        cfg_path = Path(path)
        if not cfg_path.is_absolute():
            cfg_path = PROJECT_ROOT / cfg_path
    else:
        cfg_path = DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 面板保存的快速设置优先于 config.yaml（用户手改 YAML 仍为主）
    overrides_path = cfg_path.parent / "data" / "settings_overrides.json"
    if overrides_path.exists():
        try:
            overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
            _deep_merge(data, overrides)
        except Exception:
            pass

    return Config(data, root=cfg_path.parent, config_path=cfg_path)
