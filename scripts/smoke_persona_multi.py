# -*- coding: utf-8 -*-
"""多人格管理单元测试（临时目录，不碰真实 persona）。"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.config import Config
from agent import persona

tmp = Path(tempfile.mkdtemp())
cfg = Config({
    "persona": {"persona_dir": str(tmp / "persona"),
                "active_persona": "nori", "expressions": [], "motions": []},
}, root=tmp)

assert persona.list_personas(cfg) == ["nori"]
assert persona.load_persona_text(cfg) == persona.default_persona_text(cfg)

name = persona.create_persona(cfg, "高冷人格内容", "cool")
assert name == "cool"
assert persona.active_persona_name(cfg) == "cool"
assert persona.load_persona_text(cfg) == "高冷人格内容"
assert set(persona.list_personas(cfg)) == {"nori", "cool"}

name2, path = persona.save_persona_text(cfg, "高冷人格改", name="cool")
assert name2 == "cool" and Path(path).exists()

persona.set_active_persona(cfg, "nori")
assert persona.active_persona_name(cfg) == "nori"
assert persona.load_persona_text(cfg) == persona.default_persona_text(cfg)

# 新建实例读取持久化状态
cfg2 = Config({"persona": {"persona_dir": str(tmp / "persona"),
                           "active_persona": "nori"}}, root=tmp)
assert persona.active_persona_name(cfg2) == "nori"

assert persona.delete_persona(cfg2, "cool") == "nori"
try:
    persona.delete_persona(cfg2, "nori")
    raise AssertionError("should not delete last")
except ValueError:
    pass

print("persona multi OK")
