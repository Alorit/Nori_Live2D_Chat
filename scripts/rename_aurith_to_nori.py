# -*- coding: utf-8 -*-
"""全局重命名：Nori -> Nori（项目根目录、内部目录/文件、文本引用）。"""
import os
import re
import shutil
from pathlib import Path

ROOT = Path(r"D:\Nori_Live2D_Chat")
EXCLUDE_DIRS = {"node_modules", ".git", "dist", "__pycache__", "site-packages",
                ".venv", "logs"}
EXCLUDE_SUFFIXES = {".pyc", ".log", ".exe", ".dll", ".pyd", ".png", ".jpg", ".jpeg",
                    ".wav", ".mp3", ".db", ".onnx", ".pth", ".ckpt", ".raw", ".moc3",
                    ".zip", ".7z", ".bin"}
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".bat", ".cjs", ".ts",
                 ".html", ".css", ".js", ".txt", ".mjs", ".ps1", ".cfg", ".ini", ".mcp"}

replacements = [
    ("Nori_Live2D_Chat", "Nori_Live2D_Chat"),
    ("Nori", "Nori"),
    ("nori", "nori"),
]

changed = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
    for name in filenames:
        p = Path(dirpath) / name
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        new = text
        for old, neww in replacements:
            new = new.replace(old, neww)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(str(p))

print("changed files:", len(changed))
for c in changed[:80]:
    print(c)
