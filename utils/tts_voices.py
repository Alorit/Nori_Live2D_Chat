"""TTS 语音包管理：导入 / 切换 / 导出 / 配置应用。

语音包目录约定（每个子目录一个语音包）：
    data/voices/<voice_name>/
        ref_audio.wav 或任意 .wav      # GPT-SoVITS 参考音频（必填）
        s1.ckpt                        # GPT-SoVITS SoVITS 权重（可选）
        s2.pth                         # GPT-SoVITS 生成器权重（可选）
        prompt.txt                     # 参考音频对应文本（可选）
        meta.json                      # { "prompt_text": "...", "prompt_lang": "zh" }
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from pathlib import Path

logger = logging.getLogger("utils.tts_voices")

VOICES_DIR_NAME = "data/voices"
SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def voices_dir(root: Path) -> Path:
    return root / VOICES_DIR_NAME


def safe_voice_name(name: str) -> str:
    name = (name or "").strip().replace("..", "_")
    name = SAFE_NAME_RE.sub("_", name).strip("_")
    return name or "voice"


def list_voices(root: Path) -> list[dict]:
    """扫描 data/voices 下的语音包目录，返回 [{name, path, ref_audio, has_s1, has_s2}]。"""
    d = voices_dir(root)
    out = []
    if not d.exists():
        return out
    for p in sorted(d.iterdir()):
        if not p.is_dir():
            continue
        ref = _find_ref_audio(p)
        if not ref:
            continue
        out.append({
            "name": p.name,
            "path": str(p),
            "ref_audio": str(ref),
            "has_s1": any(p.glob("*.ckpt")),
            "has_s2": any(p.glob("*.pth")),
        })
    return out


def _find_ref_audio(voice_path: Path) -> Path | None:
    for name in ("ref_audio.wav", "nori_ref.wav", "ref.wav"):
        p = voice_path / name
        if p.is_file():
            return p
    wavs = sorted(voice_path.glob("*.wav"))
    return wavs[0] if wavs else None


def import_voice(root: Path, source: str | Path) -> str | None:
    """导入语音包（文件夹或 zip），返回语音包名称；失败返回 None。"""
    src = Path(source)
    if not src.exists():
        return None
    d = voices_dir(root)
    d.mkdir(parents=True, exist_ok=True)

    if src.is_file() and src.suffix.lower() == ".zip":
        tmp_name = safe_voice_name(src.stem)
        dest = d / tmp_name
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(src) as zf:
                for member in zf.namelist():
                    # 防止 zip slip
                    target = (dest / member).resolve()
                    if not target.is_relative_to(dest.resolve()):
                        continue
                    zf.extract(member, dest)
        except Exception as e:
            logger.warning("解压语音包失败：%s", e)
            shutil.rmtree(dest, ignore_errors=True)
            return None
        # 如果 zip 里只有一个子目录，把它提升为语音包根目录
        subdirs = [x for x in dest.iterdir() if x.is_dir()]
        if len(subdirs) == 1 and not _find_ref_audio(dest):
            inner = subdirs[0]
            for item in inner.iterdir():
                shutil.move(str(item), dest / item.name)
            shutil.rmtree(inner, ignore_errors=True)
        if not _find_ref_audio(dest):
            shutil.rmtree(dest, ignore_errors=True)
            return None
        return dest.name

    if src.is_dir():
        name = safe_voice_name(src.name)
        dest = d / name
        dest.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            if item.is_dir():
                shutil.copytree(item, dest / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest / item.name)
        if not _find_ref_audio(dest):
            shutil.rmtree(dest, ignore_errors=True)
            return None
        return dest.name

    return None


def export_voice(root: Path, name: str, dest_dir: str | Path) -> Path | None:
    """把指定语音包复制到目标目录，返回目标路径。"""
    src = voices_dir(root) / safe_voice_name(name)
    if not src.is_dir() or not _find_ref_audio(src):
        return None
    dest = Path(dest_dir) / src.name
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            shutil.copytree(item, dest / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest / item.name)
    return dest


def prompt_text_for(voice_path: Path) -> str:
    """读取语音包的参考文本（prompt.txt 或 meta.json）。"""
    p = voice_path / "prompt.txt"
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    m = voice_path / "meta.json"
    if m.is_file():
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
            return str(data.get("prompt_text", "") or "").strip()
        except Exception:
            pass
    return ""


def prompt_lang_for(voice_path: Path) -> str:
    """读取语音包的参考语言（meta.json 的 prompt_lang，可选）。"""
    m = voice_path / "meta.json"
    if m.is_file():
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
            lang = str(data.get("prompt_lang", "") or "").strip()
            if lang:
                return lang
        except Exception:
            pass
    return ""


def voice_pack_weights(voice_path: Path) -> tuple[Path | None, Path | None]:
    """返回语音包的 (SoVITS 权重 *.ckpt, GPT 权重 *.pth)。"""
    s1 = next(iter(sorted(voice_path.glob("*.ckpt"))), None) if voice_path.is_dir() else None
    s2 = next(iter(sorted(voice_path.glob("*.pth"))), None) if voice_path.is_dir() else None
    return s1, s2


def apply_voice_to_config(cfg, name: str) -> dict:
    """把语音包应用到当前配置：保存 overrides，并更新 GPT-SoVITS 推理 yaml。"""
    voice_path = voices_dir(cfg.root) / safe_voice_name(name)
    ref = _find_ref_audio(voice_path)
    if not ref:
        raise ValueError(f"语音包不存在或缺少参考音频：{name}")

    # 语音包没带参考文本时，保留配置里已有的值：
    # prompt_text 为空会让 GPT-SoVITS 退回“无参考文本”模式，音色与韵律明显劣化。
    current = cfg.tts.get("gpt_sovits", {})
    current = current if isinstance(current, dict) else {}
    prompt_text = (prompt_text_for(voice_path)
                   or str(current.get("prompt_text", "") or "").strip())
    prompt_lang = (prompt_lang_for(voice_path)
                   or str(current.get("prompt_lang", "") or "").strip() or "zh")
    gpt_cfg = {
        "ref_audio_path": str(ref),
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
    }
    cfg.set_runtime("tts", "gpt_sovits", gpt_cfg)
    cfg.save_overrides({"tts": {"gpt_sovits": gpt_cfg}})

    s1, s2 = voice_pack_weights(voice_path)
    runtime_dir = str(cfg.tts.get("gpt_sovits", {}).get("runtime_dir", "") or "")
    updated_yaml = None
    if runtime_dir and s1 and s2:
        updated_yaml = update_gpt_sovits_yaml(runtime_dir, voice_path, s1, s2)

    return {
        "name": voice_path.name,
        "ref_audio": str(ref),
        "prompt_text": prompt_text,
        "s1": str(s1) if s1 else "",
        "s2": str(s2) if s2 else "",
        "updated_yaml": updated_yaml,
    }


def update_gpt_sovits_yaml(runtime_dir: str | Path, voice_path: Path,
                           s1: Path, s2: Path) -> Path | None:
    """更新 GPT-SoVITS tts_infer.yaml 的 custom/v2/v2Pro 权重路径。"""
    runtime = Path(runtime_dir)
    yaml_path = runtime / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
    if not yaml_path.is_file():
        return None
    try:
        text = yaml_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读取 tts_infer.yaml 失败：%s", e)
        return None

    s1_str = str(s1.resolve()).replace("\\", "/")
    s2_str = str(s2.resolve()).replace("\\", "/")
    lines = text.splitlines(keepends=True)
    current_section = ""
    changed = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if re.match(r"^[A-Za-z0-9_]+:\s*$", stripped):
            current_section = stripped.split(":", 1)[0].strip()
            continue
        if current_section not in ("custom", "v2", "v2Pro"):
            continue
        if stripped.startswith("t2s_weights_path:"):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = f"{indent}t2s_weights_path: {s1_str}\n"
            changed = True
        elif stripped.startswith("vits_weights_path:"):
            indent = line[:len(line) - len(line.lstrip())]
            lines[i] = f"{indent}vits_weights_path: {s2_str}\n"
            changed = True

    if not changed:
        return None
    try:
        yaml_path.write_text("".join(lines), encoding="utf-8")
        logger.info("已更新 GPT-SoVITS 权重路径：%s", yaml_path)
        return yaml_path
    except Exception as e:
        logger.warning("写入 tts_infer.yaml 失败：%s", e)
        return None
