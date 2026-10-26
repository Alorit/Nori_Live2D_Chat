"""Heart 进程 → GUI 的轻量事件通道（JSONL 追加写）。

为什么用文件而不是 socket / HTTP：
- heart 是独立子进程，GUI 关掉之后它还要继续自主运行，事件留在文件里不会丢；
- GUI 侧本来就有 2 秒一次的控制台刷新定时器，再加一个“只读文件尾”的成本几乎为零；
- 崩溃安全：追加写一行就是一条事件，半截行下次会被跳过，不会连带丢历史。

事件类型（kind）：
- ``thought``  内心 OS：{"text": "...", "mood": "..."} → GUI 显示为灰色斜体气泡
- ``speak``    自主说话：{"text": "..."} → GUI 显示为普通 AI 气泡（TTS 同时在播）
- ``motion``   做了动作：{"name": "nod", "source": "micro|plan|presence"}
- ``expr``     换了表情：{"name": "happy"}
- ``state``    状态变化：{"mood": "...", "valence": 0.2, "arousal": 0.5, "energy": 0.4}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# 文件超过这个大小就只保留最后 _KEEP_LINES 行后重写，避免无限增长
_MAX_BYTES = 512 * 1024
_KEEP_LINES = 400


def emit(path: str | os.PathLike, kind: str, **payload) -> bool:
    """追加一条事件。永远不抛异常（heart 主循环不能被日志通道拖死）。"""
    p = Path(path)
    rec: dict = {"ts": time.time(), "kind": str(kind)}
    for k, v in payload.items():
        if v is None or v == "":
            continue
        rec[k] = v
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > _MAX_BYTES:
            _truncate(p)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _truncate(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_KEEP_LINES:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        # 截断失败就让它继续长，下一次还会重试；不影响写入
        pass


def read_new(path: str | os.PathLike, offset: int = 0) -> tuple[list[dict], int]:
    """从 offset 开始读完整行，返回 (事件列表, 新 offset)。

    只消费以换行结尾的完整行：heart 正在写的那一行会留到下一次读。
    """
    p = Path(path)
    try:
        size = p.stat().st_size
    except (FileNotFoundError, OSError):
        return [], 0
    if size < offset:
        # 文件被截断或重建（比如换了事件文件），从头读
        offset = 0
    if size == offset:
        return [], offset
    try:
        with p.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return [], offset
    if not chunk:
        return [], offset
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        cut = text.rfind("\n")
        if cut < 0:
            return [], offset          # 半截行，下次再说
        text = text[: cut + 1]
    events: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
    return events, offset + len(text.encode("utf-8"))
