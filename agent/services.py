"""Nori 后台服务管理：Heart 与 GPT-SoVITS API 的无窗口启停。

GUI 控制台页面通过它管理子进程，run.bat 不再为每个服务单独开 cmd 窗口。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

from utils.tts_voices import update_gpt_sovits_yaml, voice_pack_weights, voices_dir

logger = logging.getLogger("agent.services")


def gsv_expected_to_start(cfg) -> bool:
    """GPT-SoVITS 是否“稍后会就绪”（已配置自动启动，且 runtime 与参考音频都在）。

    冷启动阶段返回 True：此时应当排队等 Nori 音色，而不是先用系统音色念出来。
    """
    g = cfg.tts.get("gpt_sovits", {})
    g = g if isinstance(g, dict) else {}
    if not bool(g.get("auto_start", True)):
        return False
    runtime = str(g.get("runtime_dir", "") or "").strip()
    ref = str(g.get("ref_audio_path", "") or "").strip()
    if not runtime or not ref or not Path(ref).is_file():
        return False
    rt = Path(runtime)
    if not rt.is_absolute():
        rt = cfg.root / rt
    has_python = ((rt / "runtime" / "pythonw.exe").exists()
                  or (rt / "runtime" / "python.exe").exists())
    return (rt / "api_v2.py").exists() and has_python


def _creationflags():
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return 0


def _pythonw(root: Path) -> str | None:
    candidates = [
        root / ".venv" / "Scripts" / "pythonw.exe",
        root / ".venv" / "Scripts" / "python.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                capture_output=True, text=True, timeout=5,
                creationflags=_creationflags()).stdout or ""
            # 没有匹配进程时 tasklist 输出不含该 PID
            return str(int(pid)) in out
        except Exception:
            pass
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _windows_command_line(pid: int) -> str:
    """用 CIM 查询进程命令行（用于验证 pid 文件确实指向 heart.py）。"""
    try:
        script = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}' "
            "-ErrorAction SilentlyContinue; if($p){$p.CommandLine}"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=8, creationflags=_creationflags())
        return r.stdout or ""
    except Exception:
        return ""


def _find_pids_by_command(substring: str) -> list[int]:
    """按命令行关键字查找 PID（用于清理脱离 pid 文件的孤儿进程）。"""
    try:
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*"
            + substring +
            "*' } | ForEach-Object { $_.ProcessId }"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=12, creationflags=_creationflags())
        return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]
    except Exception:
        return []


def _pid_is_gsv(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    cmdline = _windows_command_line(pid)
    return "gpt_sovits_service.py" in cmdline


def _pid_is_heart(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    cmdline = _windows_command_line(pid)
    return "heart.py" in cmdline


def _kill_process(pid: int, verified: bool = False) -> bool:
    """结束一个 PID（Windows 下连同子进程树）。

    verified=False 时仍直接结束，调用方需保证 PID 是受控子进程；
    从磁盘读取的 PID 必须经过验证，避免误杀无关进程。
    """
    if not _pid_alive(pid):
        return True
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_creationflags(), timeout=15)
            for _ in range(30):
                if not _pid_alive(pid):
                    return True
                time.sleep(0.1)
            return False
        else:
            os.kill(int(pid), 9)
            return True
    except Exception as e:
        logger.warning("结束进程 %s 失败：%s", pid, e)
        return False


class ServiceManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.root = cfg.root
        self.logs_dir = cfg.data_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.heart_proc: subprocess.Popen | None = None
        self.gsv_proc: subprocess.Popen | None = None
        self.gsv_external = False

    # ---------------------------------------------------------- heart ----
    @property
    def heart_pid_file(self) -> Path:
        return self.cfg.data_dir / "heart.pid"

    def heart_is_running(self) -> bool:
        if self.heart_proc and self.heart_proc.poll() is None:
            return True
        try:
            pid = int(self.heart_pid_file.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            return False
        if pid and _pid_is_heart(pid):
            return True
        # pid 文件过期或指向别的进程：清理，避免误判/误杀
        if pid:
            try:
                self.heart_pid_file.unlink(missing_ok=True)
            except Exception:
                pass
        return False

    def start_heart(self, skip_live2d: bool = False) -> bool:
        if self.heart_is_running():
            logger.info("Heart 已在运行，跳过启动")
            return True
        pyw = _pythonw(self.root)
        if not pyw:
            logger.error("找不到 pythonw.exe，无法无窗口启动 Heart")
            return False
        env = None
        if skip_live2d:
            env = dict(os.environ)
            env["NORI_HEART_SKIP_LIVE2D"] = "1"
        try:
            self.heart_proc = subprocess.Popen(
                [pyw, str(self.root / "heart.py")],
                cwd=str(self.root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
                env=env,
            )
            logger.info("Heart 已启动（PID %s）", self.heart_proc.pid)
            return True
        except Exception as e:
            logger.warning("启动 Heart 失败：%s", e)
            return False

    def stop_heart(self) -> bool:
        if self.heart_proc and self.heart_proc.poll() is None:
            try:
                _kill_process(self.heart_proc.pid, verified=True)
            finally:
                self.heart_proc = None
        try:
            pid = int(self.heart_pid_file.read_text(encoding="utf-8").strip() or "0")
            if pid and _pid_is_heart(pid):
                _kill_process(pid, verified=True)
            if pid:
                try:
                    self.heart_pid_file.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
        # 兜底：pid 文件可能因启动器/子进程分离而丢失，按命令行再扫一遍
        for pid in _find_pids_by_command("heart.py"):
            if pid != (self.heart_proc.pid if self.heart_proc else -1):
                _kill_process(pid, verified=True)
        # 无论中间 taskkill 是否立刻返回成功，以最终结果为准
        for _ in range(30):
            if not self.heart_is_running():
                return True
            time.sleep(0.1)
        return False

    # ---------------------------------------------------------- gpt-sovits ----
    @property
    def gsv_pid_file(self) -> Path:
        return self.cfg.data_dir / "gpt_sovits.pid"

    def gsv_runtime_dir(self) -> Path | None:
        p = self.cfg.tts.get("gpt_sovits", {}).get("runtime_dir", "")
        if not p:
            return None
        path = Path(p)
        if not path.is_absolute():
            path = self.root / path
        return path if path.exists() else None

    def gsv_is_running(self) -> bool:
        if self.gsv_proc and self.gsv_proc.poll() is None:
            return True
        try:
            pid = int(self.gsv_pid_file.read_text(encoding="utf-8").strip() or "0")
            if pid and _pid_is_gsv(pid):
                return True
        except Exception:
            pass
        import requests
        try:
            r = requests.get("http://127.0.0.1:9880/docs", timeout=1.0)
            if r.status_code == 200:
                self.gsv_external = True
                return True
        except Exception:
            pass
        return False

    def _active_voice_pack(self) -> tuple[Path | None, Path | None, Path | None]:
        """当前语音包目录与其 (SoVITS 权重, GPT 权重)：优先配置的参考音频所在包。"""
        candidates: list[Path] = []
        g = self.cfg.tts.get("gpt_sovits", {})
        ref = str(g.get("ref_audio_path", "") or "") if isinstance(g, dict) else ""
        if ref:
            candidates.append(Path(ref).parent)
        vd = voices_dir(self.cfg.root)
        if vd.is_dir():
            candidates.extend(p for p in sorted(vd.iterdir()) if p.is_dir())
        for d in candidates:
            s1, s2 = voice_pack_weights(d)
            if s1 and s2:
                return d, s1, s2
        return None, None, None

    def repair_gsv_weights(self, rt: Path) -> None:
        """启动前自检 tts_infer.yaml 的权重路径，失效时用当前语音包自动修复。

        典型场景：项目目录改名 / 搬家后 yaml 里仍写着旧的绝对路径，
        GPT-SoVITS 会直接 FileNotFoundError 退出，表现为 TTS 永远「冷启动中」。
        """
        yaml_path = rt / "GPT_SoVITS" / "configs" / "tts_infer.yaml"
        if not yaml_path.is_file():
            return
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("读取 %s 失败：%s", yaml_path, e)
            return

        custom = data.get("custom") or {}
        paths = [str(custom.get("t2s_weights_path", "") or ""),
                 str(custom.get("vits_weights_path", "") or "")]

        def _exists(p: str) -> bool:
            if not p:
                return False
            path = Path(p.replace("\\", "/"))
            if not path.is_absolute():
                path = rt / path
            return path.is_file()

        if all(_exists(p) for p in paths):
            return
        voice_path, s1, s2 = self._active_voice_pack()
        if not (voice_path and s1 and s2):
            logger.warning("GPT-SoVITS 权重路径已失效，且找不到可用语音包：%s",
                           " / ".join(paths))
            return
        if update_gpt_sovits_yaml(rt, voice_path, s1, s2):
            logger.info("已自动修复 GPT-SoVITS 权重路径 → %s", voice_path)

    def start_gpt_sovits(self) -> bool:
        if self.gsv_is_running():
            logger.info("GPT-SoVITS API 已在运行（%s）",
                        "外部进程" if self.gsv_external else "本服务管理")
            return True
        rt = self.gsv_runtime_dir()
        if not rt:
            logger.warning("未找到 GPT-SoVITS runtime_dir，无法启动")
            return False
        try:
            self.repair_gsv_weights(rt)
        except Exception as e:
            logger.warning("自检 GPT-SoVITS 权重路径失败：%s", e)
        pyw = rt / "runtime" / "pythonw.exe"
        if not pyw.exists():
            logger.warning("找不到 %s", pyw)
            return False
        launcher = self.root / "scripts" / "gpt_sovits_service.py"
        host = "127.0.0.1"
        port = "9880"
        infer_cfg = "GPT_SoVITS/configs/tts_infer.yaml"
        log_path = self.logs_dir / "gpt_sovits.log"
        try:
            self.gsv_external = False
            self.gsv_proc = subprocess.Popen(
                [str(pyw), str(launcher), str(rt), host, port, infer_cfg,
                 str(log_path), str(self.gsv_pid_file)],
                cwd=str(rt),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_creationflags(),
            )
            logger.info("GPT-SoVITS API 已启动（PID %s）", self.gsv_proc.pid)
            return True
        except Exception as e:
            logger.warning("启动 GPT-SoVITS 失败：%s", e)
            return False

    def stop_gpt_sovits(self) -> bool:
        if self.gsv_external:
            self.gsv_external = False
            return False
        if self.gsv_proc and self.gsv_proc.poll() is None:
            _kill_process(self.gsv_proc.pid, verified=True)
            self.gsv_proc = None
        elif self.gsv_proc is not None:
            self.gsv_proc = None
        try:
            pid = int(self.gsv_pid_file.read_text(encoding="utf-8").strip() or "0")
            if pid and _pid_is_gsv(pid):
                _kill_process(pid, verified=True)
            if pid:
                try:
                    self.gsv_pid_file.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            pass
        # 兜底：按命令行查找可能脱离 pid 文件的孤儿服务进程
        for pid in _find_pids_by_command("gpt_sovits_service.py"):
            _kill_process(pid, verified=True)
        for _ in range(30):
            if not self.gsv_is_running():
                return True
            time.sleep(0.1)
        return False

    # ---------------------------------------------------------- 汇总 ----
    def status(self) -> dict[str, bool]:
        return {
            "heart": self.heart_is_running(),
            "gpt_sovits": self.gsv_is_running(),
        }
