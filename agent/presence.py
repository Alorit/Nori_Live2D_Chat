"""主人状态感知：鼠标键盘空闲时长 + 前台窗口。

设计约束：
- **零成本**：纯本地 Win32（GetLastInputInfo / GetForegroundWindow），不联网、不截图、不安装依赖；
- **只读**：不注入、不钩键盘；写进 LLM 提示词的内容默认只有「进程名」，不含窗口标题；
- **不崩**：所有系统调用都包在 try/except 里，失败就退化成「未知」，绝不拖垮 heart 主循环。

给自主性用它的两个地方：
1. ``PetDirector``：主人离开 → 她去睡；主人回来 → 醒来伸懒腰；
2. ``heart._think()``：把「主人现在在干什么、离开了多久」写进提示词，让她有话题。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time
from pathlib import Path

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 常见进程名 → 说得出口的中文（未命中的直接用进程名去掉扩展名）
_APP_LABELS = {
    "code.exe": "VS Code",
    "code - insiders.exe": "VS Code",
    "cursor.exe": "Cursor",
    "pycharm64.exe": "PyCharm",
    "idea64.exe": "IDEA",
    "devenv.exe": "Visual Studio",
    "chrome.exe": "浏览器",
    "msedge.exe": "浏览器",
    "firefox.exe": "浏览器",
    "weixin.exe": "微信",
    "wechat.exe": "微信",
    "qq.exe": "QQ",
    "dingtalk.exe": "钉钉",
    "feishu.exe": "飞书",
    "discord.exe": "Discord",
    "explorer.exe": "文件管理器",
    "windowsterminal.exe": "终端",
    "cmd.exe": "终端",
    "powershell.exe": "终端",
    "pwsh.exe": "终端",
    "potplayermini64.exe": "播放器",
    "mpv.exe": "播放器",
    "vlc.exe": "播放器",
    "steam.exe": "Steam",
    "steamwebhelper.exe": "Steam",
    "bilibili.exe": "B 站",
    "wps.exe": "WPS",
    "winword.exe": "Word",
    "excel.exe": "Excel",
}


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


class Presence:
    """采集主人状态。非 Windows 或调用失败时退化为「未知但不报错」。"""

    def __init__(self, cfg=None):
        auto = getattr(cfg, "autonomy", None) if cfg is not None else None
        try:
            self.use_title = bool(auto.get("use_window_title", False)) if auto else False
            self.away_sec = float(auto.get("away_sec", 300)) if auto else 300.0
            self.enabled = bool(auto.get("presence", True)) if auto else True
        except Exception:
            self.use_title, self.away_sec, self.enabled = False, 300.0, True
        self.is_windows = sys.platform == "win32"
        self._user32 = None
        self._kernel32 = None
        if self.is_windows and self.enabled:
            try:
                self._user32 = ctypes.WinDLL("user32", use_last_error=True)
                self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            except Exception:
                self._user32 = self._kernel32 = None

    # ------------------------------------------------------------------
    def idle_seconds(self) -> float | None:
        """全局空闲秒数（没有任何键鼠输入）。取不到返回 None。"""
        if not self._user32 or not self._kernel32:
            return None
        try:
            info = _LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(info)
            if not self._user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            now_tick = self._kernel32.GetTickCount() & 0xFFFFFFFF
            # GetLastInputInfo 用的是 32 位 tick，直接相减再取掩码就自动处理回绕
            elapsed = (now_tick - int(info.dwTime)) & 0xFFFFFFFF
            return elapsed / 1000.0
        except Exception:
            return None

    def foreground(self) -> tuple[str, str]:
        """返回 (进程名, 窗口标题)。取不到返回 ("", "")。"""
        if not self._user32:
            return "", ""
        try:
            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return "", ""
            title = ""
            try:
                n = int(self._user32.GetWindowTextLengthW(hwnd))
                if 0 < n <= 512:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    self._user32.GetWindowTextW(hwnd, buf, n + 1)
                    title = (buf.value or "").strip()
            except Exception:
                title = ""
            app = ""
            try:
                pid = wt.DWORD()
                self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                app = self._process_name(int(pid.value))
            except Exception:
                app = ""
            return app, title
        except Exception:
            return "", ""

    def _process_name(self, pid: int) -> str:
        if not pid or not self._kernel32:
            return ""
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            ok = self._kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            return Path(buf.value).name.lower()
        except Exception:
            return ""
        finally:
            try:
                self._kernel32.CloseHandle(handle)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """一次采样。永远返回 dict，字段缺失用默认值。"""
        now = time.time()
        snap: dict = {"ts": now, "idle_sec": None, "app": "", "title": "",
                      "away": False, "unknown": True}
        if not self.enabled:
            return snap
        idle = self.idle_seconds()
        app, title = self.foreground()
        if idle is not None or app:
            snap["unknown"] = False
        snap["idle_sec"] = idle
        snap["app"] = app
        snap["title"] = title if self.use_title else ""
        snap["away"] = bool(idle is not None and idle >= self.away_sec)
        return snap

    # ------------------------------------------------------------------
    @staticmethod
    def app_label(app: str) -> str:
        if not app:
            return ""
        base = app.lower()
        if base in _APP_LABELS:
            return _APP_LABELS[base]
        return Path(base).stem

    @classmethod
    def describe(cls, snap: dict | None) -> str:
        """把采样结果写成一句人话，供提示词与日志使用。"""
        if not snap or snap.get("unknown"):
            return "主人的状态未知。"
        idle = snap.get("idle_sec")
        app = cls.app_label(str(snap.get("app") or ""))
        if snap.get("away"):
            minutes = int((idle or 0) // 60)
            return f"主人已经离开 {minutes} 分钟以上（键盘鼠标都没有输入）。"
        parts = []
        if app:
            parts.append(f"主人在用 {app}")
        title = str(snap.get("title") or "").strip()
        if title:
            parts.append(f"窗口标题是「{title[:40]}」")
        if idle is not None:
            if idle < 60:
                parts.append("刚刚还有操作")
            else:
                parts.append(f"已经 {int(idle // 60)} 分钟没动键鼠")
        return "，".join(parts) + "。" if parts else "主人在电脑前。"


def sample(cfg=None) -> dict:
    """便捷函数：一次性采样（每次新建 Presence 会重复 WinDLL，正式循环里请复用实例）。"""
    try:
        return Presence(cfg).snapshot()
    except Exception:
        return {"ts": time.time(), "idle_sec": None, "app": "", "title": "",
                "away": False, "unknown": True}


if __name__ == "__main__":  # 手动体检：python -m agent.presence
    import json
    p = Presence()
    s = p.snapshot()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    print(Presence.describe(s))
    print("exe:", os.path.basename(sys.executable))
