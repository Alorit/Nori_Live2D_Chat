"""下载 Live2D 网页渲染所需的本地 JS 库到 live2d/js/。

用法：
    python scripts/download_live2d_js.py

下载内容：
    - pixi.min.js（PIXI v6，渲染引擎）
    - live2dcubismcore.min.js（Live2D Cubism 核心，官方 CDN）
    - pixi-live2d-display.min.js（Cubism 4 支持）

之后把 Cubism 3/4 模型文件夹放到 live2d/models/ 下，并在 config.yaml 里填
live2d.model_path，例如：live2d/models/Nori/model3.json
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "live2d" / "js"

FILES = {
    "qwebchannel.js": [
        "https://raw.githubusercontent.com/qt/qtwebchannel/6.5/examples/webchannel/shared/qwebchannel.js",
        "https://raw.githubusercontent.com/qt/qtwebchannel/dev/examples/webchannel/shared/qwebchannel.js",
    ],
    "pixi.min.js": [
        "https://cdn.jsdelivr.net/npm/pixi.js@6.5.10/dist/browser/pixi.min.js",
        "https://unpkg.com/pixi.js@6.5.10/dist/browser/pixi.min.js",
    ],
    "live2dcubismcore.min.js": [
        "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
    ],
    "pixi-live2d-display.min.js": [
        "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
        "https://unpkg.com/pixi-live2d-display@0.4.0/dist/cubism4.min.js",
    ],
}


def _get(url: str, timeout=120):
    import urllib3
    try:
        return requests.get(url, stream=True, timeout=timeout)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, stream=True, timeout=timeout, verify=False)


def main():
    JS_DIR.mkdir(parents=True, exist_ok=True)
    ok_all = True
    for fname, urls in FILES.items():
        dest = JS_DIR / fname
        if dest.exists() and dest.stat().st_size > 10_000:
            print(f"[跳过] {fname} 已存在")
            continue
        done = False
        for url in urls:
            print(f"[下载] {url}")
            try:
                resp = _get(url)
                if resp.status_code == 200:
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=1 << 16):
                            f.write(chunk)
                    print(f"[完成] {fname}（{dest.stat().st_size} 字节）")
                    done = True
                    break
                else:
                    print(f"[失败] HTTP {resp.status_code}")
            except Exception as e:
                print(f"[失败] {e}")
        if not done:
            print(f"[错误] {fname} 下载失败", file=sys.stderr)
            ok_all = False

    if ok_all:
        print("\nJS 库就绪。请把你的 Live2D 模型放到 live2d/models/ 下。")
    else:
        print("\n部分文件下载失败，请检查网络后重试。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
