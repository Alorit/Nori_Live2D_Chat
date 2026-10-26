"""统一控制台的日志收集：把 data/logs/*.log 的最新内容合并展示。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

SOURCES = {
    "agent": "agent.log",
    "heart": "heart.log",
    "gpt_sovits": "gpt_sovits.log",
    # 桌宠进程的 stdout/stderr 由 agent/live2d_native.py 重定向到这个文件；
    # 之前指向 live2d_mcp.log（旧 MCP 应用留下的产物），等于永远看不到内容。
    "live2d": "live2d_native.log",
    "train": "nori_train.log",
}


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= 0:
        return []
    # 只读文件末尾，避免大文件全量加载
    with open(path, "rb") as f:
        f.seek(max(0, size - min(size, 1_000_000)))
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-max_lines:]


def _ts_prefix(line: str):
    """解析行首时间戳，失败返回 None。"""
    try:
        if len(line) < 19:
            return None
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def collect_logs(root: Path, source: str = "全部", max_lines: int = 500,
                 filter_text: str = "", level: str = "全部") -> str:
    root = Path(root)  # 允许直接传项目根目录字符串
    logs_dir = root / "data" / "logs"
    names = list(SOURCES.items()) if source == "全部" else \
        [(source, SOURCES.get(source, ""))]

    entries: list[tuple[datetime, str, str]] = []
    for key, filename in names:
        if not filename:
            continue
        path = logs_dir / filename
        lines = _tail_lines(path, max_lines)
        parsed = 0
        for line in lines:
            ts = _ts_prefix(line)
            if filter_text and filter_text.lower() not in line.lower():
                continue
            if level != "全部":
                if f"[{level}]" not in line and f" {level} " not in line:
                    continue
            if ts:
                entries.append((ts, key, line))
                parsed += 1
            else:
                entries.append((None, key, line))
        if source == "全部" and not entries and lines:
            # 文件存在但没有任何可解析/匹配内容，给出占位提示
            entries.append((None, key, f"[{key}] 没有匹配的日志"))

    out: list[str] = []
    if source == "全部":
        entries.sort(key=lambda e: (e[0] or datetime.min, e[1]))
    else:
        entries.sort(key=lambda e: (e[0] or datetime.min, e[2]))
    for ts, key, line in entries:
        out.append(f"[{key}] {line}" if source == "全部" else line)
    return "\n".join(out) if out else "（暂无日志）"
