"""Windows 原生标题栏暗色化工具。

把 Win10/11 的原生标题栏染成与界面一致的暗色，使其融入 GUI：
- Win11：直接设置标题栏底色（DWMWA_CAPTION_COLOR=35）与文字色（36）
- Win10：退回沉浸式暗色模式（DWMWA_USE_IMMERSIVE_DARK_MODE=20，旧版 19）
非 Windows 或调用失败时静默跳过，不影响功能。

用法（在窗口 showEvent 里首次调用即可）：
    apply_dark_title_bar(widget, "#060a18")
"""
from __future__ import annotations

import sys


def apply_dark_title_bar(widget, bg_hex: str = "#060a18",
                         text_hex: str = "#d7e3ff") -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        def _colorref(hex_str: str) -> int:
            h = (hex_str or "").lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return r | (g << 8) | (b << 16)

        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        caption = wintypes.COLORREF(_colorref(bg_hex))
        if dwm.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)) == 0:
            text = wintypes.COLORREF(_colorref(text_hex))
            dwm.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
            return
        for attr in (20, 19):
            on = wintypes.BOOL(1)
            if dwm.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except Exception:
        pass
