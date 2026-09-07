"""Nori AI 桌面宠物 - 程序入口。

启动：
    python main.py              # 正常启动（原生 Live2D + 对话框）
    python main.py --no-pet     # 只启动对话框
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sys
import threading
from pathlib import Path

# 保证从项目根目录运行也能 import
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from agent.brain import Brain
from agent.config import load_config
from agent.core import AgentCore
from agent.live2d_native import Live2DNativeClient
from agent.memory import MemoryStore
from agent.mcp_manager import MCPManager
from agent.persona import (
    active_persona_name,
    create_persona,
    delete_persona,
    list_personas,
    load_persona_meta,
    load_persona_text,
    persona_path,
    reset_persona_to_default,
    save_persona_meta,
    save_persona_text,
    set_active_persona,
)
from agent.search import BaiduSearchClient
from agent.services import ServiceManager
from agent.tts.factory import create_backend, create_tts, probe_backends
from gui.chat_window import ChatWindow
from gui.first_run import FirstRunDialog
from gui.splash import SplashWindow
from utils.stickers import copy_to_chat_media
from utils.tts_voices import (
    apply_voice_to_config,
    export_voice,
    import_voice,
    list_voices,
)


def setup_logging(log_file: str):
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if sys.stdout is not None:  # pythonw 启动时没有 stdout
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------- 线程 ----
class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class SendWorker(QRunnable):
    def __init__(self, core: AgentCore, text: str,
                 image_paths: list[str] | None = None):
        super().__init__()
        self.core = core
        self.text = text
        self.image_paths = image_paths or []
        self.signals = WorkerSignals()

    def run(self):
        try:
            reply = self.core.handle_user_text(self.text, image_paths=self.image_paths)
            try:
                self.signals.result.emit(reply)
            except RuntimeError:
                pass  # 程序正在退出，丢弃信号
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class TTSWorker(QRunnable):
    def __init__(self, tts, text: str):
        super().__init__()
        self.tts = tts
        self.text = text
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.tts.speak(self.text)
            try:
                self.signals.result.emit("ok")
            except RuntimeError:
                pass  # 程序正在退出，丢弃信号
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class ServiceStatusWorker(QRunnable):
    """后台刷新 Heart / GPT-SoVITS 状态，避免在主线程执行 tasklist/HTTP。"""

    def __init__(self, services):
        super().__init__()
        self.services = services
        self.signals = WorkerSignals()

    def run(self):
        try:
            st = self.services.status()
            try:
                self.signals.result.emit(st)
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


class TTSPreferredWorker(QRunnable):
    """后台探测首选 TTS 后端是否就绪，避免在主线程 socket/HTTP 阻塞。"""

    def __init__(self, cfg, preferred: str):
        super().__init__()
        self.cfg = cfg
        self.preferred = preferred
        self.signals = WorkerSignals()

    def run(self):
        try:
            backend = create_backend(self.preferred, self.cfg)
            ok = backend.available()
            try:
                self.signals.result.emit((self.preferred, ok, backend if ok else None))
            except RuntimeError:
                pass
        except Exception as e:
            try:
                self.signals.error.emit(str(e))
            except RuntimeError:
                pass


# ---------------------------------------------------------------- 控制器 ----
class AppController(QObject):
    live2d_connection_done = Signal(bool, str)

    def __init__(self, cfg, app: QApplication, enable_pet: bool = True,
                 autostart_services: bool = True, progress=None):
        super().__init__()
        self.cfg = cfg
        self.app = app
        self.pool = QThreadPool.globalInstance()
        self.autostart_services = autostart_services
        self.enable_pet = enable_pet
        self._full_quit = False
        self._tts_pending: list[str] = []
        self._service_status_busy = False
        self._tts_probe_busy = False
        self._tts_busy = False
        self.current_conversation_id: int | None = None
        self._progress = progress or (lambda value, text: None)

        def _stage(value, text):
            try:
                self._progress(value, text)
            except Exception:
                pass

        _stage(8, "正在加载长期记忆…")
        # 记忆 / 大脑 / 视觉 / 搜索 / MCP-Skills
        self.memory = MemoryStore(cfg.db_path, cfg.memory)
        _stage(16, "正在连接大脑模型…")
        self.brain = Brain(cfg)
        _stage(24, "正在检查视觉 MCP…")
        _stage(30, "正在加载搜索模块…")
        self.search = BaiduSearchClient(cfg)
        self.mcp_manager = MCPManager(cfg.root)
        self.core = AgentCore(cfg, self.memory, self.brain,
                              search=self.search,
                              mcp_manager=self.mcp_manager)

        # 后台服务（Heart / GPT-SoVITS）统一管理，不再各开一个 cmd 窗口
        self.services = ServiceManager(cfg)

        # TTS（可用性探测）
        self.tts = None
        self.tts_name = "无"
        _stage(38, "正在加载 Nori 语音引擎…")
        try:
            self.tts = create_tts(cfg)
            self.tts_name = self.tts.name
        except Exception as e:
            logging.warning("TTS 不可用：%s", e)

        # 窗口与 Live2D 控制
        live2d_enabled = enable_pet and cfg.live2d.get("enabled", True)
        _stage(48, "正在构建控制台界面…")
        self.chat = ChatWindow(cfg, quit_on_close=not enable_pet, live2d_mode=live2d_enabled)
        self.pet = None          # 完全替换：不再使用内嵌 Live2D 渲染
        self.live2d = None
        self.live2d_ready = False
        start_live2d_async = False
        if live2d_enabled:
            _stage(60, "正在连接 Live2D 角色…")
            self.live2d = Live2DNativeClient(cfg)
            start_live2d_async = True

        self._wire()
        if start_live2d_async:
            # 不阻塞控制台显示：Live2D 在后台线程连接，就绪后通过信号通知 UI
            threading.Thread(target=self._connect_live2d_async, daemon=True).start()
        _stage(78, "正在加载人格与记忆…")
        self._load_gui_data()

        # 自动启动后台服务（无窗口）：heart + GPT-SoVITS
        if autostart_services:
            _stage(86, "正在唤醒 Nori 心脏…")
            self._autostart_services()

        _stage(92, "正在整理状态…")
        self._startup_message()

        # 定时记忆回顾：LLM 总结 + 相似记忆合并
        self.memory_review_timer = QTimer(self)
        self.memory_review_timer.timeout.connect(self._memory_review_in_thread)
        self._restart_memory_review_timer()

        # 若首选 TTS 后端启动时还没就绪（如 GPT-SoVITS 冷启动中），
        # 每 15 秒重新探测并在就绪后自动切换。
        self.tts_probe_timer = QTimer(self)
        self.tts_probe_timer.timeout.connect(self._check_preferred_tts)
        self.tts_probe_timer.start(15 * 1000)

        # 服务状态指示灯
        self.service_status_timer = QTimer(self)
        self.service_status_timer.timeout.connect(self._refresh_service_status)
        self.service_status_timer.start(3 * 1000)
        self._refresh_service_status()
        _stage(100, "Nori 已就绪")

        # 首次使用向导：splash 关闭后询问用户称呼（设置里可随时修改）
        QTimer.singleShot(600, self._maybe_first_run_wizard)

    # ------------------------------------------------------------------
    def _maybe_first_run_wizard(self):
        """第一次启动且未设置称呼时，弹窗让用户输入自己的名字。"""
        try:
            if str(self.cfg.gui.get("user_name", "") or "").strip():
                return
            if bool(self.cfg.gui.get("first_run_done", False)):
                return
            dlg = FirstRunDialog(agent_name=str(self.chat._agent_name or "Nori"),
                                 parent=self.chat)
            dlg.exec()
            name = (dlg.user_name or "").strip()
            if name:
                self.cfg.set_runtime("gui", "user_name", name)
                self.cfg.save_overrides({"gui": {"user_name": name}})
                self.chat.set_user_name(name)
                self.chat.append_system(f"✅ 已记住你的称呼：{name}（可在 设置 → 基础设置 修改）")
            else:
                self.cfg.save_overrides({"gui": {"first_run_done": True}})
                self.chat.append_system(
                    "已跳过初次设置，将默认用“主人”称呼你；可在 设置 → 基础设置 修改。")
        except Exception as e:
            logging.warning("首次使用向导失败：%s", e)

    # ------------------------------------------------------------------
    def _wire(self):
        self.chat.send_requested.connect(self.on_user_text)
        self.chat.media_send_requested.connect(self.on_media_send)
        self.chat.feedback_requested.connect(self.on_feedback)
        self.chat.export_requested.connect(self.on_export)
        self.chat.tts_backend_requested.connect(self.on_tts_backend)
        self.chat.speed_requested.connect(self.on_speed)
        self.chat.scale_requested.connect(self.on_scale)
        self.chat.always_on_top_requested.connect(self.on_always_on_top)
        self.chat.live2d_window_requested.connect(self.on_live2d_window)
        self.chat.save_settings_requested.connect(self.on_save_settings)
        self.chat.font_size_requested.connect(self.on_font_size)
        self.chat.chat_font_size_requested.connect(self.on_chat_font_size)
        self.chat.tts_status_refresh_requested.connect(self.on_tts_status_refresh)
        self.chat.user_name_requested.connect(self.on_user_name)
        self.chat.agent_name_requested.connect(self.on_agent_name)
        self.chat.agent_avatar_requested.connect(self.on_agent_avatar)
        self.chat.avatar_requested.connect(self.on_avatar)
        self.chat.context_compression_requested.connect(self.on_context_compression)
        self.chat.llm_config_requested.connect(self.on_llm_config)
        self.chat.llm_fetch_models_requested.connect(self.on_llm_fetch_models)
        self.chat.search_config_requested.connect(self.on_search_config)
        self.chat.vision_config_requested.connect(self.on_vision_config)
        self.chat.tts_voice_switch_requested.connect(self.on_tts_voice_switch)
        self.chat.tts_voice_import_requested.connect(self.on_tts_voice_import)
        self.chat.tts_voice_export_requested.connect(self.on_tts_voice_export)
        self.chat.voice_export_dir_requested.connect(self.on_voice_export_dir)
        self.chat.llm_model_rename_requested.connect(self.on_llm_model_rename)
        self.chat.llm_model_delete_requested.connect(self.on_llm_model_delete)
        self.chat.memory_auto_review_requested.connect(self.on_memory_auto_review)
        self.chat.memory_review_now_requested.connect(self.on_memory_review_now)
        self.chat.history_refresh_requested.connect(self.on_history_refresh)
        self.chat.conversation_open_requested.connect(self.on_conversation_open)
        self.chat.conversation_new_requested.connect(self.on_conversation_new)
        self.chat.conversation_rename_requested.connect(self.on_conversation_rename)
        self.chat.conversation_delete_requested.connect(self.on_conversation_delete)
        self.chat.mcp_refresh_requested.connect(self.on_mcp_refresh)
        self.chat.mcp_add_requested.connect(self.on_mcp_add)
        self.chat.mcp_import_requested.connect(self.on_mcp_import)
        self.chat.mcp_toggle_requested.connect(self.on_mcp_toggle)
        self.chat.mcp_delete_requested.connect(self.on_mcp_delete)
        self.chat.skill_import_requested.connect(self.on_skill_import)
        self.chat.skill_toggle_requested.connect(self.on_skill_toggle)
        self.chat.skill_delete_requested.connect(self.on_skill_delete)
        self.chat.quit_requested.connect(self.on_quit_requested)
        self.chat.persona_save_requested.connect(self.on_persona_save)
        self.chat.persona_new_requested.connect(self.on_persona_new)
        self.chat.persona_switch_requested.connect(self.on_persona_switch)
        self.chat.persona_delete_requested.connect(self.on_persona_delete)
        self.chat.persona_reset_requested.connect(self.on_persona_reset)
        self.chat.persona_import_requested.connect(self.on_persona_import)
        self.chat.live2d_list_models_requested.connect(self.on_live2d_list_models)
        self.chat.live2d_switch_model_requested.connect(self.on_live2d_switch_model)
        self.chat.live2d_import_model_requested.connect(self.on_live2d_import_model)
        self.chat.memory_refresh_requested.connect(self.on_memory_refresh)
        self.chat.memory_add_requested.connect(self.on_memory_add)
        self.chat.memory_update_requested.connect(self.on_memory_update)
        self.chat.memory_delete_requested.connect(self.on_memory_delete)
        self.chat.memory_rule_toggle_requested.connect(self.on_memory_rule_toggle)
        self.chat.memory_rule_delete_requested.connect(self.on_memory_rule_delete)
        self.chat.service_action_requested.connect(self.on_service_action)
        self.live2d_connection_done.connect(self._on_live2d_connection_done)

    def _connect_live2d_async(self):
        """后台连接原生 Live2D，避免阻塞控制台启动。"""
        try:
            ready = self.live2d.ensure_running()
            self.live2d_ready = ready
            if ready:
                try:
                    self.live2d.show_window()
                except Exception as e:
                    logging.warning("显示 Live2D 窗口失败：%s", e)
                self.live2d_connection_done.emit(True, f"✅ 原生 Live2D 已连接：{self.live2d.base_url}")
            else:
                self.live2d_connection_done.emit(False, "⚠ 原生 Live2D 未连接：请确认 Nori-Desktop-Pet 已构建且控制服务可访问")
        except Exception as e:
            self.live2d_ready = False
            logging.warning("连接 Live2D 失败：%s", e)
            self.live2d_connection_done.emit(False, f"⚠ 原生 Live2D 连接失败：{e}")

    @Slot(bool, str)
    def _on_live2d_connection_done(self, ok: bool, message: str):
        self.chat.append_system(message)
        if ok:
            try:
                self._refresh_live2d_models(announce=False)
            except Exception as e:
                logging.warning("刷新 Live2D 模型列表失败：%s", e)
            self._refresh_status_pill()

    def _load_gui_data(self):
        """把人格、记忆、规则加载到面板。"""
        try:
            # 迁移旧上传头像：data/avatars/user_avatar.* 存在但配置为空时，自动设为默认
            if not str(self.cfg.gui.get("user_avatar", "") or ""):
                candidates = sorted((self.cfg.data_dir / "avatars").glob("user_avatar.*"),
                                    key=lambda p: p.stat().st_mtime, reverse=True)
                if candidates:
                    self.cfg.set_runtime("gui", "user_avatar", str(candidates[0]))
                    self.cfg.save_overrides({"gui": {"user_avatar": str(candidates[0])}})
            self.chat.set_avatar("user", str(self.cfg.gui.get("user_avatar", "") or ""))
        except Exception as e:
            self.chat.append_system(f"⚠ 加载头像失败：{e}")
        try:
            self._refresh_persona_page()
            self._setup_active_persona_workspace(load_history=True)
        except Exception as e:
            self.chat.append_system(f"⚠ 加载人格失败：{e}")
        try:
            self._refresh_memory_page("", "全部")
        except Exception as e:
            self.chat.append_system(f"⚠ 加载记忆失败：{e}")
        try:
            self._refresh_tts_voices()
        except Exception as e:
            self.chat.append_system(f"⚠ 加载 TTS 语音包失败：{e}")
        try:
            self._refresh_mcp_page()
        except Exception as e:
            self.chat.append_system(f"⚠ 加载 MCP/Skills 失败：{e}")
        if self.live2d_ready:
            try:
                self._refresh_live2d_models(announce=False)
            except Exception as e:
                logging.warning("加载 Live2D 模型列表失败：%s", e)

    def _refresh_tts_voices(self):
        """刷新 TTS 语音包下拉框，并标出当前生效语音包。"""
        voices = list_voices(self.cfg.root)
        current = ""
        ref = str(self.cfg.tts.get("gpt_sovits", {}).get("ref_audio_path", "") or "")
        if ref:
            try:
                p = Path(ref)
                if p.parent.name and p.parent.parent.name == "voices":
                    current = p.parent.name
            except Exception:
                pass
        self.chat.set_tts_voices(voices, current)

    def _autostart_services(self):
        """无窗口启动 heart 与 GPT-SoVITS（run.bat 只负责拉起本 GUI）。"""
        if self.cfg.heart.get("enabled", True):
            try:
                self.services.start_heart(skip_live2d=not self.enable_pet)
            except Exception as e:
                logging.warning("自动启动 Heart 失败：%s", e)
        gs = self.cfg.tts.get("gpt_sovits", {})
        if gs.get("auto_start", True) and gs.get("ref_audio_path"):
            try:
                self.services.start_gpt_sovits()
            except Exception as e:
                logging.warning("自动启动 GPT-SoVITS 失败：%s", e)
        self._refresh_service_status()

    def _refresh_service_status(self):
        """后台刷新服务状态，避免 tasklist/HTTP 阻塞主线程。"""
        if self._service_status_busy:
            return
        self._service_status_busy = True
        worker = ServiceStatusWorker(self.services)
        worker.signals.result.connect(self._on_service_status_result)
        worker.signals.error.connect(self._on_service_status_error)
        self.pool.start(worker)

    def _on_service_status_result(self, st):
        self._service_status_busy = False
        try:
            self.chat.set_service_status("heart", bool(st.get("heart", False)))
            self.chat.set_service_status("gpt_sovits", bool(st.get("gpt_sovits", False)))
        except Exception:
            pass

    def _on_service_status_error(self, err):
        self._service_status_busy = False
        logging.warning("刷新服务状态失败：%s", err)

    def _check_preferred_tts(self):
        """后台探测首选 TTS 后端，就绪后自动切换（避免主线程 socket 阻塞）。"""
        if self._tts_probe_busy:
            return
        order = list(self.cfg.tts.get("order", []))
        wanted = str(self.cfg.tts.get("backend", "auto"))
        preferred = wanted if wanted != "auto" else (order[0] if order else None)
        if not preferred:
            return
        if self.tts is not None and preferred == self.tts_name:
            return
        self._tts_probe_busy = True
        worker = TTSPreferredWorker(self.cfg, preferred)
        worker.signals.result.connect(self._on_tts_preferred_result)
        worker.signals.error.connect(self._on_tts_probe_error)
        self.pool.start(worker)

    def _on_tts_preferred_result(self, payload):
        self._tts_probe_busy = False
        try:
            preferred, ok, backend = payload
            if not ok or backend is None:
                return
            wanted = str(self.cfg.tts.get("backend", "auto"))
            if wanted != "auto" and preferred != wanted:
                return
            self.tts = backend
            self.tts_name = preferred
            self._apply_speed(self.chat.speed_slider.value() / 100.0)
            self.chat.append_system(f"✅ Nori 语音引擎已就绪，自动切换：{preferred}")
            self._refresh_service_status()
            self._refresh_status_pill()
            self._flush_tts_pending()
        except Exception as e:
            logging.warning("切换首选 TTS 失败：%s", e)

    def _on_tts_probe_error(self, err):
        self._tts_probe_busy = False
        logging.warning("TTS 后端探测失败：%s", err)

    def _vision_mcp_available(self) -> bool:
        """判断是否已通过设置界面的 MCP 导入了视觉服务器。"""
        try:
            for s in self.mcp_manager.list_servers():
                if s.get("enabled") and "vision" in str(s.get("name", "")).lower():
                    return True
        except Exception:
            pass
        return False

    def _refresh_status_pill(self):
        api_status = "API 已配置" if self.cfg.api_key else "API Key 未填写"
        tts_status = "GPT-SoVITS·Nori 已就绪" if self.tts else "GPT-SoVITS·Nori 冷启动/未就绪"
        live2d_status = "已连接" if self.live2d_ready else ("未连接" if self.live2d else "关闭")
        vision_status = "MCP 已接入" if self._vision_mcp_available() else "未接入"
        search_status = "已启用" if self.search.enabled else "未启用"
        self.chat.set_status(
            f"{api_status} · TTS：{tts_status} · 视觉：{vision_status} · "
            f"搜索：{search_status} · Live2D：{live2d_status}")

    def _startup_message(self):
        stats = self.memory.stats()
        self.chat.append_system(
            f"记忆库：{stats['messages']} 条消息 / {stats['memories']} 条长期记忆 / {stats['rules']} 条规则")
        tts_status = "GPT-SoVITS · Nori 音色（唯一语音引擎）"
        self.chat.append_system(
            f"TTS 后端：{tts_status}（当前状态：{'✅ 已就绪' if self.tts else '⏳ 冷启动中，消息将排队'}）")
        if self._vision_mcp_available():
            self.chat.append_system(
                "👁 视觉 MCP：已接入（nori-vision）。点击 📷 发送图片，Nori 能看懂照片内容。")
        else:
            self.chat.append_system(
                "👁 视觉 MCP：未接入。请先启动 vision_mcp/server.py，"
                "再到 设置→MCP/Skills 导入 vision_mcp/nori-vision.mcp.json")
        if self.search.enabled:
            self.chat.append_system("🔍 联网搜索：百度 AI 搜索（输入 /搜 关键词 或 搜索 xxx）")
        else:
            self.chat.append_system("🔍 联网搜索：未启用")
        if not self.cfg.api_key:
            self.chat.append_system("⚠ 还没有配置 LLM API Key：请编辑 config.yaml 的 llm.api_key，或使用本地 Ollama。")
        else:
            self.chat.append_system(f"模型：{self.cfg.model}")

        # 原生 Live2D 状态
        if self.live2d is not None:
            if self.live2d_ready:
                self.chat.append_system(f"✅ 原生 Live2D 已连接：{self.live2d.base_url}")
            else:
                self.chat.append_system(
                    "⚠ 原生 Live2D 未连接：请确认 Nori-Desktop-Pet 已构建且控制服务可访问")
        else:
            self.chat.append_system("ℹ 未启用 Live2D（纯对话框模式）")

        # 面板初始状态
        self._refresh_status_pill()
        speed = float(self.cfg.tts.get("speed", 1.0) or 1.0)
        scale = float(self.cfg.live2d.get("scale", 1.0) or 1.0)
        top = bool(self.cfg.gui.get("pet_always_on_top", True))
        font_size = int(self.cfg.gui.get("font_size", 13) or 13)
        chat_font_size = int(self.cfg.gui.get("chat_font_size", 15) or 15)
        self.chat.set_voice_export_dir(str(self.cfg.gui.get("voice_export_dir", "") or ""))
        self.chat.set_current_settings(
            backend=str(self.cfg.tts.get("backend", "auto")),
            speed=speed, scale=scale, always_on_top=top,
            font_size=font_size, chat_font_size=chat_font_size)

    # ------------------------------------------------------------------
    @Slot(str)
    def on_user_text(self, text: str):
        if not self.cfg.api_key:
            msg = "还没有配置 LLM API Key。请编辑 config.yaml 的 llm.api_key，或使用本地 Ollama。"
            self.chat.append_system("⚠ " + msg)
            if self.pet:
                self.pet.show_bubble("先帮我填一下 API Key 啦，在 config.yaml 里～")
            return

        self.chat.set_input_enabled(False)
        self.chat.set_thinking(True)
        # 思考时播放待机动作，避免角色僵硬（模型无该动作时会被安全忽略）
        if self.live2d and self.live2d_ready:
            try:
                self.live2d.play_motion("idle")
            except Exception:
                pass
        worker = SendWorker(self.core, text)
        worker.signals.result.connect(self._on_reply)
        worker.signals.error.connect(self._on_llm_error)
        self.pool.start(worker)

    @Slot(object, str)
    def on_media_send(self, image_paths, caption: str):
        """发送图片/表情包：复制进项目 media 目录 -> 显示缩略图 -> 视觉理解 -> LLM。"""
        if not self.cfg.api_key:
            msg = "还没有配置 LLM API Key。请编辑 config.yaml 的 llm.api_key，或使用本地 Ollama。"
            self.chat.append_system("⚠ " + msg)
            return
        paths = self._prepare_media_paths(image_paths or [])
        if not paths:
            self.chat.append_system("⚠ 没有可发送的图片（文件不存在或格式不支持）")
            return
        caption = (caption or "").strip()

        self.chat.set_input_enabled(False)
        self.chat.set_thinking(True)
        if self.live2d and self.live2d_ready:
            try:
                self.live2d.play_motion("idle")
            except Exception:
                pass
        worker = SendWorker(self.core, caption, image_paths=paths)
        worker.signals.result.connect(self._on_reply)
        worker.signals.error.connect(self._on_llm_error)
        self.pool.start(worker)

    def _prepare_media_paths(self, raw_paths) -> list[str]:
        """校验用户选择的图片；外部图片复制到 data/chat_media 以持久保存。"""
        sticker_root = (self.cfg.root / "data" / "stickers").resolve()
        media_root = (self.cfg.root / "data" / "chat_media").resolve()
        out: list[str] = []
        seen: set[str] = set()
        for raw in raw_paths or []:
            try:
                p = Path(str(raw)).expanduser().resolve()
            except Exception:
                continue
            if str(p) in seen or not p.is_file():
                continue
            suffix = p.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                continue
            try:
                if p.stat().st_size > 20 * 1024 * 1024:
                    self.chat.append_system(f"⚠ 图片超过 20MB，已跳过：{p.name}")
                    continue
                if not (p.is_relative_to(sticker_root) or p.is_relative_to(media_root)):
                    copied = copy_to_chat_media(self.cfg.root, p)
                    if copied is None:
                        continue
                    p = copied.resolve()
            except Exception as e:
                self.chat.append_system(f"⚠ 处理图片失败：{e}")
                continue
            seen.add(str(p))
            out.append(str(p))
        return out[:4]

    @Slot(object)
    def _on_reply(self, reply):
        self.chat.set_input_enabled(True)
        self.chat.set_thinking(False)
        self.chat.append_assistant(reply.text)
        self._apply_live2d_commands(reply.commands)
        self.speak(reply.text)

    def _apply_live2d_commands(self, commands):
        """把 LLM 的 [expr:xx] / [motion:xx] 发给原生 Live2D。"""
        if not commands or not self.live2d:
            return
        for kind, name in commands:
            try:
                if kind == "expr":
                    mapped = self._map_name("emotion_map", name)
                    self.live2d.set_expression(mapped)
                elif kind == "motion":
                    mapped = self._map_name("motion_map", name)
                    self.live2d.play_motion(mapped)
            except Exception as e:
                logging.warning("Live2D 指令失败 %s=%s：%s", kind, name, e)

    def _map_name(self, map_key: str, name: str) -> str:
        mapping = self.cfg.persona.get(map_key, {})
        if isinstance(mapping, dict):
            return mapping.get(name, name)
        return name

    @Slot(str)
    def _on_llm_error(self, err: str):
        self.chat.set_input_enabled(True)
        self.chat.set_thinking(False)
        self.chat.append_system(f"⚠ LLM 调用失败：{err}")

    @Slot(float)
    def on_feedback(self, delta: float):
        self.core.apply_feedback(delta)
        label = "👍 已记录正面反馈，相关记忆已加强" if delta > 0 else "👎 已记录负面反馈，相关记忆已减弱"
        self.chat.append_system(label)

    @Slot()
    def on_export(self):
        try:
            path = self.core.export_training_data(str(self.cfg.data_dir / "training.jsonl"))
            self.chat.append_system(f"已导出训练数据：{path}")
        except Exception as e:
            self.chat.append_system(f"导出失败：{e}")

    def _consolidate_in_thread(self):
        threading.Thread(target=self.core.consolidate_now, daemon=True,
                         name="memory-consolidate-timer").start()

    def _restart_memory_review_timer(self):
        enabled = bool(self.cfg.memory.get("auto_review_enabled", True))
        minutes = max(5, int(self.cfg.memory.get("auto_review_minutes", 30)))
        if enabled:
            self.memory_review_timer.start(minutes * 60 * 1000)
        else:
            self.memory_review_timer.stop()

    def _memory_review_in_thread(self):
        threading.Thread(target=self._memory_review_once, daemon=True,
                         name="memory-auto-review").start()

    def _memory_review_once(self):
        # 本地 Ollama 模式跳过自动记忆回顾，避免后台 LLM 抢占显存/拖慢回复
        if getattr(self.cfg, "is_local_llm", False):
            logging.info("本地 Ollama 模式：跳过自动记忆回顾")
            return
        threshold = float(self.cfg.memory.get("similarity_threshold", 0.85))
        try:
            merged = self.memory.merge_similar_memories(threshold)
            logging.info("相似记忆合并：%d 条", merged)
        except Exception as e:
            logging.warning("相似记忆合并失败：%s", e)
        self.core.consolidate_now()

    @Slot()
    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide()
        else:
            self.chat.show()
            self.chat.raise_()
            self.chat.activateWindow()

    # ------------------------------------------------------------------
    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if not self.tts:
            # Nori 语音引擎冷启动中：先排队，就绪后按顺序朗读
            if len(self._tts_pending) >= 8:
                self._tts_pending.pop(0)
            self._tts_pending.append(text)
            self._schedule_tts_retry()
            return
        if self._tts_pending or self._tts_busy:
            self._tts_pending.append(text)
            return
        self._speak_now(text)

    def _speak_now(self, text: str):
        if not self.tts or self._tts_busy:
            return
        self._tts_busy = True
        if self.live2d:
            try:
                self.live2d.set_speaking(True)
            except Exception:
                pass
        self._start_lip_sync()
        worker = TTSWorker(self.tts, text)
        worker.signals.result.connect(self._on_tts_done)
        worker.signals.error.connect(self._on_tts_error)
        self.pool.start(worker)

    # ------------------------------------------------------------------ Live2D 嘴型同步
    def _start_lip_sync(self):
        """TTS 播放期间向 Live2D 推送模拟音频电平，驱动嘴型动作。"""
        if not self.live2d or not self.live2d_ready:
            return
        self._lip_sync_counter = 0
        if getattr(self, "_lip_sync_timer", None) is None:
            self._lip_sync_timer = QTimer(self)
            self._lip_sync_timer.setInterval(60)
            self._lip_sync_timer.timeout.connect(self._tick_lip_sync)
        if not self._lip_sync_timer.isActive():
            self._lip_sync_timer.start()

    def _tick_lip_sync(self):
        if not self._tts_busy:
            self._stop_lip_sync()
            return
        self._lip_sync_counter += 1
        phase = self._lip_sync_counter * 0.55
        # 模拟语音包络：基础开度 + 起伏，让嘴型看起来像在说话
        level = 0.35 + 0.45 * abs(math.sin(phase)) + 0.12 * math.sin(phase * 2.7)
        level = max(0.0, min(1.0, level))
        if self.live2d:
            try:
                self.live2d.audio_level(level)
            except Exception:
                pass

    def _stop_lip_sync(self):
        timer = getattr(self, "_lip_sync_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
        if self.live2d:
            try:
                self.live2d.audio_level(0)
            except Exception:
                pass

    def _flush_tts_pending(self):
        if self._tts_busy or not self.tts or not self._tts_pending:
            return
        text = self._tts_pending.pop(0)
        self._speak_now(text)

    def _schedule_tts_retry(self):
        """如果 TTS 还没就绪或有积压，几秒后自动再试一次。"""
        if getattr(self, "_tts_retry_timer", None) is None:
            self._tts_retry_timer = QTimer(self)
            self._tts_retry_timer.setInterval(5000)
            self._tts_retry_timer.timeout.connect(self._on_tts_retry)
        if not self._tts_retry_timer.isActive():
            self._tts_retry_timer.start()

    def _on_tts_retry(self):
        if self._tts_pending:
            if self.tts:
                self._flush_tts_pending()
            else:
                self._check_preferred_tts()
        elif not self._tts_busy:
            self._tts_retry_timer.stop()

    @Slot(object)
    def _on_tts_done(self, _):
        self._tts_busy = False
        self._stop_lip_sync()
        if self.live2d:
            try:
                self.live2d.set_speaking(False)
            except Exception:
                pass
        self._flush_tts_pending()
        if not self._tts_pending and not self._tts_busy:
            self._tts_retry_timer.stop()

    @Slot(str)
    def _on_tts_error(self, err: str):
        self._tts_busy = False
        self._stop_lip_sync()
        if self.live2d:
            try:
                self.live2d.set_speaking(False)
            except Exception:
                pass
        self.chat.append_system(f"⚠ TTS 播放失败：{err}")
        self._flush_tts_pending()
        if not self._tts_pending and not self._tts_busy:
            self._tts_retry_timer.stop()

    # ------------------------------------------------------------------ 快速设置 ----
    @Slot(str)
    def on_tts_backend(self, name: str):
        """运行时切换 TTS 后端。"""
        self.cfg.set_runtime("tts", "backend", name)
        if name == "auto":
            try:
                self.tts = create_tts(self.cfg)
                self.tts_name = self.tts.name
                self.chat.append_system(f"已切换到自动选择：{self.tts_name}")
            except Exception as e:
                self.chat.append_system(f"自动选择 TTS 失败：{e}")
                return
        else:
            try:
                backend = create_backend(name, self.cfg)
                if not backend.available():
                    self.chat.append_system(f"⚠ {name} 后端当前不可用（模型/依赖未就绪）")
                    return
                self.tts = backend
                self.tts_name = name
                self.chat.append_system(f"已切换到 TTS：{name}")
            except Exception as e:
                self.chat.append_system(f"切换 TTS 失败：{e}")
                return
        # 新后端继承当前语速
        speed = self.chat.speed_slider.value() / 100.0
        self._apply_speed(speed)
        self._refresh_status_pill()
        self._flush_tts_pending()

    @Slot(str)
    def on_voice_export_dir(self, path: str):
        """设置语音包导出目录并持久化（留空 = 默认下载目录）。"""
        path = (path or "").strip()
        if path:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self.chat.append_system(f"⚠ 导出目录不可用：{e}")
                return
        self.cfg.set_runtime("gui", "voice_export_dir", path)
        self.cfg.save_overrides({"gui": {"voice_export_dir": path}})
        self.chat.set_voice_export_dir(path)
        self.chat.append_system(
            f"📦 语音包导出目录已设为：{path if path else '默认下载目录'}")

    @Slot()
    def on_tts_status_refresh(self):
        try:
            self._check_preferred_tts()
            self._refresh_service_status()
            self._refresh_status_pill()
            self.chat.append_system(
                f"状态已刷新：TTS={self.tts_name}，"
                f"Heart={'运行中' if self.services.heart_is_running() else '未运行'}，"
                f"GPT-SoVITS={'运行中' if self.services.gsv_is_running() else '未运行'}")
        except Exception as e:
            self.chat.append_system(f"⚠ 刷新状态失败：{e}")

    @Slot(int)
    def on_font_size(self, size: int):
        size = max(10, min(18, int(size)))
        self.cfg.set_runtime("gui", "font_size", size)
        self.chat.apply_font_size(size)

    @Slot(int)
    def on_chat_font_size(self, size: int):
        size = max(12, min(22, int(size)))
        self.cfg.set_runtime("gui", "chat_font_size", size)
        self.chat.apply_chat_font_size(size)

    def _reload_current_chat_history(self):
        if self.current_conversation_id:
            try:
                self._load_conversation_messages(self.current_conversation_id)
            except Exception:
                pass

    @Slot(str, str)
    def on_avatar(self, role: str, path: str):
        if role in ("nori", "agent"):
            self.on_agent_avatar(path)
            return
        try:
            if not path:
                self.cfg.set_runtime("gui", "user_avatar", "")
                self.cfg.save_overrides({"gui": {"user_avatar": ""}})
                self.chat.set_avatar("user", "")
                self._reload_current_chat_history()
                self.chat.append_system("我的头像已恢复默认")
                return
            src = Path(path)
            if not src.is_file():
                self.chat.append_system("头像文件不存在")
                return
            avatar_dir = self.cfg.data_dir / "avatars"
            avatar_dir.mkdir(parents=True, exist_ok=True)
            suffix = src.suffix.lower() or ".png"
            dest = avatar_dir / f"user_avatar{suffix}"
            shutil.copy2(src, dest)
            self.cfg.set_runtime("gui", "user_avatar", str(dest))
            self.cfg.save_overrides({"gui": {"user_avatar": str(dest)}})
            self.chat.set_avatar("user", str(dest))
            self._reload_current_chat_history()
            self.chat.append_system(f"我的头像已更新并设为默认：{dest}")
        except Exception as e:
            self.chat.append_system(f"设置头像失败：{e}")

    @Slot(str)
    def on_agent_avatar(self, path: str):
        try:
            persona = active_persona_name(self.cfg)
            meta = load_persona_meta(self.cfg, persona)
            if not path:
                meta["avatar"] = ""
            else:
                src = Path(path)
                if not src.is_file():
                    self.chat.append_system("头像文件不存在")
                    return
                avatar_dir = self.cfg.data_dir / "avatars"
                avatar_dir.mkdir(parents=True, exist_ok=True)
                safe = persona.replace(" ", "_").replace("/", "_")
                dest = avatar_dir / f"persona_{safe}{src.suffix.lower() or '.png'}"
                shutil.copy2(src, dest)
                meta["avatar"] = str(dest)
            save_persona_meta(self.cfg, persona, meta)
            self.chat.set_avatar("agent", meta.get("avatar", ""))
            self._reload_current_chat_history()
            self.chat.append_system(
                f"{persona} 头像已更新并设为默认" if meta.get("avatar")
                else f"{persona} 头像已恢复默认")
        except Exception as e:
            self.chat.append_system(f"设置智能体头像失败：{e}")

    @Slot(str)
    def on_user_name(self, name: str):
        name = (name or "").strip() or "主人"
        self.cfg.set_runtime("gui", "user_name", name)
        self.cfg.save_overrides({"gui": {"user_name": name}})
        self.chat.set_user_name(name)
        self._reload_current_chat_history()
        self.chat.append_system(f"用户昵称已设为：{name}")

    @Slot(str)
    def on_agent_name(self, name: str):
        persona = active_persona_name(self.cfg)
        name = (name or "").strip() or persona
        meta = load_persona_meta(self.cfg, persona)
        meta["agent_name"] = name
        save_persona_meta(self.cfg, persona, meta)
        self.chat.set_agent_name(name)
        self._reload_current_chat_history()
        self.chat.append_system(f"{persona} 的智能体名字已设为：{name}")

    @Slot(str, int, int)
    def on_context_compression(self, mode: str, window: int, max_chars: int):
        self.cfg.set_runtime("llm", "context_compression", {
            "mode": mode, "window_size": max(5, int(window)),
            "max_chars": max(100, int(max_chars))})
        self.chat.append_system(
            f"上下文压缩已设置：{mode}，保留最近 {window} 条，摘要 {max_chars} 字")

    @staticmethod
    def _llm_provider_from_base(base_url: str) -> str:
        base_lower = (base_url or "").lower()
        if "localhost" in base_lower or "127.0.0.1" in base_lower:
            return "ollama"
        if "deepseek" in base_lower:
            return "deepseek"
        if "openai" in base_lower:
            return "openai"
        return "custom"

    @Slot(str, str, str)
    def on_llm_config(self, api_key: str, base_url: str, model: str):
        try:
            api_key = (api_key or "").strip()
            base_url = (base_url or "https://api.deepseek.com").strip()
            model = (model or "deepseek-v4-flash").strip()
            base_lower = base_url.lower()
            if "localhost" in base_lower or "127.0.0.1" in base_lower:
                provider = "ollama"
            elif "deepseek" in base_lower:
                provider = "deepseek"
            elif "openai" in base_lower:
                provider = "openai"
            else:
                provider = "custom"
            self.cfg.set_runtime("llm", "api_key", api_key)
            self.cfg.set_runtime("llm", "base_url", base_url)
            self.cfg.set_runtime("llm", "model", model)
            self.cfg.set_runtime("llm", "provider", provider)
            custom_models = [str(x).strip() for x in (self.cfg.llm.get("custom_models") or []) if str(x).strip()]
            if model and model not in custom_models:
                custom_models.append(model)
            self.cfg.set_runtime("llm", "custom_models", custom_models)
            self.brain.reload()
            self.chat.add_custom_model(model)
            # 立刻落盘到 settings_overrides，下次启动生效（config.yaml 仍作为默认值）
            self.cfg.save_overrides({
                "llm": {"api_key": api_key, "base_url": base_url, "model": model,
                        "provider": provider, "custom_models": custom_models}})
            self.chat.append_system(
                "✅ API 配置已应用并保存到 data/settings_overrides.json（优先级高于 config.yaml）")
        except Exception as e:
            self.chat.append_system(f"⚠ 保存 API 配置失败：{e}")

    @Slot()
    def on_llm_fetch_models(self):
        """从当前 OpenAI 兼容提供商拉取模型列表（支持 Ollama）。"""
        try:
            from openai import OpenAI
            api_key = str(self.cfg.api_key or "").strip() or "not-needed"
            client = OpenAI(api_key=api_key, base_url=self.cfg.base_url, timeout=30)
            raw_models = client.models.list().data
            model_ids: set[str] = set()
            for m in raw_models:
                if isinstance(m, str):
                    model_ids.add(m)
                elif (m_id := getattr(m, "id", None)):
                    model_ids.add(str(m_id))
            models = sorted(model_ids)
            if not models:
                self.chat.append_system("⚠ 提供商返回了空模型列表")
                return
            combo = self.chat.api_model_combo
            combo.blockSignals(True)
            combo.clear()
            for name in models:
                combo.addItem(name)
            # 保留本地自定义模型
            for name in (self.cfg.llm.get("custom_models") or []):
                name = str(name).strip()
                if name and combo.findText(name) < 0:
                    combo.addItem(name)
            current = str(self.cfg.llm.get("model", "") or "")
            if current and combo.findText(current) < 0:
                combo.addItem(current)
            if current:
                combo.setCurrentText(current)
            combo.blockSignals(False)
            self.chat.append_system(f"✅ 已从 {self.cfg.base_url} 获取 {len(models)} 个模型")
        except Exception as e:
            self.chat.append_system(f"⚠ 获取模型列表失败：{e}")

    @Slot(str)
    def on_search_config(self, api_key: str):
        """保存百度搜索 API Key 到本地覆盖文件，不写入 config.yaml。"""
        try:
            api_key = (api_key or "").strip()
            self.cfg.set_runtime("search", "api_key", api_key)
            self.cfg.save_overrides({"search": {"api_key": api_key}})
            self._refresh_status_pill()
            self.chat.append_system(
                "✅ 百度搜索 API Key 已保存到 data/settings_overrides.json"
                + ("（当前已填写）" if api_key else "（已清空）"))
        except Exception as e:
            self.chat.append_system(f"⚠ 保存搜索 API 配置失败：{e}")

    @Slot(str, str, str, int)
    def on_vision_config(self, api_key: str, base_url: str, model: str, port: int):
        """保存视觉 MCP 配置到 vision_mcp/config.json（独立于主项目）。"""
        try:
            vision_dir = self.cfg.root / "vision_mcp"
            vision_dir.mkdir(parents=True, exist_ok=True)
            cfg_data = {
                "api_key": (api_key or "").strip(),
                "base_url": (base_url or "https://ark.cn-beijing.volces.com/api/v3").strip(),
                "model": (model or "doubao-seed-2-1-pro-260628").strip(),
                "port": max(1, min(65535, int(port))),
                "timeout": 120,
            }
            (vision_dir / "config.json").write_text(
                json.dumps(cfg_data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._refresh_status_pill()
            self.chat.append_system(
                "✅ 视觉 MCP API 已保存到 vision_mcp/config.json。"
                "如果视觉 MCP 正在运行，请重启 vision_mcp/server.py 后生效。")
        except Exception as e:
            self.chat.append_system(f"⚠ 保存视觉 MCP 配置失败：{e}")

    @Slot(str)
    def on_tts_voice_switch(self, name: str):
        """切换 TTS 语音包：应用配置、更新 GPT-SoVITS 权重路径并重启 API。"""
        try:
            info = apply_voice_to_config(self.cfg, name)
            was_running = self.services.gsv_is_running()
            if was_running:
                self.services.stop_gpt_sovits()
            if info.get("ref_audio"):
                self.services.start_gpt_sovits()
            self.tts = None
            self.tts_name = "无"
            self._check_preferred_tts()
            self._refresh_tts_voices()
            extra = "，已更新 GPT-SoVITS 权重路径" if info.get("updated_yaml") else ""
            self.chat.append_system(
                f"✅ 已切换 TTS 语音包：{info['name']}{extra}。"
                "如果 API 正在冷启动，稍等片刻会自动就绪。")
        except Exception as e:
            self.chat.append_system(f"⚠ 切换 TTS 语音包失败：{e}")
            self._refresh_tts_voices()

    @Slot(str)
    def on_tts_voice_import(self, path: str):
        try:
            name = import_voice(self.cfg.root, path)
            if not name:
                self.chat.append_system("⚠ 导入失败：没有找到参考音频（wav）")
                return
            self._refresh_tts_voices()
            self.chat.append_system(f"📂 已导入 TTS 语音包：{name}，可在下拉框切换")
        except Exception as e:
            self.chat.append_system(f"⚠ 导入 TTS 语音包失败：{e}")

    @Slot(str)
    def on_tts_voice_export(self, name: str):
        try:
            dest_dir = (str(self.cfg.gui.get("voice_export_dir", "") or "").strip()
                        or str(Path.home() / "Downloads"))
            dest = export_voice(self.cfg.root, name, Path(dest_dir))
            if not dest:
                self.chat.append_system("⚠ 导出失败：语音包不存在或缺少参考音频")
                return
            self.chat.append_system(f"📦 已导出 TTS 语音包到：{dest}")
        except Exception as e:
            self.chat.append_system(f"⚠ 导出 TTS 语音包失败：{e}")

    # ------------------------------------------------------------------ LLM 模型重命名/删除
    @Slot(str, str)
    def on_llm_model_rename(self, old_name: str, new_name: str):
        try:
            old_name = (old_name or "").strip()
            new_name = (new_name or "").strip()
            if not new_name:
                return
            custom = [str(x).strip() for x in (self.cfg.llm.get("custom_models") or []) if str(x).strip()]
            if old_name in custom:
                custom[custom.index(old_name)] = new_name
            elif new_name not in custom:
                custom.append(new_name)
            current = str(self.cfg.llm.get("model", "") or "")
            if current == old_name:
                self.cfg.set_runtime("llm", "model", new_name)
                self.chat.api_model_combo.setCurrentText(new_name)
                self.brain.reload()
            self.cfg.set_runtime("llm", "custom_models", custom)
            self.cfg.save_overrides({
                "llm": {"custom_models": custom, "model": self.cfg.llm.get("model", "")}})
            self.chat.add_custom_model(new_name)
            self.chat.remove_custom_model(old_name)
            self.chat.append_system(f"✏ LLM 模型已重命名：{old_name} → {new_name}")
        except Exception as e:
            self.chat.append_system(f"⚠ 重命名 LLM 模型失败：{e}")

    @Slot(str)
    def on_llm_model_delete(self, name: str):
        try:
            name = (name or "").strip()
            custom = [str(x).strip() for x in (self.cfg.llm.get("custom_models") or []) if str(x).strip() and str(x).strip() != name]
            current = str(self.cfg.llm.get("model", "") or "")
            if current == name:
                current = custom[0] if custom else "deepseek-v4-flash"
                self.cfg.set_runtime("llm", "model", current)
                self.chat.api_model_combo.setCurrentText(current)
                self.brain.reload()
            self.cfg.set_runtime("llm", "custom_models", custom)
            self.cfg.save_overrides({
                "llm": {"custom_models": custom, "model": self.cfg.llm.get("model", "")}})
            self.chat.remove_custom_model(name)
            self.chat.append_system(f"🗑 已从模型列表删除：{name}")
        except Exception as e:
            self.chat.append_system(f"⚠ 删除 LLM 模型失败：{e}")

    # ------------------------------------------------------------------ 记忆
    @Slot(bool, int)
    def on_memory_auto_review(self, enabled: bool, minutes: int):
        self.cfg.set_runtime("memory", "auto_review_enabled", enabled)
        self.cfg.set_runtime("memory", "auto_review_minutes", max(5, int(minutes)))
        self._restart_memory_review_timer()
        self.chat.append_system(
            f"定时记忆回顾：{'开启，每 ' + str(minutes) + ' 分钟' if enabled else '已关闭'}")

    @Slot()
    def on_memory_review_now(self):
        self.chat.append_system("开始记忆回顾：合并相似记忆 + LLM 总结…")
        self._memory_review_in_thread()

    @Slot(float)
    def on_speed(self, speed: float):
        self._apply_speed(speed)

    def _apply_speed(self, speed: float):
        self.cfg.set_runtime("tts", "speed", speed)
        if self.tts and hasattr(self.tts, "set_speed"):
            try:
                self.tts.set_speed(speed)
            except Exception as e:
                logging.debug("设置语速失败：%s", e)

    @Slot(float)
    def on_scale(self, scale: float):
        self.cfg.set_runtime("live2d", "scale", scale)
        if self.live2d and hasattr(self.live2d, "set_scale"):
            try:
                self.live2d.set_scale(scale)
            except Exception as e:
                self.chat.append_system(f"⚠ 设置 Live2D 缩放失败：{e}")
        if self.pet:
            self.pet.set_scale(scale)

    @Slot(bool)
    def on_always_on_top(self, on: bool):
        self.cfg.set_runtime("gui", "pet_always_on_top", on)
        if self.pet:
            self.pet.setWindowFlag(Qt.WindowStaysOnTopHint, on)
            self.pet.show()  # 重新显示使置顶标志生效
            self.chat.append_system("宠物窗口已置顶" if on else "宠物窗口已取消置顶")
        else:
            self.chat.append_system("原生 Live2D 应用自身管理置顶")

    @Slot(str)
    def on_live2d_window(self, action: str):
        """显示/隐藏/切换原生 Live2D 窗口。"""
        if not self.live2d:
            self.chat.append_system("未启用 Live2D")
            return
        if not self.live2d_ready:
            self.live2d_ready = self.live2d.ensure_running()
        if not self.live2d_ready:
            self.chat.append_system("⚠ Live2D 未连接，无法控制窗口")
            return
        try:
            self.live2d.control_window(action)
            label = {"show": "已显示", "hide": "已隐藏", "toggle": "已切换"}.get(action, action)
            self.chat.append_system(f"Live2D 窗口：{label}")
            if action in ("show", "toggle"):
                self._refresh_live2d_models(announce=False)
        except Exception as e:
            self.chat.append_system(f"Live2D 窗口控制失败：{e}")

    @Slot()
    def on_save_settings(self):
        """保存面板设置到 data/settings_overrides.json（保留 config.yaml 注释）。"""
        current_model = self.chat.api_model_combo.currentText().strip()
        custom_models = [str(x).strip() for x in (self.cfg.llm.get("custom_models") or []) if str(x).strip()]
        if current_model and current_model not in custom_models:
            custom_models.append(current_model)
        self.chat.add_custom_model(current_model)
        overrides = {
            "tts": {
                "backend": self.chat.backend_combo.currentData(),
                "speed": round(self.chat.speed_slider.value() / 100.0, 2),
            },
            "llm": {
                "api_key": self.chat.api_key_edit.text().strip(),
                "base_url": self.chat.api_base_edit.text().strip(),
                "model": current_model,
                "provider": self._llm_provider_from_base(
                    self.chat.api_base_edit.text().strip()),
                "custom_models": custom_models,
                "context_compression": {
                    "mode": self.chat.compression_mode_combo.currentData(),
                    "window_size": self.chat.compression_window_spin.value(),
                    "max_chars": self.chat.compression_chars_spin.value(),
                },
            },
            "live2d": {"scale": round(self.chat.scale_slider.value() / 100.0, 2)},
            "search": {"api_key": self.chat.search_api_edit.text().strip()},
            "gui": {
                "pet_always_on_top": self.chat.top_check.isChecked(),
                "font_size": int(self.chat.font_combo.currentData() or 13),
                "chat_font_size": int(self.chat.chat_font_combo.currentData() or 15),
                "user_name": self.chat._user_name,
                "user_avatar": self.chat._user_avatar,
            },
            "memory": {
                "auto_review_enabled": self.chat.mem_auto_review_check.isChecked(),
                "auto_review_minutes": self.chat.mem_review_spin.value(),
            },
        }
        try:
            path = self.cfg.save_overrides(overrides)
            # 同时把视觉 MCP 配置写入 vision_mcp/config.json（独立文件）
            if hasattr(self.chat, "vision_api_edit"):
                vision_dir = self.cfg.root / "vision_mcp"
                vision_dir.mkdir(parents=True, exist_ok=True)
                (vision_dir / "config.json").write_text(
                    json.dumps({
                        "api_key": self.chat.vision_api_edit.text().strip(),
                        "base_url": self.chat.vision_base_edit.text().strip(),
                        "model": self.chat.vision_model_combo.currentText().strip(),
                        "port": int(self.chat.vision_port_spin.value()),
                        "timeout": 120,
                    }, ensure_ascii=False, indent=2), encoding="utf-8")
            self.chat.append_system(f"✅ 设置已保存到 {path}，下次启动自动生效")
        except Exception as e:
            self.chat.append_system(f"保存设置失败：{e}")

    # ------------------------------------------------------------------ 人格 ----
    def _setup_active_persona_workspace(self, load_history: bool = True):
        """为新人格自动创建专属主对话，并让当前会话指向它。"""
        persona = active_persona_name(self.cfg)
        main_id = self.memory.ensure_main_conversation(persona)
        self.current_conversation_id = main_id
        self.core.current_conversation_id = main_id
        meta = load_persona_meta(self.cfg, persona)
        # 迁移旧版“Nori 头像”上传：没有本人格头像时自动设为默认
        if not meta.get("avatar"):
            legacy = self.cfg.data_dir / "avatars" / "nori_avatar.png"
            if legacy.exists():
                meta["avatar"] = str(legacy)
                save_persona_meta(self.cfg, persona, meta)
        self.chat.set_agent_name(meta.get("agent_name") or persona)
        self.chat.set_avatar("agent", meta.get("avatar", ""))
        self.chat.set_user_name(str(self.cfg.gui.get("user_name", "") or "主人"))
        self.chat.set_history_personas(list_personas(self.cfg), persona)
        self._refresh_history_page(persona)
        if load_history:
            self._load_conversation_messages(main_id)

    def _load_conversation_messages(self, conv_id: int):
        conv = self.memory.get_conversation(conv_id)
        if not conv:
            return
        persona = conv.get("persona", active_persona_name(self.cfg))
        messages = self.memory.get_recent_messages(200, persona=persona,
                                                   conversation_id=conv_id)
        self.chat.clear_chat()
        self.chat.set_chat_history(messages)
        self.chat.set_current_conversation_label(conv.get("title", ""))

    def _refresh_history_page(self, persona: str):
        rows = self.memory.list_conversations(persona)
        self.chat.set_conversations(rows, self.current_conversation_id)
        current = self.memory.get_conversation(self.current_conversation_id or 0)
        self.chat.set_current_conversation_label(current.get("title", "未选择") if current else "未选择")

    def _refresh_persona_page(self):
        names = list_personas(self.cfg)
        active = active_persona_name(self.cfg)
        self.chat.set_persona_list(names, active)
        self.chat.set_persona_text(
            load_persona_text(self.cfg), active, str(persona_path(self.cfg, active)))

    @Slot(str, str)
    def on_persona_save(self, name: str, text: str):
        try:
            saved_name, path = save_persona_text(self.cfg, text, name=name)
            self._refresh_persona_page()
            self.chat.append_system(f"✅ 人格“{saved_name}”已保存到 {path}，下一条消息开始生效")
        except Exception as e:
            self.chat.append_system(f"⚠ 保存人格失败：{e}")

    @Slot(str, str)
    def on_persona_new(self, name: str, text: str):
        try:
            if not text.strip():
                self.chat.append_system("⚠ 新建人格内容不能为空")
                return
            create_persona(self.cfg, text, name)
            self._refresh_persona_page()
            self._setup_active_persona_workspace(load_history=True)
            self.chat.append_system(f"✅ 已新建并切换到人格“{name}”，已创建专属历史对话区")
        except Exception as e:
            self.chat.append_system(f"⚠ 新建人格失败：{e}")

    @Slot(str, str)
    def on_persona_import(self, name: str, text: str):
        try:
            create_persona(self.cfg, text, name)
            self._refresh_persona_page()
            self._setup_active_persona_workspace(load_history=True)
            self.chat.append_system(f"📂 已导入 .md 并切换到人格“{name}”，已创建专属历史对话区")
        except Exception as e:
            self.chat.append_system(f"⚠ 导入人格失败：{e}")

    @Slot(str)
    def on_persona_switch(self, name: str):
        try:
            set_active_persona(self.cfg, name)
            self._refresh_persona_page()
            self._setup_active_persona_workspace(load_history=True)
            self.chat.append_system(f"🔄 已切换人格：{name}，已加载该人格的专属历史")
        except Exception as e:
            self.chat.append_system(f"⚠ 切换人格失败：{e}")
            self._refresh_persona_page()

    @Slot(str)
    def on_persona_reset(self, name: str):
        try:
            reset_persona_to_default(self.cfg, name=name)
            self._refresh_persona_page()
            self.chat.append_system(f"↩️ 人格“{name}”已恢复为默认 Nori 人格（persona/Nori.md）")
        except Exception as e:
            self.chat.append_system(f"⚠ 恢复默认人格失败：{e}")

    @Slot(str)
    def on_persona_delete(self, name: str):
        try:
            active = delete_persona(self.cfg, name)
            self._refresh_persona_page()
            self.chat.append_system(f"🗑 已删除人格“{name}”，当前人格：{active}")
        except Exception as e:
            self.chat.append_system(f"⚠ 删除人格失败：{e}")
            self._refresh_persona_page()

    # ------------------------------------------------------------------ 聊天记录 ----
    @Slot(str)
    def on_history_refresh(self, persona: str):
        try:
            self._refresh_history_page(persona or active_persona_name(self.cfg))
        except Exception as e:
            self.chat.append_system(f"⚠ 刷新聊天记录失败：{e}")

    @Slot(int)
    def on_conversation_open(self, conv_id: int):
        try:
            conv = self.memory.get_conversation(int(conv_id))
            if not conv:
                self.chat.append_system("⚠ 会话不存在")
                return
            self.current_conversation_id = int(conv_id)
            self.core.current_conversation_id = int(conv_id)
            self._load_conversation_messages(int(conv_id))
            self._refresh_history_page(conv.get("persona", active_persona_name(self.cfg)))
            self.chat.append_system(f"已打开会话：{conv.get('title','')}")
        except Exception as e:
            self.chat.append_system(f"⚠ 打开会话失败：{e}")

    @Slot(str)
    def on_conversation_new(self, persona: str):
        try:
            conv_id = self.memory.create_conversation(persona)
            self.current_conversation_id = conv_id
            self.core.current_conversation_id = conv_id
            self._load_conversation_messages(conv_id)
            self._refresh_history_page(persona)
            self.chat.append_system(f"✅ 已为 {persona} 新建对话")
        except Exception as e:
            self.chat.append_system(f"⚠ 新建对话失败：{e}")

    @Slot(int, str)
    def on_conversation_rename(self, conv_id: int, title: str):
        try:
            if self.memory.rename_conversation(int(conv_id), title):
                conv = self.memory.get_conversation(int(conv_id))
                self._refresh_history_page(conv.get("persona", active_persona_name(self.cfg)) if conv else active_persona_name(self.cfg))
                self.chat.append_system(f"✅ 已重命名：{title}")
            else:
                self.chat.append_system("⚠ 主对话不能重命名或会话不存在")
        except Exception as e:
            self.chat.append_system(f"⚠ 重命名失败：{e}")

    @Slot(int)
    def on_conversation_delete(self, conv_id: int):
        try:
            if self.memory.delete_conversation(int(conv_id)):
                self.chat.append_system(f"🗑 已删除会话 #{conv_id}")
                if self.current_conversation_id == int(conv_id):
                    self._setup_active_persona_workspace(load_history=True)
                else:
                    self._refresh_history_page(active_persona_name(self.cfg))
            else:
                self.chat.append_system("⚠ 主对话不可删除")
        except Exception as e:
            self.chat.append_system(f"⚠ 删除会话失败：{e}")

    # ------------------------------------------------------------------ 记忆 ----
    def _refresh_memory_page(self, query: str, mem_type: str):
        rows = self.memory.list_memories(limit=300,
                                         mem_type=None if mem_type == "全部" else mem_type,
                                         query=query)
        self.chat.set_memories(rows)
        self.chat.set_rules(self.memory.list_rules(limit=200))

    @Slot(str, str)
    def on_memory_refresh(self, query: str, mem_type: str):
        try:
            self._refresh_memory_page(query, mem_type)
            n = self.memory_table_count()
            self.chat.append_system(f"🧠 记忆刷新完成：显示 {n} 条")
        except Exception as e:
            self.chat.append_system(f"⚠ 刷新记忆失败：{e}")

    def memory_table_count(self) -> int:
        return self.chat.memory_table.rowCount()

    @Slot(str, str, float)
    def on_memory_add(self, content: str, mem_type: str, importance: float):
        try:
            mem_id = self.memory.add_memory(content, mem_type=mem_type,
                                            importance=importance, source="gui")
            if mem_id is None:
                self.chat.append_system("⚠ 该记忆已存在，未重复添加")
            else:
                self.chat.append_system(f"✅ 已添加记忆 #{mem_id}")
            self._refresh_memory_page(self.chat.mem_search.text().strip(),
                                      self.chat.mem_type_combo.currentText())
        except Exception as e:
            self.chat.append_system(f"⚠ 添加记忆失败：{e}")

    @Slot(int, str, str, float)
    def on_memory_update(self, mem_id: int, content: str, mem_type: str, importance: float):
        try:
            if self.memory.update_memory(mem_id, content=content, mem_type=mem_type,
                                         importance=importance):
                self.chat.append_system(f"✅ 已更新记忆 #{mem_id}")
            else:
                self.chat.append_system(f"⚠ 记忆 #{mem_id} 不存在")
            self._refresh_memory_page(self.chat.mem_search.text().strip(),
                                      self.chat.mem_type_combo.currentText())
        except Exception as e:
            self.chat.append_system(f"⚠ 更新记忆失败：{e}")

    @Slot(int)
    def on_memory_delete(self, mem_id: int):
        try:
            if self.memory.delete_memory(mem_id):
                self.chat.append_system(f"🗑 已删除记忆 #{mem_id}")
            else:
                self.chat.append_system(f"⚠ 记忆 #{mem_id} 不存在")
            self._refresh_memory_page(self.chat.mem_search.text().strip(),
                                      self.chat.mem_type_combo.currentText())
        except Exception as e:
            self.chat.append_system(f"⚠ 删除记忆失败：{e}")

    @Slot(int)
    def on_memory_rule_toggle(self, rule_id: int):
        try:
            row = self.memory.list_rules(limit=1000)
            target = next((r for r in row if r["id"] == rule_id), None)
            if target is None:
                self.chat.append_system("⚠ 规则不存在")
                return
            enabled = not bool(target["enabled"])
            self.memory.set_rule_enabled(rule_id, enabled)
            self.chat.append_system(f"{'✅ 已启用规则' if enabled else '⛔ 已停用规则'} #{rule_id}")
            self._refresh_memory_page(self.chat.mem_search.text().strip(),
                                      self.chat.mem_type_combo.currentText())
        except Exception as e:
            self.chat.append_system(f"⚠ 切换规则失败：{e}")

    @Slot(int)
    def on_memory_rule_delete(self, rule_id: int):
        try:
            if self.memory.delete_rule(rule_id):
                self.chat.append_system(f"🗑 已删除规则 #{rule_id}")
            else:
                self.chat.append_system("⚠ 规则不存在")
            self._refresh_memory_page(self.chat.mem_search.text().strip(),
                                      self.chat.mem_type_combo.currentText())
        except Exception as e:
            self.chat.append_system(f"⚠ 删除规则失败：{e}")

    # ------------------------------------------------------------------ MCP/Skills ----
    def _refresh_mcp_page(self):
        self.chat.set_mcp_servers(self.mcp_manager.list_servers())
        self.chat.set_skills(self.mcp_manager.list_skills())

    @Slot()
    def on_mcp_refresh(self):
        try:
            self._refresh_mcp_page()
            self.chat.append_system("🔌 MCP / Skills 列表已刷新")
        except Exception as e:
            self.chat.append_system(f"⚠ 刷新 MCP/Skills 失败：{e}")

    @Slot(str, str, str, str, str)
    def on_mcp_add(self, name: str, transport: str, url: str, command: str, args: str):
        try:
            if self.mcp_manager.add_server(name, transport, url, command, args):
                self._refresh_mcp_page()
                self.chat.append_system(f"✅ 已添加 MCP：{name}")
            else:
                self.chat.append_system(f"⚠ MCP {name} 已存在")
        except Exception as e:
            self.chat.append_system(f"⚠ 添加 MCP 失败：{e}")

    @Slot(str)
    def on_mcp_import(self, path: str):
        try:
            n = self.mcp_manager.import_server_config(path)
            self._refresh_mcp_page()
            self.chat.append_system(f"📂 已导入 {n} 个 MCP 服务器")
        except Exception as e:
            self.chat.append_system(f"⚠ 导入 MCP 失败：{e}")

    @Slot(str)
    def on_mcp_toggle(self, name: str):
        s = self.mcp_manager.get_server(name)
        if s:
            self.mcp_manager.set_server_enabled(name, not s.get("enabled"))
            self._refresh_mcp_page()
            self.chat.append_system(f"🔌 MCP {name} 已{'启用' if not s.get('enabled') else '停用'}")

    @Slot(str)
    def on_mcp_delete(self, name: str):
        self.mcp_manager.remove_server(name)
        self._refresh_mcp_page()
        self.chat.append_system(f"🗑 已删除 MCP：{name}")

    @Slot(str)
    def on_skill_import(self, path: str):
        try:
            if self.mcp_manager.import_skill(path):
                self._refresh_mcp_page()
                self.chat.append_system(f"🧩 已导入 Skill：{Path(path).name}")
            else:
                self.chat.append_system("⚠ 未找到 SKILL.md，导入失败")
        except Exception as e:
            self.chat.append_system(f"⚠ 导入 Skill 失败：{e}")

    @Slot(str)
    def on_skill_toggle(self, name: str):
        current = next((s for s in self.mcp_manager.list_skills() if s.get("name") == name), None)
        enabled = not (current or {}).get("enabled", True)
        self.mcp_manager.set_skill_enabled(name, enabled)
        self._refresh_mcp_page()
        self.chat.append_system(f"🧩 Skill {name} 已{'启用' if enabled else '停用'}")

    @Slot(str)
    def on_skill_delete(self, name: str):
        self.mcp_manager.remove_skill(name)
        self._refresh_mcp_page()
        self.chat.append_system(f"🗑 已删除 Skill：{name}")

    # ------------------------------------------------------------------ 服务 ----
    @Slot(str)
    def on_service_action(self, action: str):
        try:
            if action == "start_heart":
                ok = self.services.start_heart(skip_live2d=not self.enable_pet)
                self.chat.append_system("✅ Heart 已启动（无窗口）" if ok else "⚠ Heart 启动失败，请看控制台日志")
            elif action == "stop_heart":
                ok = self.services.stop_heart()
                self.chat.append_system("■ Heart 已停止" if ok else "⚠ Heart 停止失败")
            elif action == "start_gsv":
                ok = self.services.start_gpt_sovits()
                self.chat.append_system(
                    "✅ GPT-SoVITS 正在启动，约 1 分钟后就绪（Nori 音色）" if ok
                    else "⚠ GPT-SoVITS 启动失败，请看控制台日志")
            elif action == "stop_gsv":
                ok = self.services.stop_gpt_sovits()
                if ok:
                    self.chat.append_system(
                        "■ GPT-SoVITS 已停止；语音引擎暂停，消息会排队，重新启动后自动恢复")
                    self.tts = None
                    self.tts_name = "无"
                else:
                    self.chat.append_system(
                        "⚠ 该 GPT-SoVITS 不是本面板启动的，请到日志目录关闭外部进程")
            else:
                return
        except Exception as e:
            self.chat.append_system(f"⚠ 服务操作失败：{e}")
        self._refresh_service_status()
        self.chat._refresh_console()

    # ------------------------------------------------------------------ Live2D 模型 ----
    def _refresh_live2d_models(self, announce: bool = True):
        if not self.live2d or not self.live2d_ready:
            if announce:
                self.chat.append_system("⚠ Live2D 未连接，无法读取模型列表")
            return
        data = self.live2d.list_models()
        models = data.get("models", []) if isinstance(data, dict) else []
        current = data.get("current", "") if isinstance(data, dict) else ""
        self.chat.set_live2d_models(models, current)
        if hasattr(self.live2d, "get_state"):
            try:
                state = self.live2d.get_state()
                scale = float(state.get("scale", 1.0) or 1.0)
                self.chat.scale_slider.blockSignals(True)
                self.chat.scale_slider.setValue(int(round(max(0.5, min(2.0, scale)) * 100)))
                self.chat.scale_label.setText(f"{scale:.2f}x")
                self.chat.scale_slider.blockSignals(False)
            except Exception:
                pass
        if announce:
            self.chat.append_system(
                f"🔄 Live2D 模型列表已刷新：{len(models)} 个模型，当前 {current or '未知'}")

    @Slot()
    def on_live2d_list_models(self):
        try:
            self._refresh_live2d_models(announce=True)
        except Exception as e:
            self.chat.append_system(f"⚠ 刷新 Live2D 模型列表失败：{e}")

    @Slot(str)
    def on_live2d_switch_model(self, model_path: str):
        if not self.live2d or not self.live2d_ready:
            self.chat.append_system("⚠ Live2D 未连接，无法切换模型")
            return
        try:
            self.live2d.switch_model(model_path)
            self.chat.append_system(f"🔄 已加载 Live2D 模型：{model_path}，角色窗口正在重新加载")
            QTimer.singleShot(5000, lambda: self._refresh_live2d_models(announce=False))
        except Exception as e:
            self.chat.append_system(f"⚠ 切换 Live2D 模型失败：{e}")

    @Slot(str)
    def on_live2d_import_model(self, source: str):
        """从本地文件夹或 ZIP 导入 Live2D 模型到原生桌宠。"""
        if not self.live2d or not self.live2d_ready:
            self.chat.append_system("⚠ Live2D 未连接，无法导入模型")
            return
        try:
            imported = self.live2d.import_model(source)
            if not imported:
                self.chat.append_system("⚠ 模型导入完成，但没有识别到受支持的模型 ID")
                return
            self.chat.append_system(f"📦 已导入 Live2D 模型：{', '.join(imported)}")
            if imported:
                self.live2d.switch_model(imported[0])
                self.chat.append_system(f"🔄 已切换到模型：{imported[0]}")
            QTimer.singleShot(1500, lambda: self._refresh_live2d_models(announce=True))
        except Exception as e:
            self.chat.append_system(f"⚠ 导入 Live2D 模型失败：{e}")

    # ------------------------------------------------------------------ 完全退出 ----
    @Slot()
    def on_quit_requested(self):
        """完全退出：停止后台服务、关闭 Live2D 应用并退出本程序。"""
        logging.info("用户请求完全退出：停止所有后台服务")
        self._full_quit = True
        try:
            self.services.stop_heart()
        except Exception as e:
            logging.warning("退出时停止 Heart 失败：%s", e)
        try:
            self.services.stop_gpt_sovits()
        except Exception as e:
            logging.warning("退出时停止 GPT-SoVITS 失败：%s", e)
        if self.live2d:
            try:
                self.live2d.shutdown()
            except Exception as e:
                logging.warning("退出时关闭 Live2D 失败：%s", e)
        QTimer.singleShot(150, self.app.quit)

    # ------------------------------------------------------------------
    def show(self):
        if self.pet:
            self.pet.show()
        if self.cfg.gui.get("show_chat_on_start", True):
            self.chat.show()
            self.chat.raise_()
            self.chat.activateWindow()


def main():
    parser = argparse.ArgumentParser(description="Nori AI 桌面宠物")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("--no-pet", action="store_true", help="只显示对话框，不显示宠物窗口")
    parser.add_argument("--no-services", action="store_true",
                        help="不自动启动 Heart / GPT-SoVITS 后台服务")
    parser.add_argument("--no-splash", action="store_true", help="不显示启动加载界面")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.log_file)

    app = QApplication(sys.argv)
    app.setApplicationName("NoriLive2D")
    # 任务栏/标题栏使用 Nori 图标而不是默认 Python 图标：
    # 1) 进程级 AppUserModelID，让 Windows 任务栏把本进程当作独立应用；
    # 2) 全局窗口图标（标题栏、任务栏、Alt-Tab 都会用它）。
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Alorit.Nori.Live2DChat.1")
        except Exception:
            pass
    icon_path = PROJECT_ROOT / "gui" / "assets" / "nori_icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    # 有宠物窗口时，对话框关闭不代表退出；只有对话框时，关了窗口就退出
    app.setQuitOnLastWindowClosed(args.no_pet)

    splash = None
    if not args.no_splash:
        splash = SplashWindow()
        splash.set_progress(3, "正在读取配置…")
        splash.show()
        app.processEvents()

    try:
        controller = AppController(cfg, app, enable_pet=not args.no_pet,
                                   autostart_services=not args.no_services,
                                   progress=splash.set_progress if splash else None)
    except Exception:
        if splash:
            splash.finish()
        raise

    def _on_quit():
        try:
            controller.memory.close()
        except Exception:
            pass
        try:
            # 完全退出按钮已停过服务；普通关闭按配置决定是否停 heart
            if controller._full_quit or cfg.heart.get("stop_with_gui", False):
                controller.services.stop_heart()
        except Exception:
            pass

    app.aboutToQuit.connect(_on_quit)
    controller.show()
    if splash:
        # 让加载界面完成最后一帧绘制后自动关闭
        QTimer.singleShot(150, splash.finish)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
