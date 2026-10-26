# -*- coding: utf-8 -*-
"""无 GUI 冒烟测试：persona + memory CRUD + services status/log util。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.config import Config
from agent.memory import MemoryStore
from agent.persona import load_persona_text, persona_path, save_persona_text, reset_persona_to_default
from utils.console_logs import collect_logs

# 1) persona：用临时 persona 文件，不碰真实 nori.md
tmp = Path(tempfile.mkdtemp())
cfg_data = {
    "persona": {"base": "默认人格内容", "persona_dir": str(tmp / "persona"),
                "active_persona": "test",
                "expressions": ["开心"], "motions": ["点头"], "control_rule": "{expressions}/{motions}"},
    "memory": {"backend": "bm25", "max_memories": 100, "top_k": 8},
}
cfg = Config(cfg_data, root=ROOT)
assert load_persona_text(cfg) == "默认人格内容", load_persona_text(cfg)
save_persona_text(cfg, "# 测试\n你是猫娘Nori")
assert load_persona_text(cfg).startswith("# 测试")
reset_persona_to_default(cfg)
assert load_persona_text(cfg) == "默认人格内容"
print("persona OK:", persona_path(cfg))

# 2) memory CRUD（临时 db）
db = tmp / "mem.db"
m = MemoryStore(str(db), cfg.memory)
mid = m.add_memory("用户喜欢草莓蛋糕", mem_type="semantic", importance=0.8, source="test")
assert mid
rows = m.list_memories(query="草莓")
assert rows and rows[0]["id"] == mid
assert m.update_memory(mid, content="用户喜欢抹茶蛋糕", importance=0.9)
r = m.get_memory(mid)
assert r["content"] == "用户喜欢抹茶蛋糕" and abs(r["importance"] - 0.9) < 1e-6
rid = m.add_rules(["不要剧透"], source="test")
rules = m.list_rules()
assert rules and rules[0]["id"] == rid and rules[0]["enabled"] == 1
assert m.set_rule_enabled(rid, False)
assert m.list_rules()[0]["enabled"] == 0
assert m.delete_memory(mid)
assert m.get_memory(mid) is None
assert m.delete_rule(rid)
m.close()
print("memory CRUD OK")

# 3) console logs 读取（真实日志目录，即使为空不报错）
text = collect_logs(ROOT, "全部", filter_text="", level="全部")
print("console_logs OK, chars =", len(text))
assert isinstance(text, str)
