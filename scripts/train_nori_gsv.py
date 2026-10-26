# -*- coding: utf-8 -*-
"""用捕获的 Nori 干净语音微调 GPT-SoVITS（v2Pro）。

流水线（等价于 webui 的一键三连 + 训练）：
  1. 汇总 data/inori_voice 里的干净片段 -> 切片
  2. FunASR 自动转写
  3. 1a 文本/BERT -> 1b CNHuBERT/SV -> 1c 语义 token
  4. 微调 SoVITS 与 GPT（小数据、少量 epoch，避免过拟合）
  5. 把训练好的权重复制到 D:\\Nori_Live2D_Chat\\data\\voices\\nori
  6. 更新 GPT_SoVITS/configs/tts_infer.yaml 使用 Nori 微调权重

日志：D:\\Nori_Live2D_Chat\\data\\logs\\nori_train.log
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent.config import load_config

cfg = load_config()
GSV_ROOT = Path(cfg.tts.get("gpt_sovits", {}).get("runtime_dir", "")).resolve()
PY = GSV_ROOT / "runtime" / "python.exe"
EXP_NAME = "nori"
EXP_DIR = GSV_ROOT / "logs" / EXP_NAME
LOG_PATH = PROJECT_ROOT / "data" / "logs" / "nori_train.log"
VOICE_OUT = PROJECT_ROOT / "data" / "voices" / "nori"

BERT_DIR = GSV_ROOT / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large"
CNHUBERT_DIR = GSV_ROOT / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base"
SV_PATH = GSV_ROOT / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt"
PRETRAINED_S2G = "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth"
PRETRAINED_S2D = "GPT_SoVITS/pretrained_models/v2Pro/s2Dv2Pro.pth"
PRETRAINED_S1 = "GPT_SoVITS/pretrained_models/s1v3.ckpt"


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, env_extra=None, timeout=3600):
    env = dict(os.environ)
    env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
    env["TEMP"] = str(GSV_ROOT / "TEMP")
    if env_extra:
        env.update(env_extra)
    log("RUN: " + " ".join(str(x) for x in cmd))
    proc = subprocess.run(cmd, cwd=str(GSV_ROOT), env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    tail = "\n".join((proc.stdout or "").splitlines()[-25:])
    log(tail)
    if proc.returncode != 0:
        raise RuntimeError(f"命令失败 code={proc.returncode}: {' '.join(map(str, cmd))}")


def prepare_dataset():
    log("== 1/6 准备 Nori 数据集 ==")
    if EXP_DIR.exists():
        shutil.rmtree(EXP_DIR, ignore_errors=True)
    wav_raw = EXP_DIR / "wavs"
    sliced = EXP_DIR / "sliced"
    wav_raw.mkdir(parents=True, exist_ok=True)
    sliced.mkdir(parents=True, exist_ok=True)

    srcs = sorted((PROJECT_ROOT / "data" / "inori_voice" / "samples").glob("*.wav"))
    srcs = [p for p in srcs if "_16k" not in p.name]
    for extra in ["nori_ref.wav", "nori_capture.wav", "nori_capture2.wav",
                  "nori_capture3.wav"]:
        p = PROJECT_ROOT / "data" / "inori_voice" / extra
        if p.exists():
            srcs.append(p)
    for i, p in enumerate(srcs):
        shutil.copy2(p, wav_raw / f"nori_{i:03d}_{p.name}")
    log(f"source wavs: {len(srcs)}")

    run([str(PY), "-s", "tools/slice_audio.py", str(wav_raw), str(sliced),
         "-34", "4000", "300", "10", "500", "0.9", "0.25", "0", "1"],
        timeout=1800)
    n_sliced = len(list(sliced.glob("*.wav")))
    log(f"sliced wavs: {n_sliced}")
    if n_sliced < 4:
        raise RuntimeError("切片结果太少，停止训练")

    asr_out = GSV_ROOT / "output"
    asr_out.mkdir(parents=True, exist_ok=True)
    run([str(PY), "-s", "tools/asr/funasr_asr.py", "-i", str(sliced),
         "-o", str(asr_out), "-s", "large", "-l", "zh", "-p", "float16"],
        timeout=3600)
    list_path = asr_out / f"{sliced.name}.list"
    if not list_path.exists():
        raise RuntimeError(f"ASR 输出缺失：{list_path}")
    n_lines = len(list_path.read_text(encoding="utf-8").strip().splitlines())
    log(f"ASR lines: {n_lines}")
    if n_lines < 4:
        raise RuntimeError("ASR 转写结果太少，停止训练")
    return str(list_path), str(sliced)


def preprocess(inp_text: str, inp_wav_dir: str):
    log("== 2/6 文本/BERT 特征（1a） ==")
    base_env = {
        "inp_text": inp_text,
        "inp_wav_dir": inp_wav_dir,
        "exp_name": EXP_NAME,
        "opt_dir": str(EXP_DIR),
        "bert_pretrained_dir": str(BERT_DIR),
        "cnhubert_base_dir": str(CNHUBERT_DIR),
        "sv_path": str(SV_PATH),
        "pretrained_s2G": PRETRAINED_S2G,
        "s2config_path": "GPT_SoVITS/configs/s2v2Pro.json",
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0",
        "is_half": "True",
        "version": "v2Pro",
    }
    run([str(PY), "-s", "GPT_SoVITS/prepare_datasets/1-get-text.py"],
        env_extra=base_env, timeout=3600)
    part = EXP_DIR / "2-name2text-0.txt"
    target = EXP_DIR / "2-name2text.txt"
    if not part.exists():
        raise RuntimeError(f"1a 输出缺失：{part}")
    shutil.move(str(part), str(target))

    log("== 3/6 CNHuBERT + 说话人向量（1b） ==")
    run([str(PY), "-s", "GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py"],
        env_extra=base_env, timeout=3600)
    run([str(PY), "-s", "GPT_SoVITS/prepare_datasets/2-get-sv.py"],
        env_extra=base_env, timeout=3600)

    log("== 4/6 语义 token（1c） ==")
    run([str(PY), "-s", "GPT_SoVITS/prepare_datasets/3-get-semantic.py"],
        env_extra=base_env, timeout=3600)
    part = EXP_DIR / "6-name2semantic-0.tsv"
    target = EXP_DIR / "6-name2semantic.tsv"
    if not part.exists():
        raise RuntimeError(f"1c 输出缺失：{part}")
    shutil.move(str(part), str(target))


def train_s2():
    log("== 5/6 微调 SoVITS（8 epochs） ==")
    (EXP_DIR / "logs_s2_v2Pro").mkdir(parents=True, exist_ok=True)
    with open(GSV_ROOT / "GPT_SoVITS" / "configs" / "s2v2Pro.json",
              "r", encoding="utf-8") as f:
        data = json.load(f)
    data["train"].update({
        "batch_size": 4,
        "epochs": 8,
        "text_low_lr_rate": 0.4,
        "pretrained_s2G": PRETRAINED_S2G,
        "pretrained_s2D": PRETRAINED_S2D,
        "if_save_latest": False,
        "if_save_every_weights": True,
        "save_every_epoch": 8,
        "gpu_numbers": "0",
        "grad_ckpt": False,
        "lora_rank": 32,
    })
    data["model"]["version"] = "v2Pro"
    data["data"]["exp_dir"] = data["s2_ckpt_dir"] = str(EXP_DIR)
    data["save_weight_dir"] = "SoVITS_weights_v2Pro"
    data["name"] = "nori_s2"
    data["version"] = "v2Pro"
    tmp_cfg = GSV_ROOT / "TEMP" / "tmp_s2_nori.json"
    tmp_cfg.write_text(json.dumps(data), encoding="utf-8")
    run([str(PY), "-s", "GPT_SoVITS/s2_train.py", "--config", str(tmp_cfg)],
        timeout=10800)


def train_s1():
    log("== 6/6 微调 GPT（8 epochs） ==")
    (EXP_DIR / "logs_s1").mkdir(parents=True, exist_ok=True)
    with open(GSV_ROOT / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml",
              "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["train"].update({
        "batch_size": 4,
        "epochs": 8,
        "save_every_n_epoch": 8,
        "if_save_every_weights": True,
        "if_save_latest": False,
        "if_dpo": False,
        "half_weights_save_dir": "GPT_weights_v2Pro",
        "exp_name": "nori_s1",
    })
    data["pretrained_s1"] = PRETRAINED_S1
    data["train_semantic_path"] = str(EXP_DIR / "6-name2semantic.tsv")
    data["train_phoneme_path"] = str(EXP_DIR / "2-name2text.txt")
    data["output_dir"] = str(EXP_DIR / "logs_s1_v2Pro")
    tmp_cfg = GSV_ROOT / "TEMP" / "tmp_s1_nori.yaml"
    tmp_cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    env = {"_CUDA_VISIBLE_DEVICES": "0", "hz": "25hz"}
    run([str(PY), "-s", "GPT_SoVITS/s1_train.py", "--config_file", str(tmp_cfg)],
        env_extra=env, timeout=10800)


def collect_weights():
    log("== 收集 Nori 微调权重 ==")
    s2_candidates = list((GSV_ROOT / "SoVITS_weights_v2Pro").glob("nori_s2*.pth"))
    s1_candidates = list((GSV_ROOT / "GPT_weights_v2Pro").glob("nori_s1*.ckpt"))
    if s2_candidates:
        s2_candidates.sort(key=lambda p: p.stat().st_mtime)
    if s1_candidates:
        s1_candidates.sort(key=lambda p: p.stat().st_mtime)
    log(f"s2 candidates: {[p.name for p in s2_candidates]}")
    log(f"s1 candidates: {[p.name for p in s1_candidates]}")
    if not s2_candidates or not s1_candidates:
        raise RuntimeError("未找到训练产物")
    VOICE_OUT.mkdir(parents=True, exist_ok=True)
    s2_path = VOICE_OUT / "nori_s2.pth"
    s1_path = VOICE_OUT / "nori_s1.ckpt"
    shutil.copy2(s2_candidates[-1], s2_path)
    shutil.copy2(s1_candidates[-1], s1_path)
    shutil.copy2(PROJECT_ROOT / "data" / "inori_voice" / "nori_ref.wav",
                 VOICE_OUT / "nori_ref.wav")
    return s2_path, s1_path


def update_infer_config(s2_path: Path, s1_path: Path):
    log("== 更新 tts_infer.yaml 使用 Nori 微调权重 ==")
    yaml_path = GSV_ROOT / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    for section in ("custom", "v2", "v2Pro"):
        if section in data:
            data[section]["device"] = "cuda"
            data[section]["is_half"] = True
            data[section]["version"] = "v2Pro"
            data[section]["t2s_weights_path"] = str(s1_path).replace("\\", "/")
            data[section]["vits_weights_path"] = str(s2_path).replace("\\", "/")
    yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    log(f"已更新 {yaml_path}")


def main():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log("=== Nori GPT-SoVITS 训练开始 ===")
    if not PY.exists():
        raise RuntimeError(f"GPT-SoVITS runtime 不存在：{PY}")
    inp_text, inp_wav_dir = prepare_dataset()
    preprocess(inp_text, inp_wav_dir)
    train_s2()
    train_s1()
    s2_path, s1_path = collect_weights()
    update_infer_config(s2_path, s1_path)
    log("=== 训练完成 ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"训练失败：{e}")
        raise
