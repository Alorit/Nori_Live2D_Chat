# -*- coding: utf-8 -*-
"""历史按人格隔离测试。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.memory import MemoryStore

db = Path(tempfile.mkdtemp()) / "mem.db"
m = MemoryStore(str(db), {"backend": "bm25"})
m.record_message("user", "主人你好", persona="nori")
m.record_message("assistant", "喵，主人", persona="nori")
m.record_message("user", "Nori 你好", persona="Nori")
m.record_message("assistant", "我在数字空间里等你", persona="Nori")

assert [x["content"] for x in m.get_recent_messages(10, persona="Nori")] == [
    "Nori 你好", "我在数字空间里等你"]
assert len(m.get_recent_messages(10, persona="nori")) == 2
print("history isolation OK")
m.close()
