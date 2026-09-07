"""Nori 统一控制台（本地 Qt 窗口）。

页签：聊天 / 人格 / 记忆 / 控制台 / 设置
"""
from __future__ import annotations

import html as _html
import json
import logging
import os
from datetime import datetime as _datetime
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QDesktopServices,
    QIcon,
    QMovie,
    QPainter,
    QPainterPath,
    QPixmap,
    QColor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gui.winstyle import apply_dark_title_bar
from utils.console_logs import collect_logs
from utils.stickers import (
    ensure_default_stickers,
    import_sticker,
    list_stickers,
)

STYLE = """
QWidget#ChatWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #060a18, stop:0.45 #0a1026, stop:1 #0d1230);
    font-family: "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 13px;
    color: #d7e3ff;
}
QLabel#HeaderTitle {
    font-size: 20px;
    font-weight: 900;
    color: #a7f3d0;
    padding: 2px 0;
    letter-spacing: 1px;
}
QLabel#StatusPill {
    background: rgba(15, 30, 58, 0.72);
    border: 1px solid rgba(103, 232, 249, 0.35);
    border-radius: 13px;
    padding: 4px 12px;
    color: #7dd3fc;
    font-size: 12px;
}
QTabWidget::pane {
    border: 1px solid rgba(103, 232, 249, 0.22);
    border-radius: 16px;
    background: rgba(10, 17, 38, 0.68);
    top: -1px;
}
QTabBar::tab {
    background: rgba(17, 26, 54, 0.62);
    border: 1px solid rgba(103, 232, 249, 0.18);
    border-bottom: none;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    padding: 8px 18px;
    margin-right: 3px;
    color: #8fa6d8;
    font-weight: 600;
}
QTabBar::tab:selected {
    background: #101b3a;
    color: #a7f3d0;
    border-color: rgba(167, 243, 208, 0.55);
    font-weight: 800;
}
QTabBar::tab:hover {
    background: #152246;
}
QTextBrowser#ChatLog {
    background: rgba(7, 12, 26, 0.78);
    border: 1px solid rgba(103, 232, 249, 0.28);
    border-radius: 18px;
    padding: 14px;
    selection-background-color: #123c54;
    selection-color: #eafff7;
}
QLabel {
    color: #cfe6ff;
    background: transparent;
}
QScrollArea#ChatScroll {
    background: rgba(7, 12, 26, 0.78);
    border: 1px solid rgba(103, 232, 249, 0.28);
    border-radius: 18px;
}
QScrollArea#ChatScroll > QWidget > QWidget {
    background: transparent;
}
QFrame#UserBubble {
    background: rgba(13, 32, 58, 0.92);
    border: 1px solid rgba(103, 232, 249, 0.75);
    border-right: 3px solid #38bdf8;
    border-radius: 14px 4px 14px 14px;
}
QFrame#AIBubble {
    background: rgba(24, 18, 50, 0.92);
    border: 1px solid rgba(167, 139, 250, 0.7);
    border-left: 3px solid #8b7cf6;
    border-radius: 4px 14px 14px 14px;
}
QLabel#BubbleText {
    background: transparent;
    padding: 2px;
    border: none;
}
QLabel#BubbleMeta {
    background: transparent;
    border: none;
}
QMessageBox {
    background: #0b1229;
}
QMessageBox QLabel {
    color: #d7e3ff;
}
QToolTip {
    background: #0b1229;
    color: #7dd3fc;
    border: 1px solid rgba(103, 232, 249, 0.4);
}
QLineEdit#MessageInput {
    background: rgba(10, 17, 36, 0.9);
    border: 1px solid rgba(103, 232, 249, 0.4);
    border-radius: 20px;
    padding: 10px 16px;
    font-size: 13px;
    color: #eafff7;
}
QLineEdit#MessageInput:focus {
    border: 1.5px solid #67e8f9;
    background: rgba(14, 24, 50, 0.95);
}
QPlainTextEdit, QLineEdit, QTableWidget, QListWidget {
    background: rgba(9, 15, 32, 0.92);
    border: 1px solid rgba(125, 211, 252, 0.28);
    border-radius: 12px;
    padding: 6px;
    color: #d7e3ff;
    selection-background-color: #123c54;
    selection-color: #eafff7;
}
QPlainTextEdit:focus, QLineEdit:focus {
    border: 1.5px solid #67e8f9;
}
QTableWidget {
    gridline-color: rgba(103, 232, 249, 0.12);
    alternate-background-color: rgba(16, 27, 58, 0.72);
}
QHeaderView::section {
    background: #101b3a;
    border: none;
    border-right: 1px solid rgba(103, 232, 249, 0.18);
    padding: 6px 8px;
    color: #7dd3fc;
    font-weight: 700;
}
QPushButton {
    background: rgba(14, 24, 50, 0.82);
    border: 1px solid rgba(125, 211, 252, 0.35);
    border-radius: 15px;
    padding: 7px 14px;
    color: #9fc6ff;
    font-weight: 600;
}
QPushButton:hover {
    background: #132246;
    border-color: #67e8f9;
    color: #eafff7;
}
QPushButton:pressed {
    background: #0d1b36;
}
QPushButton:disabled {
    color: #52638c;
    border-color: rgba(125, 211, 252, 0.15);
}
QPushButton#SendButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #10b981, stop:0.55 #22d3ee, stop:1 #38bdf8);
    color: #04121a;
    border: none;
    padding: 10px 24px;
    border-radius: 20px;
    font-weight: 800;
}
QPushButton#SendButton:hover {
    background: #2dd4bf;
}
QPushButton#SendButton:disabled {
    background: #1e3a4d;
    color: #6d8da8;
}
QPushButton#LikeButton {
    color: #6ee7b7;
    border-color: rgba(52, 211, 153, 0.45);
}
QPushButton#DislikeButton {
    color: #fda4af;
    border-color: rgba(251, 113, 133, 0.4);
}
QPushButton#SaveButton {
    background: rgba(68, 42, 10, 0.55);
    border-color: rgba(252, 211, 77, 0.5);
    color: #fcd34d;
}
QPushButton#PrimaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #22d3ee, stop:1 #818cf8);
    color: #04121a;
    border: none;
    font-weight: 800;
}
QPushButton#DangerButton {
    background: rgba(69, 18, 31, 0.6);
    border-color: rgba(251, 113, 133, 0.45);
    color: #fda4af;
}
QGroupBox#PanelBox {
    background: rgba(11, 20, 43, 0.66);
    border: 1px solid rgba(103, 232, 249, 0.22);
    border-radius: 16px;
    margin-top: 10px;
    padding: 14px 12px 10px 12px;
    font-weight: 700;
    color: #7dd3fc;
}
QGroupBox#PanelBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
}
QComboBox {
    background: rgba(10, 18, 38, 0.95);
    border: 1px solid rgba(125, 211, 252, 0.35);
    border-radius: 12px;
    padding: 5px 10px;
    color: #d7e3ff;
    min-width: 110px;
}
QComboBox:focus {
    border: 1px solid #67e8f9;
}
QComboBox QAbstractItemView {
    background: #0c1530;
    border: 1px solid rgba(103, 232, 249, 0.35);
    border-radius: 10px;
    color: #d7e3ff;
    selection-background-color: #123c54;
    selection-color: #eafff7;
}
QComboBox::item {
    color: #d7e3ff;
}
QComboBox::item:selected {
    color: #eafff7;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #1b2949;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #34d399, stop:0.5 #22d3ee, stop:1 #818cf8);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #a7f3d0;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QCheckBox {
    spacing: 6px;
    color: #9fc6ff;
}
QDoubleSpinBox {
    background: rgba(10, 18, 38, 0.95);
    border: 1px solid rgba(125, 211, 252, 0.35);
    border-radius: 10px;
    padding: 4px 8px;
    color: #d7e3ff;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #29406b;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3b5b96;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QMenu {
    background: #0c1530;
    border: 1px solid rgba(103, 232, 249, 0.35);
    border-radius: 10px;
    color: #d7e3ff;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: #123c54;
    color: #eafff7;
}
QMenu::separator {
    height: 1px;
    background: rgba(103, 232, 249, 0.2);
    margin: 4px 8px;
}
QListWidget#HistoryList {
    background: rgba(9, 15, 32, 0.92);
    border: 1px solid rgba(125, 211, 252, 0.28);
    border-radius: 14px;
    padding: 6px;
}
QListWidget#HistoryList::item {
    border-radius: 10px;
    margin: 2px 2px;
    padding: 2px;
}
QListWidget#HistoryList::item:hover {
    background: rgba(19, 34, 70, 0.85);
}
QListWidget#HistoryList::item:selected {
    background: rgba(18, 60, 84, 0.9);
    border: 1px solid rgba(103, 232, 249, 0.55);
}
QLabel#HistoryItemTitle {
    color: #eafff7;
    font-weight: 700;
    font-size: 14px;
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#HistoryItemTitleActive {
    color: #7dd3fc;
    font-weight: 800;
    font-size: 14px;
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#HistoryItemMeta {
    color: #8fa6d8;
    font-size: 11px;
    background: transparent;
    border: none;
    padding: 0;
}
"""


class MessageBubble(QWidget):
    """QQ/微信式聊天气泡：头像 + 名字/标签/时间 + 圆角气泡。"""

    def __init__(self, text: str, who: str, avatar: str, name_color: str,
                 align_right: bool, tag: str = "", font_size: int = 13,
                 image_paths: list[str] | None = None, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 2)
        outer.setSpacing(8)

        # 头像（图片自动裁成圆形，否则显示 emoji）
        avatar_label = QLabel(avatar if not Path(avatar).is_file() else "", self)
        avatar_label.setAlignment(Qt.AlignCenter)
        avatar_label.setFixedSize(36, 36)
        avatar_path = Path(avatar)
        if avatar_path.is_file():
            try:
                pix = QPixmap(str(avatar_path)).scaled(
                    34, 34, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                rounded = QPixmap(34, 34)
                rounded.fill(Qt.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.Antialiasing, True)
                clip = QPainterPath()
                clip.addEllipse(0, 0, 34, 34)
                painter.setClipPath(clip)
                painter.drawPixmap(0, 0, pix)
                painter.end()
                avatar_label.setPixmap(rounded)
            except Exception:
                avatar_label.setText("🧑" if align_right else "🐱")
            avatar_label.setStyleSheet("border-radius:18px; border:1px solid #38bdf8;")
        else:
            avatar_label.setStyleSheet(
                "background: rgba(15,30,58,0.9); border:1px solid #38bdf8;"
                "border-radius:18px; font-size:18px; color:#cfe6ff;")

        # 气泡
        bubble_frame = QFrame(self)
        bubble_frame.setObjectName("UserBubble" if align_right else "AIBubble")
        bubble_layout = QVBoxLayout(bubble_frame)
        bubble_layout.setContentsMargins(12, 8, 12, 10)
        bubble_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        name = QLabel(who, bubble_frame)
        name.setStyleSheet(f"color:{name_color}; font-weight:700; font-size:{max(10, font_size - 1)}px;")
        header.addWidget(name)
        if tag:
            tag_label = QLabel(tag, bubble_frame)
            tag_label.setStyleSheet(
                "color:#67e8f9; background:rgba(103,232,249,0.10);"
                "border:1px solid rgba(103,232,249,0.3); border-radius:8px;"
                "padding:1px 6px; font-size:9px; letter-spacing:1px;")
            header.addWidget(tag_label)
        header.addStretch(1)
        time_label = QLabel(_datetime.now().strftime("%H:%M"), bubble_frame)
        time_label.setStyleSheet("color:#7d8db5; font-size:10px;")
        header.addWidget(time_label)
        bubble_layout.addLayout(header)

        # 图片 / 表情包（先图后文字说明）
        for path in image_paths or []:
            bubble_layout.addWidget(self._make_image_label(path))

        text = (text or "").strip()
        if text:
            content = QLabel(text, bubble_frame)
            content.setObjectName("BubbleText")
            content.setWordWrap(True)
            content.setTextInteractionFlags(Qt.TextSelectableByMouse)
            content.setStyleSheet(f"color:#d7e3ff; font-size:{max(10, font_size)}px;")
            content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            bubble_layout.addWidget(content)

        bubble_frame.setMaximumWidth(620)
        bubble_frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        if align_right:
            outer.addStretch(1)
            outer.addWidget(bubble_frame)
            outer.addWidget(avatar_label)
        else:
            outer.addWidget(avatar_label)
            outer.addWidget(bubble_frame)
            outer.addStretch(1)

    @staticmethod
    def _make_image_label(path: str, max_w: int = 300, max_h: int = 240) -> QLabel:
        """生成聊天气泡里的图片缩略图（GIF 会循环播放）。"""
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "background: rgba(255,255,255,0.04);"
            "border: 1px solid rgba(103,232,249,0.35); border-radius: 12px;"
            "padding: 3px;")
        try:
            p = Path(path)
            pix = QPixmap(str(p))
            if pix.isNull() or pix.width() <= 0 or pix.height() <= 0:
                label.setText("🖼 无法预览图片")
                label.setMinimumSize(120, 80)
                return label
            size = pix.size()
            if size.width() > max_w or size.height() > max_h:
                size = size.scaled(max_w, max_h, Qt.KeepAspectRatio)
            label.setMaximumWidth(max_w)
            label.setMaximumHeight(max_h)

            if p.suffix.lower() == ".gif":
                movie = QMovie(str(p))
                if movie.isValid():
                    movie.setScaledSize(size)
                    label.setMovie(movie)
                    label._movie = movie  # 保持引用，避免被回收
                    movie.start()
                    label.setToolTip(f"{p.name}（GIF）\n{p}")
                    return label
            label.setPixmap(pix.scaled(size, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
            label.setToolTip(f"{p.name}\n{p}")
        except Exception:
            label.setText("🖼 无法预览图片")
            label.setMinimumSize(120, 80)
        return label


class _WheelGuard(QObject):
    """吞掉设置控件上的滚轮事件，但转发给设置滚动区，避免误改值又能正常滚动页面。"""

    def __init__(self, parent=None, scroll_area=None):
        super().__init__(parent)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            if self.scroll_area is not None:
                viewport = self.scroll_area.viewport()
                if viewport is not None:
                    QCoreApplication.sendEvent(viewport, event)
            return True
        return super().eventFilter(obj, event)


class ChatWindow(QWidget):
    send_requested = Signal(str)
    media_send_requested = Signal(object, str)  # image_paths(list[str]), caption
    feedback_requested = Signal(float)  # 1.0 赞 / -1.0 踩
    export_requested = Signal()
    tts_backend_requested = Signal(str)
    speed_requested = Signal(float)
    scale_requested = Signal(float)
    always_on_top_requested = Signal(bool)
    live2d_window_requested = Signal(str)  # show / hide / toggle
    save_settings_requested = Signal()
    quit_requested = Signal()
    font_size_requested = Signal(int)
    chat_font_size_requested = Signal(int)
    tts_status_refresh_requested = Signal()
    user_name_requested = Signal(str)
    agent_name_requested = Signal(str)
    agent_avatar_requested = Signal(str)
    avatar_requested = Signal(str, str)  # role(user/agent), image path
    context_compression_requested = Signal(str, int, int)  # mode, window, max_chars
    llm_config_requested = Signal(str, str, str)  # api_key, base_url, model
    llm_fetch_models_requested = Signal()          # 从当前提供商拉取模型列表
    search_config_requested = Signal(str)         # baidu api_key
    vision_config_requested = Signal(str, str, str, int)  # api_key, base_url, model, port
    tts_voice_switch_requested = Signal(str)      # voice name
    tts_voice_import_requested = Signal(str)      # source folder/zip
    tts_voice_export_requested = Signal(str)      # voice name
    voice_export_dir_requested = Signal(str)      # 语音包导出目录
    llm_model_rename_requested = Signal(str, str)  # old_name, new_name
    llm_model_delete_requested = Signal(str)       # model name
    memory_auto_review_requested = Signal(bool, int)  # enabled, minutes
    memory_review_now_requested = Signal()
    # 聊天记录（按人格 + 会话）
    history_refresh_requested = Signal(str)          # persona
    conversation_open_requested = Signal(int)        # conversation_id
    conversation_new_requested = Signal(str)         # persona
    conversation_rename_requested = Signal(int, str)
    conversation_delete_requested = Signal(int)
    # MCP / Skill
    mcp_refresh_requested = Signal()
    mcp_add_requested = Signal(str, str, str, str, str)  # name, transport, url, command, args
    mcp_import_requested = Signal(str)
    mcp_toggle_requested = Signal(str)
    mcp_delete_requested = Signal(str)
    skill_import_requested = Signal(str)
    skill_toggle_requested = Signal(str)
    skill_delete_requested = Signal(str)
    # 人格（多人格切换）
    persona_save_requested = Signal(str, str)    # name, text
    persona_new_requested = Signal(str, str)     # name, text
    persona_switch_requested = Signal(str)       # name
    persona_delete_requested = Signal(str)       # name
    persona_reset_requested = Signal(str)        # name
    persona_import_requested = Signal(str, str)  # name, text
    # Live2D 模型切换
    live2d_list_models_requested = Signal()
    live2d_switch_model_requested = Signal(str)
    live2d_import_model_requested = Signal(str)
    # 记忆
    memory_refresh_requested = Signal(str, str)
    memory_add_requested = Signal(str, str, float)
    memory_update_requested = Signal(int, str, str, float)
    memory_delete_requested = Signal(int)
    memory_rule_toggle_requested = Signal(int)
    memory_rule_delete_requested = Signal(int)
    # 服务控制台
    service_action_requested = Signal(str)

    def __init__(self, cfg, quit_on_close: bool = False, live2d_mode: bool = False):
        super().__init__()
        self.cfg = cfg
        self._quit_on_close = quit_on_close
        self.live2d_mode = live2d_mode
        self._editing_mem_id: int | None = None
        gui = cfg.gui
        self.setObjectName("ChatWindow")
        self.setWindowTitle("Nori 控制台")
        self.resize(int(gui.get("chat_width", 760)), int(gui.get("chat_height", 820)))
        self._font_size = int(gui.get("font_size", 13) or 13)
        self._chat_font_size = int(gui.get("chat_font_size", 15) or 15)
        self._user_name = str(gui.get("user_name", "") or "主人")
        self._agent_name = str(gui.get("agent_name", "Nori") or "Nori")
        self._user_avatar = str(gui.get("user_avatar", "") or "")
        self._agent_avatar = str(gui.get("agent_avatar", "") or "")
        self._voice_export_dir = str(gui.get("voice_export_dir", "") or "")
        self.setStyleSheet(self._style_for_font(self._font_size))
        self.setAcceptDrops(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # 头部：不再放标题文字（由系统标题栏承担），右上角 × 即完全退出
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addStretch(1)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("StatusPill")
        header.addWidget(self.status_label)
        self.tts_refresh_btn = QPushButton("🔄", self)
        self.tts_refresh_btn.setFixedWidth(34)
        self.tts_refresh_btn.setToolTip("重新检测 TTS 与后台服务状态")
        self.tts_refresh_btn.clicked.connect(lambda: self.tts_status_refresh_requested.emit())
        header.addWidget(self.tts_refresh_btn)
        root.addLayout(header)

        # 顶级页签：聊天 / 设置（人格、记忆、控制台统一收纳在设置里）
        self.tabs = QTabWidget(self)
        self.chat_page = QWidget(self)
        self.settings_page = QWidget(self)
        self.tabs.addTab(self.chat_page, "💬 聊天")
        self.tabs.addTab(self.settings_page, "⚙ 设置")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self._build_chat_page()
        self._console_notes: list[str] = []

        # 设置页：嵌套页签统一管理所有编辑/控制功能
        self.settings_tabs = QTabWidget(self.settings_page)
        self.settings_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.settings_tabs.currentChanged.connect(self._on_settings_tab_changed)
        self.settings_basic_page = QWidget(self.settings_page)
        self.history_page = QWidget(self.settings_page)
        self.persona_page = QWidget(self.settings_page)
        self.memory_page = QWidget(self.settings_page)
        self.mcp_page = QWidget(self.settings_page)
        self.console_page = QWidget(self.settings_page)
        self.settings_tabs.addTab(self.settings_basic_page, "🎛 基础设置")
        self.settings_tabs.addTab(self.history_page, "🗂 聊天记录")
        self.settings_tabs.addTab(self.persona_page, "📜 人格")
        self.settings_tabs.addTab(self.memory_page, "🧠 记忆")
        self.settings_tabs.addTab(self.mcp_page, "🔌 MCP / Skills")
        self.settings_tabs.addTab(self.console_page, "🖥️ 控制台")
        self.settings_layout = QVBoxLayout(self.settings_page)
        self.settings_layout.setContentsMargins(8, 8, 8, 8)

        self._build_basic_settings_page()
        self._build_history_page()
        self._build_persona_page()
        self._build_memory_page()
        self._build_mcp_page()
        self._build_console_page()

        # 设置页放进滚动区：窗口高度缩小时可上下滚动，内容不会被压坏
        self.settings_scroll = QScrollArea(self.settings_page)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.settings_scroll.setFrameShape(QFrame.NoFrame)
        self.settings_scroll.setWidget(self.settings_tabs)
        self.settings_layout.addWidget(self.settings_scroll)
        self._install_wheel_guard()

        # 让窗口高度可自由收缩（设置页内容不再撑起 1000+ 的最小高度）
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.setMinimumSize(480, 360)
        self._fit_to_screen()

        self._enabled = True

    def _fit_to_screen(self):
        """启动时若默认窗口超出屏幕，自动缩到可用区域内，避免“太长”。"""
        try:
            screen = self.screen() or QApplication_primary_screen()
            if screen is None:
                return
            geo = screen.availableGeometry()
            target_w = min(self.width(), max(400, geo.width() - 80))
            target_h = min(self.height(), max(320, geo.height() - 80))
            self.resize(target_w, target_h)
        except Exception:
            pass

    def _install_wheel_guard(self):
        """设置页内所有下拉框/滑条/数值框禁用滚轮修改，但滚轮仍可滚动设置页。"""
        self._wheel_guard = _WheelGuard(self, scroll_area=self.settings_scroll)
        types = (QComboBox, QSlider, QSpinBox, QDoubleSpinBox)
        for w in self.settings_tabs.findChildren(QWidget):
            if isinstance(w, types):
                w.installEventFilter(self._wheel_guard)

    def _install_combo_context_menu(self, combo: QComboBox, kind: str):
        """给下拉框加右键菜单：重命名 / 删除。"""
        combo.setContextMenuPolicy(Qt.CustomContextMenu)
        combo.customContextMenuRequested.connect(
            lambda pos, c=combo, k=kind: self._show_combo_context_menu(c, k, pos))

    def _show_combo_context_menu(self, combo: QComboBox, kind: str, pos):
        menu = QMenu(self)
        rename_action = menu.addAction("✏ 重命名")
        delete_action = menu.addAction("🗑 删除")
        action = menu.exec(combo.mapToGlobal(pos))
        if action is rename_action:
            self._on_combo_rename(combo, kind)
        elif action is delete_action:
            self._on_combo_delete(combo, kind)

    def _on_combo_rename(self, combo: QComboBox, kind: str):
        if kind == "llm":
            old = combo.currentText().strip()
            if not old:
                return
            new, ok = QInputDialog.getText(self, "重命名 LLM 模型", "新模型名称：", text=old)
            if ok and new.strip():
                self.llm_model_rename_requested.emit(old, new.strip())

    def _on_combo_delete(self, combo: QComboBox, kind: str):
        if kind == "llm":
            name = combo.currentText().strip()
            if not name:
                return
            if QMessageBox.question(
                    self, "删除 LLM 模型", f"确定从模型列表删除“{name}”吗？") != QMessageBox.Yes:
                return
            self.llm_model_delete_requested.emit(name)

    def _style_for_font(self, size: int) -> str:
        return STYLE.replace("font-size: 13px;", f"font-size: {size}px;", 1)

    def apply_font_size(self, size: int):
        size = max(10, min(18, int(size)))
        self._font_size = size
        self.setStyleSheet(self._style_for_font(size))
        idx = self.font_combo.findData(size)
        if idx >= 0:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(idx)
            self.font_combo.blockSignals(False)

    def apply_chat_font_size(self, size: int):
        size = max(12, min(22, int(size)))
        self._chat_font_size = size
        idx = self.chat_font_combo.findData(size)
        if idx >= 0:
            self.chat_font_combo.blockSignals(True)
            self.chat_font_combo.setCurrentIndex(idx)
            self.chat_font_combo.blockSignals(False)

    def set_avatar(self, role: str, path: str):
        path = (path or "").strip()
        if role == "user":
            self._user_avatar = path
            self.user_avatar_label.setText(Path(path).name if path else "🧑（默认）")
        elif role in ("nori", "agent"):
            self._agent_avatar = path
            self.agent_avatar_label.setText(Path(path).name if path else "🐱（默认）")

    def set_user_name(self, name: str):
        name = (name or "").strip() or "主人"
        self._user_name = name
        self.user_name_edit.blockSignals(True)
        self.user_name_edit.setText(name)
        self.user_name_edit.blockSignals(False)

    def set_agent_name(self, name: str):
        name = (name or "").strip() or "Nori"
        self._agent_name = name
        self.agent_name_edit.blockSignals(True)
        self.agent_name_edit.setText(name)
        self.agent_name_edit.blockSignals(False)

    # ------------------------------------------------------------------ 聊天页
    def _build_chat_page(self):
        layout = QVBoxLayout(self.chat_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 聊天记录：QQ/微信式气泡流
        self.log = QScrollArea(self.chat_page)
        self.log.setObjectName("ChatScroll")
        self.log.setWidgetResizable(True)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log_content = QWidget(self.log)
        self.log_content.setObjectName("ChatScrollContent")
        self.bubble_layout = QVBoxLayout(self.log_content)
        self.bubble_layout.setContentsMargins(8, 8, 8, 8)
        self.bubble_layout.setSpacing(8)
        self.bubble_layout.addStretch(1)
        self.log.setWidget(self.log_content)
        layout.addWidget(self.log, 1)

        # 输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.image_btn = QPushButton("📷", self.chat_page)
        self.image_btn.setToolTip("发送图片（可多选 png / jpg / webp / gif / bmp）")
        self.image_btn.setFixedWidth(42)
        self.image_btn.clicked.connect(self._on_send_images)
        input_row.addWidget(self.image_btn)

        self.sticker_btn = QPushButton("😊", self.chat_page)
        self.sticker_btn.setToolTip("表情包")
        self.sticker_btn.setFixedWidth(42)
        self.sticker_btn.clicked.connect(self._show_sticker_menu)
        input_row.addWidget(self.sticker_btn)

        self.input = QLineEdit(self.chat_page)
        self.input.setObjectName("MessageInput")
        self.input.setPlaceholderText("输入消息，回车发送；📷 发图片，😊 发表情包…")
        self.input.returnPressed.connect(self._on_send)
        input_row.addWidget(self.input, 1)

        self.send_btn = QPushButton("发送", self.chat_page)
        self.send_btn.setObjectName("SendButton")
        self.send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        # 反馈行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.like_btn = QPushButton("👍 说得好", self.chat_page)
        self.like_btn.setObjectName("LikeButton")
        self.like_btn.clicked.connect(lambda: self.feedback_requested.emit(1.0))
        btn_row.addWidget(self.like_btn)

        self.dislike_btn = QPushButton("👎 别这样", self.chat_page)
        self.dislike_btn.setObjectName("DislikeButton")
        self.dislike_btn.clicked.connect(lambda: self.feedback_requested.emit(-1.0))
        btn_row.addWidget(self.dislike_btn)

        self.export_btn = QPushButton("📦 导出训练数据", self.chat_page)
        self.export_btn.clicked.connect(self.export_requested)
        btn_row.addWidget(self.export_btn)

        btn_row.addStretch(1)
        self.settings_btn = QPushButton("⚙ 设置", self.chat_page)
        self.settings_btn.setCheckable(True)
        self.settings_btn.toggled.connect(self._toggle_settings)
        btn_row.addWidget(self.settings_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------ 人格页
    def _build_persona_page(self):
        layout = QVBoxLayout(self.persona_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        box = QGroupBox("人格切换与编辑（.md，保存后立即生效）", self.persona_page)
        box.setObjectName("PanelBox")
        bl = QVBoxLayout(box)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel("当前人格", self.persona_page))
        self.persona_combo = QComboBox(self.persona_page)
        self.persona_combo.currentIndexChanged.connect(self._on_persona_combo)
        top.addWidget(self.persona_combo, 1)
        self.persona_new_btn = QPushButton("➕ 新建", self.persona_page)
        self.persona_new_btn.clicked.connect(self._on_new_persona)
        top.addWidget(self.persona_new_btn)
        self.persona_import_btn = QPushButton("📂 导入 .md", self.persona_page)
        self.persona_import_btn.clicked.connect(self._on_import_persona)
        top.addWidget(self.persona_import_btn)
        self.persona_delete_btn = QPushButton("🗑 删除", self.persona_page)
        self.persona_delete_btn.setObjectName("DangerButton")
        self.persona_delete_btn.clicked.connect(self._on_delete_persona)
        top.addWidget(self.persona_delete_btn)
        bl.addLayout(top)

        self.persona_path_label = QLabel("", self.persona_page)
        self.persona_path_label.setStyleSheet("color:#8fa6d8; font-size:12px;")
        bl.addWidget(self.persona_path_label)

        self.persona_edit = QPlainTextEdit(self.persona_page)
        self.persona_edit.setPlaceholderText("在这里编辑 Nori 的人格提示词（Markdown）…")
        self.persona_edit.textChanged.connect(lambda: setattr(self, "_persona_dirty", True))
        bl.addWidget(self.persona_edit, 1)

        hint = QLabel(
            "提示：当前 .md 就是完整的 System Prompt，不会额外拼接 config.yaml 的人设；"
            "可用占位符：{{time}} {{memory}} {{rules}} {{summary}}。"
            "切换人格后下一条消息立即使用新人设。",
            self.persona_page)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6d8; font-size:12px;")
        bl.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.persona_save_btn = QPushButton("💾 保存", self.persona_page)
        self.persona_save_btn.setObjectName("PrimaryButton")
        self.persona_save_btn.clicked.connect(self._on_save_persona)
        row.addWidget(self.persona_save_btn)
        self.persona_reset_btn = QPushButton("↩️ 恢复默认", self.persona_page)
        self.persona_reset_btn.setObjectName("DangerButton")
        self.persona_reset_btn.clicked.connect(self._on_reset_persona)
        row.addWidget(self.persona_reset_btn)
        row.addStretch(1)
        bl.addLayout(row)

        layout.addWidget(box)
        self._persona_dirty = False
        self._persona_active = ""

    def _current_persona_name(self) -> str:
        return self.persona_combo.currentData() or self._persona_active

    def _on_persona_combo(self, index: int):
        name = self.persona_combo.itemData(index)
        if not name or name == self._persona_active:
            return
        if self._persona_dirty:
            ret = QMessageBox.question(
                self, "未保存的修改",
                f"人格“{self._persona_active}”有未保存的修改，切换前要保存吗？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save)
            if ret == QMessageBox.Cancel:
                self._restore_persona_combo(self._persona_active)
                return
            if ret == QMessageBox.Save:
                self.persona_save_requested.emit(
                    self._persona_active, self.persona_edit.toPlainText())
        self.persona_switch_requested.emit(name)

    def _restore_persona_combo(self, name: str):
        idx = self.persona_combo.findData(name)
        if idx >= 0:
            self.persona_combo.blockSignals(True)
            self.persona_combo.setCurrentIndex(idx)
            self.persona_combo.blockSignals(False)

    def _on_save_persona(self):
        name = self._current_persona_name()
        if not name:
            return
        self.persona_save_requested.emit(name, self.persona_edit.toPlainText())

    def _on_new_persona(self):
        name, ok = QInputDialog.getText(
            self, "新建人格", "人格名称（保存为 persona/<名称>.md）：")
        name = (name or "").strip()
        if not ok or not name:
            return
        self.persona_new_requested.emit(name, self.persona_edit.toPlainText())

    def _on_import_persona(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入人格提示词（.md）", str(self.cfg.root),
            "Markdown (*.md);;Text (*.txt);;All files (*.*)")
        if not path:
            return
        try:
            text = open(path, "r", encoding="utf-8").read()
        except UnicodeDecodeError:
            text = open(path, "r", encoding="gbk", errors="replace").read()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        name = Path(path).stem.strip() or "imported"
        if QMessageBox.question(
                self, "导入人格",
                f"将以“{name}”新建/覆盖人格并切换过去，继续吗？") != QMessageBox.Yes:
            return
        self.persona_import_requested.emit(name, text)

    def _on_reset_persona(self):
        name = self._current_persona_name()
        if not name:
            return
        if QMessageBox.question(
                self, "恢复默认人格",
                f"将用默认 Nori 人格（persona/Nori.md）覆盖“{name}”，确定吗？") \
                != QMessageBox.Yes:
            return
        self.persona_reset_requested.emit(name)

    def _on_delete_persona(self):
        name = self._current_persona_name()
        if not name:
            return
        if QMessageBox.question(
                self, "删除人格", f"确定删除人格“{name}”吗？此操作不可撤销。") \
                != QMessageBox.Yes:
            return
        self.persona_delete_requested.emit(name)

    # ------------------------------------------------------------------ 记忆页
    def _build_memory_page(self):
        layout = QVBoxLayout(self.memory_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 搜索 / 过滤
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_row.addWidget(QLabel("搜索", self.memory_page))
        self.mem_search = QLineEdit(self.memory_page)
        self.mem_search.setPlaceholderText("输入关键词，回车搜索…")
        self.mem_search.returnPressed.connect(self._emit_memory_refresh)
        search_row.addWidget(self.mem_search, 1)
        self.mem_type_combo = QComboBox(self.memory_page)
        self.mem_type_combo.addItems(["全部", "episodic", "semantic"])
        self.mem_type_combo.currentIndexChanged.connect(self._emit_memory_refresh)
        search_row.addWidget(self.mem_type_combo)
        self.mem_refresh_btn = QPushButton("🔄 刷新", self.memory_page)
        self.mem_refresh_btn.clicked.connect(self._emit_memory_refresh)
        search_row.addWidget(self.mem_refresh_btn)
        layout.addLayout(search_row)

        # 定时回顾与相似记忆合并
        review_row = QHBoxLayout()
        review_row.setSpacing(6)
        self.mem_auto_review_check = QCheckBox("定时记忆回顾（LLM 总结 + 合并相似记忆）", self.memory_page)
        self.mem_auto_review_check.setChecked(bool(self.cfg.memory.get("auto_review_enabled", True)))
        self.mem_auto_review_check.toggled.connect(self._emit_auto_review)
        review_row.addWidget(self.mem_auto_review_check)
        review_row.addWidget(QLabel("间隔（分钟）", self.memory_page))
        self.mem_review_spin = QSpinBox(self.memory_page)
        self.mem_review_spin.setRange(5, 240)
        self.mem_review_spin.setValue(int(self.cfg.memory.get("auto_review_minutes", 30)))
        self.mem_review_spin.valueChanged.connect(self._emit_auto_review)
        review_row.addWidget(self.mem_review_spin)
        self.mem_review_now_btn = QPushButton("🧹 立即回顾/合并", self.memory_page)
        self.mem_review_now_btn.setObjectName("PrimaryButton")
        self.mem_review_now_btn.clicked.connect(self.memory_review_now_requested)
        review_row.addWidget(self.mem_review_now_btn)
        review_row.addStretch(1)
        layout.addLayout(review_row)

        # 新增 / 编辑
        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        self.mem_new_content = QLineEdit(self.memory_page)
        self.mem_new_content.setPlaceholderText("新增记忆内容（双击下方条目可编辑）…")
        edit_row.addWidget(self.mem_new_content, 1)
        self.mem_new_type = QComboBox(self.memory_page)
        self.mem_new_type.addItems(["episodic", "semantic"])
        edit_row.addWidget(self.mem_new_type)
        self.mem_new_imp = QDoubleSpinBox(self.memory_page)
        self.mem_new_imp.setRange(0.0, 1.0)
        self.mem_new_imp.setSingleStep(0.05)
        self.mem_new_imp.setValue(0.6)
        self.mem_new_imp.setPrefix("重要度 ")
        edit_row.addWidget(self.mem_new_imp)
        self.mem_add_btn = QPushButton("＋ 新增", self.memory_page)
        self.mem_add_btn.setObjectName("PrimaryButton")
        self.mem_add_btn.clicked.connect(self._on_memory_add)
        edit_row.addWidget(self.mem_add_btn)
        self.mem_update_btn = QPushButton("✏ 更新选中", self.memory_page)
        self.mem_update_btn.clicked.connect(self._on_memory_update)
        edit_row.addWidget(self.mem_update_btn)
        self.mem_delete_btn = QPushButton("🗑 删除选中", self.memory_page)
        self.mem_delete_btn.setObjectName("DangerButton")
        self.mem_delete_btn.clicked.connect(self._on_memory_delete)
        edit_row.addWidget(self.mem_delete_btn)
        layout.addLayout(edit_row)

        # 记忆表
        self.memory_table = QTableWidget(0, 6, self.memory_page)
        self.memory_table.setMinimumHeight(220)
        self.memory_table.setHorizontalHeaderLabels(["ID", "类型", "内容", "重要性", "访问", "时间"])
        self.memory_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.memory_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.memory_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.memory_table.setAlternatingRowColors(True)
        self.memory_table.verticalHeader().setVisible(False)
        self.memory_table.doubleClicked.connect(self._on_memory_row_activated)
        header = self.memory_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.memory_table, 1)

        # 行为规则
        rules_box = QGroupBox("行为规则（由反思整合学习到）", self.memory_page)
        rules_box.setObjectName("PanelBox")
        rl = QVBoxLayout(rules_box)
        rules_row = QHBoxLayout()
        self.rules_list = QListWidget(self.memory_page)
        rl.addWidget(self.rules_list)
        self.rule_toggle_btn = QPushButton("启用/停用", self.memory_page)
        self.rule_toggle_btn.clicked.connect(self._on_rule_toggle)
        rules_row.addWidget(self.rule_toggle_btn)
        self.rule_delete_btn = QPushButton("删除规则", self.memory_page)
        self.rule_delete_btn.setObjectName("DangerButton")
        self.rule_delete_btn.clicked.connect(self._on_rule_delete)
        rules_row.addWidget(self.rule_delete_btn)
        rules_row.addStretch(1)
        rl.addLayout(rules_row)
        layout.addWidget(rules_box)

    def _emit_memory_refresh(self):
        self.memory_refresh_requested.emit(
            self.mem_search.text().strip(), self.mem_type_combo.currentText())

    def _emit_auto_review(self):
        self.memory_auto_review_requested.emit(
            self.mem_auto_review_check.isChecked(), self.mem_review_spin.value())

    def _on_memory_add(self):
        content = self.mem_new_content.text().strip()
        if not content:
            QMessageBox.information(self, "新增记忆", "请先输入记忆内容。")
            return
        self.memory_add_requested.emit(
            content, self.mem_new_type.currentText(), self.mem_new_imp.value())
        self.mem_new_content.clear()
        self._editing_mem_id = None

    def _on_memory_update(self):
        mem_id = self._selected_memory_id()
        if mem_id is None:
            QMessageBox.information(self, "更新记忆", "请先在表格里选中一条记忆。")
            return
        content = self.mem_new_content.text().strip()
        if not content:
            QMessageBox.information(self, "更新记忆", "编辑框内容不能为空。")
            return
        self.memory_update_requested.emit(
            mem_id, content, self.mem_new_type.currentText(), self.mem_new_imp.value())
        self.mem_new_content.clear()
        self._editing_mem_id = None

    def _on_memory_delete(self):
        mem_id = self._selected_memory_id()
        if mem_id is None:
            QMessageBox.information(self, "删除记忆", "请先在表格里选中一条记忆。")
            return
        if QMessageBox.question(self, "删除记忆", f"确定删除记忆 #{mem_id} 吗？") \
                != QMessageBox.Yes:
            return
        self.memory_delete_requested.emit(mem_id)
        self.mem_new_content.clear()
        self._editing_mem_id = None

    def _on_memory_row_activated(self, index):
        row = index.row()
        mem_id = self._memory_id_at(row)
        if mem_id is None:
            return
        self._editing_mem_id = mem_id
        content_item = self.memory_table.item(row, 2)
        type_item = self.memory_table.item(row, 1)
        imp_item = self.memory_table.item(row, 3)
        self.mem_new_content.setText(content_item.text() if content_item else "")
        idx = self.mem_new_type.findText(type_item.text() if type_item else "episodic")
        if idx >= 0:
            self.mem_new_type.setCurrentIndex(idx)
        if imp_item:
            try:
                self.mem_new_imp.setValue(float(imp_item.text()))
            except Exception:
                pass

    def _selected_memory_id(self):
        row = self.memory_table.currentRow()
        return self._memory_id_at(row)

    def _memory_id_at(self, row: int):
        if row < 0 or row >= self.memory_table.rowCount():
            return None
        item = self.memory_table.item(row, 0)
        if not item:
            return None
        try:
            return int(item.text())
        except Exception:
            return None

    def _on_rule_toggle(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            QMessageBox.information(self, "规则", "请先选中一条规则。")
            return
        self.memory_rule_toggle_requested.emit(rule_id)

    def _on_rule_delete(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            QMessageBox.information(self, "规则", "请先选中一条规则。")
            return
        if QMessageBox.question(self, "删除规则", "确定删除这条行为规则吗？") \
                != QMessageBox.Yes:
            return
        self.memory_rule_delete_requested.emit(rule_id)

    def _selected_rule_id(self):
        item = self.rules_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    # ------------------------------------------------------------------ MCP/Skills 页
    def _build_mcp_page(self):
        layout = QVBoxLayout(self.mcp_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        mcp_box = QGroupBox("MCP 服务器（外部工具）", self.mcp_page)
        mcp_box.setObjectName("PanelBox")
        m = QVBoxLayout(mcp_box)
        mcp_row = QHBoxLayout()
        self.mcp_refresh_btn = QPushButton("🔄 刷新", self.mcp_page)
        self.mcp_refresh_btn.clicked.connect(lambda: self.mcp_refresh_requested.emit())
        mcp_row.addWidget(self.mcp_refresh_btn)
        self.mcp_add_btn = QPushButton("＋ 添加", self.mcp_page)
        self.mcp_add_btn.clicked.connect(self._on_add_mcp)
        mcp_row.addWidget(self.mcp_add_btn)
        self.mcp_import_btn = QPushButton("📂 导入 MCP JSON", self.mcp_page)
        self.mcp_import_btn.clicked.connect(self._on_import_mcp)
        mcp_row.addWidget(self.mcp_import_btn)
        self.mcp_toggle_btn = QPushButton("启用/停用", self.mcp_page)
        self.mcp_toggle_btn.clicked.connect(self._on_toggle_mcp)
        mcp_row.addWidget(self.mcp_toggle_btn)
        self.mcp_delete_btn = QPushButton("删除", self.mcp_page)
        self.mcp_delete_btn.setObjectName("DangerButton")
        self.mcp_delete_btn.clicked.connect(self._on_delete_mcp)
        mcp_row.addWidget(self.mcp_delete_btn)
        mcp_row.addStretch(1)
        m.addLayout(mcp_row)
        self.mcp_list = QListWidget(self.mcp_page)
        m.addWidget(self.mcp_list)
        layout.addWidget(mcp_box)

        skill_box = QGroupBox("Skills（Claude Agent Skills 风格指令包）", self.mcp_page)
        skill_box.setObjectName("PanelBox")
        s = QVBoxLayout(skill_box)
        skill_row = QHBoxLayout()
        self.skill_refresh_btn = QPushButton("🔄 刷新", self.mcp_page)
        self.skill_refresh_btn.clicked.connect(lambda: self.mcp_refresh_requested.emit())
        skill_row.addWidget(self.skill_refresh_btn)
        self.skill_import_btn = QPushButton("＋ 导入 Skill", self.mcp_page)
        self.skill_import_btn.clicked.connect(self._on_import_skill)
        skill_row.addWidget(self.skill_import_btn)
        self.skill_toggle_btn = QPushButton("启用/停用", self.mcp_page)
        self.skill_toggle_btn.clicked.connect(self._on_toggle_skill)
        skill_row.addWidget(self.skill_toggle_btn)
        self.skill_delete_btn = QPushButton("删除", self.mcp_page)
        self.skill_delete_btn.setObjectName("DangerButton")
        self.skill_delete_btn.clicked.connect(self._on_delete_skill)
        skill_row.addWidget(self.skill_delete_btn)
        skill_row.addStretch(1)
        s.addLayout(skill_row)
        self.skill_list = QListWidget(self.mcp_page)
        s.addWidget(self.skill_list)
        layout.addWidget(skill_box, 1)

    def _on_add_mcp(self):
        name, ok = QInputDialog.getText(self, "添加 MCP", "名称：")
        if not ok or not name.strip():
            return
        transport, ok2 = QInputDialog.getItem(
            self, "添加 MCP", "传输方式：", ["streamable_http", "sse", "stdio"], 0, False)
        if not ok2:
            return
        url, command, args = "", "", ""
        if transport == "stdio":
            command, ok3 = QInputDialog.getText(self, "添加 MCP", "启动命令（如 python）：")
            if not ok3:
                return
            args, ok4 = QInputDialog.getText(self, "添加 MCP", "参数（空格分隔）：")
            if not ok4:
                return
        else:
            url, ok3 = QInputDialog.getText(self, "添加 MCP", "URL：")
            if not ok3 or not url.strip():
                return
        self.mcp_add_requested.emit(name.strip(), transport, url, command, args)

    def _on_import_mcp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入 MCP 配置", str(self.cfg.root), "JSON (*.json);;All files (*.*)")
        if path:
            self.mcp_import_requested.emit(path)

    def _on_toggle_mcp(self):
        name = self._selected_item_name(self.mcp_list)
        if name:
            self.mcp_toggle_requested.emit(name)

    def _on_delete_mcp(self):
        name = self._selected_item_name(self.mcp_list)
        if name and QMessageBox.question(self, "删除 MCP", f"确定删除 {name}？") == QMessageBox.Yes:
            self.mcp_delete_requested.emit(name)

    def _on_import_skill(self):
        path = QFileDialog.getExistingDirectory(
            self, "导入 Skill 文件夹（含 SKILL.md）", str(self.cfg.root))
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "导入 SKILL.md", str(self.cfg.root), "Markdown (*.md)")
        if path:
            self.skill_import_requested.emit(path)

    def _on_toggle_skill(self):
        name = self._selected_item_name(self.skill_list)
        if name:
            self.skill_toggle_requested.emit(name)

    def _on_delete_skill(self):
        name = self._selected_item_name(self.skill_list)
        if name and QMessageBox.question(self, "删除 Skill", f"确定删除 {name}？") == QMessageBox.Yes:
            self.skill_delete_requested.emit(name)

    @staticmethod
    def _selected_item_name(lst):
        item = lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def set_mcp_servers(self, rows: list[dict]):
        self.mcp_list.clear()
        for r in rows or []:
            label = f"{'✅' if r.get('enabled') else '⛔'} {r.get('name')} · {r.get('transport','')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.get("name"))
            self.mcp_list.addItem(item)

    def set_skills(self, rows: list[dict]):
        self.skill_list.clear()
        for r in rows or []:
            label = f"{'✅' if r.get('enabled') else '⛔'} {r.get('name')} · {r.get('path','')}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r.get("name"))
            self.skill_list.addItem(item)

    # ------------------------------------------------------------------ 控制台页
    def _build_console_page(self):
        layout = QVBoxLayout(self.console_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        svc = QGroupBox("后台服务", self.console_page)
        svc.setObjectName("PanelBox")
        svc_grid = QGridLayout(svc)

        self.heart_status_label = QLabel("Heart：检查中…", self.console_page)
        svc_grid.addWidget(self.heart_status_label, 0, 0)
        self.start_heart_btn = QPushButton("▶ 启动 Heart", self.console_page)
        self.start_heart_btn.clicked.connect(
            lambda: self.service_action_requested.emit("start_heart"))
        svc_grid.addWidget(self.start_heart_btn, 0, 1)
        self.stop_heart_btn = QPushButton("■ 停止 Heart", self.console_page)
        self.stop_heart_btn.clicked.connect(
            lambda: self.service_action_requested.emit("stop_heart"))
        svc_grid.addWidget(self.stop_heart_btn, 0, 2)

        self.gsv_status_label = QLabel("GPT-SoVITS：检查中…", self.console_page)
        svc_grid.addWidget(self.gsv_status_label, 1, 0)
        self.start_gsv_btn = QPushButton("▶ 启动 GPT-SoVITS", self.console_page)
        self.start_gsv_btn.clicked.connect(
            lambda: self.service_action_requested.emit("start_gsv"))
        svc_grid.addWidget(self.start_gsv_btn, 1, 1)
        self.stop_gsv_btn = QPushButton("■ 停止 GPT-SoVITS", self.console_page)
        self.stop_gsv_btn.clicked.connect(
            lambda: self.service_action_requested.emit("stop_gsv"))
        svc_grid.addWidget(self.stop_gsv_btn, 1, 2)
        layout.addWidget(svc)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(QLabel("来源", self.console_page))
        self.console_source = QComboBox(self.console_page)
        self.console_source.addItems(["全部", "agent", "heart", "gpt_sovits", "live2d", "train"])
        self.console_source.currentIndexChanged.connect(self._refresh_console)
        tools.addWidget(self.console_source)
        tools.addWidget(QLabel("级别", self.console_page))
        self.console_level = QComboBox(self.console_page)
        self.console_level.addItems(["全部", "INFO", "WARNING", "ERROR", "DEBUG"])
        self.console_level.currentIndexChanged.connect(self._refresh_console)
        tools.addWidget(self.console_level)
        self.console_filter = QLineEdit(self.console_page)
        self.console_filter.setPlaceholderText("过滤关键字…")
        self.console_filter.textChanged.connect(self._schedule_console_refresh)
        tools.addWidget(self.console_filter, 1)
        self.console_refresh_btn = QPushButton("🔄 刷新", self.console_page)
        self.console_refresh_btn.clicked.connect(self._refresh_console)
        tools.addWidget(self.console_refresh_btn)
        self.console_clear_btn = QPushButton("🧹 清屏", self.console_page)
        self.console_clear_btn.clicked.connect(lambda: self.console_view.clear())
        tools.addWidget(self.console_clear_btn)
        self.console_dir_btn = QPushButton("📁 日志目录", self.console_page)
        self.console_dir_btn.clicked.connect(self._open_logs_dir)
        tools.addWidget(self.console_dir_btn)
        layout.addLayout(tools)

        self.console_view = QPlainTextEdit(self.console_page)
        self.console_view.setReadOnly(True)
        self.console_view.setMaximumBlockCount(4000)
        self.console_view.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px;"
            "background: rgba(6,10,24,0.95); color: #a5f3fc;"
            "border: 1px solid rgba(103,232,249,0.25); border-radius: 12px;")
        layout.addWidget(self.console_view, 1)

        self._last_console_text: str | None = None

        bottom = QHBoxLayout()
        self.console_auto = QCheckBox("自动刷新（2 秒）", self.console_page)
        self.console_auto.setChecked(True)
        bottom.addWidget(self.console_auto)
        self.console_scroll = QCheckBox("自动滚动到底部", self.console_page)
        self.console_scroll.setChecked(True)
        bottom.addWidget(self.console_scroll)
        bottom.addStretch(1)
        layout.addLayout(bottom)

        self.console_timer = QTimer(self)
        self.console_timer.setInterval(2000)
        self.console_timer.timeout.connect(self._auto_refresh_console)
        self.console_timer.start()
        self._console_filter_timer = QTimer(self)
        self._console_filter_timer.setSingleShot(True)
        self._console_filter_timer.setInterval(300)
        self._console_filter_timer.timeout.connect(self._refresh_console)

    def _schedule_console_refresh(self):
        self._console_filter_timer.start()

    def _auto_refresh_console(self):
        if self.console_auto.isChecked():
            self._refresh_console()

    def _refresh_console(self):
        # 控制台不可见时不读日志、不刷文本，避免周期性卡顿
        if (self.tabs.currentWidget() is not self.settings_page or
                self.settings_tabs.currentWidget() is not self.console_page):
            return
        try:
            text = collect_logs(
                self.cfg.root,
                source=self.console_source.currentText(),
                filter_text=self.console_filter.text().strip(),
                level=self.console_level.currentText(),
            )
        except Exception as e:
            text = f"[控制台读取日志失败] {e}"
        if self._console_notes:
            notes = "\n".join(self._console_notes[-400:])
            text = f"{text}\n\n── 会话内通知 ──\n{notes}"
        if text != self._last_console_text:
            self._last_console_text = text
            self.console_view.setPlainText(text)
        if self.console_scroll.isChecked():
            sb = self.console_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _open_logs_dir(self):
        path = self.cfg.root / "data" / "logs"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def set_service_status(self, name: str, running: bool):
        if name == "heart":
            self.heart_status_label.setText(
                f"Heart：{'✅ 运行中' if running else '⛔ 未运行'}")
        elif name == "gpt_sovits":
            self.gsv_status_label.setText(
                f"GPT-SoVITS：{'✅ 运行中' if running else '⛔ 未运行'}")

    def append_console_note(self, text: str):
        """系统通知统一写入控制台日志区（会话内可见，并落 agent 日志）。"""
        line = f"[{_datetime.now().strftime('%H:%M:%S')}] ▸ {text}"
        self._console_notes.append(line)
        self._console_notes = self._console_notes[-500:]
        logging.getLogger("nori.ui").info(text)
        self._refresh_console()

    # ------------------------------------------------------------------ 设置页
    def _build_basic_settings_page(self):
        layout = QVBoxLayout(self.settings_basic_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # LLM / API 配置（支持 DeepSeek、OpenAI、Ollama、自定义 OpenAI 兼容端点）
        api_box = QGroupBox("LLM / API 配置（支持自定义提供商与本地 Ollama）", self.settings_basic_page)
        api_box.setObjectName("PanelBox")
        api_grid = QGridLayout(api_box)
        api_grid.setHorizontalSpacing(10)
        api_grid.setVerticalSpacing(8)

        api_grid.addWidget(QLabel("提供商", self.settings_basic_page), 0, 0)
        self.api_provider_combo = QComboBox(self.settings_basic_page)
        self.api_provider_combo.addItem("DeepSeek", "deepseek")
        self.api_provider_combo.addItem("OpenAI", "openai")
        self.api_provider_combo.addItem("Ollama（本地）", "ollama")
        self.api_provider_combo.addItem("自定义", "custom")
        self.api_provider_combo.currentIndexChanged.connect(self._on_api_provider_changed)
        api_grid.addWidget(self.api_provider_combo, 0, 1, 1, 3)

        api_grid.addWidget(QLabel("API Key", self.settings_basic_page), 1, 0)
        self.api_key_edit = QLineEdit(self.settings_basic_page)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...；Ollama 本地可留空")
        self.api_key_edit.setText(str(self.cfg.llm.get("api_key", "") or ""))
        api_grid.addWidget(self.api_key_edit, 1, 1, 1, 2)
        self.api_show_check = QCheckBox("显示", self.settings_basic_page)
        self.api_show_check.toggled.connect(
            lambda on: self.api_key_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        api_grid.addWidget(self.api_show_check, 1, 3)

        api_grid.addWidget(QLabel("Base URL", self.settings_basic_page), 2, 0)
        self.api_base_edit = QLineEdit(self.settings_basic_page)
        self.api_base_edit.setText(str(self.cfg.llm.get("base_url", "https://api.deepseek.com")))
        api_grid.addWidget(self.api_base_edit, 2, 1, 1, 2)

        api_grid.addWidget(QLabel("模型", self.settings_basic_page), 3, 0)
        self.api_model_combo = QComboBox(self.settings_basic_page)
        self.api_model_combo.setEditable(True)
        self.api_model_combo.addItems([
            "deepseek-v4-flash", "deepseek-chat",
            "gpt-4o-mini", "gpt-4o",
            "qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "gemma2:9b",
        ])
        for m in (self.cfg.llm.get("custom_models") or []):
            m = str(m).strip()
            if m and self.api_model_combo.findText(m) < 0:
                self.api_model_combo.addItem(m)
        self.api_model_combo.setCurrentText(str(self.cfg.llm.get("model", "deepseek-v4-flash")))
        api_grid.addWidget(self.api_model_combo, 3, 1, 1, 2)
        self.api_apply_btn = QPushButton("应用并保存 API", self.settings_basic_page)
        self.api_apply_btn.setObjectName("PrimaryButton")
        self.api_apply_btn.clicked.connect(self._emit_llm_config)
        api_grid.addWidget(self.api_apply_btn, 3, 3)

        self.api_fetch_models_btn = QPushButton("🔄 获取模型列表", self.settings_basic_page)
        self.api_fetch_models_btn.setToolTip("从当前 Base URL 拉取可用模型（OpenAI 兼容 / Ollama）")
        self.api_fetch_models_btn.clicked.connect(self._emit_fetch_llm_models)
        api_grid.addWidget(self.api_fetch_models_btn, 4, 1)
        layout.addWidget(api_box)
        self._sync_api_provider_from_base()
        self._install_combo_context_menu(self.api_model_combo, "llm")

        layout.addWidget(self._build_search_api_box())
        layout.addWidget(self._build_vision_api_box())

        layout.addWidget(self._build_quick_box())
        layout.addWidget(self._build_tts_voice_box())

        font_box = QGroupBox("字体与头像", self.settings_basic_page)
        font_box.setObjectName("PanelBox")
        font_grid = QGridLayout(font_box)
        font_grid.setHorizontalSpacing(10)
        font_grid.setVerticalSpacing(8)

        # 界面字体 / 聊天气泡字体分开设置
        font_grid.addWidget(QLabel("界面字体大小", self.settings_basic_page), 0, 0)
        self.font_combo = QComboBox(self.settings_basic_page)
        for size in range(10, 19):
            self.font_combo.addItem(f"{size} px", size)
        default_font = int(self.cfg.gui.get("font_size", 13) or 13)
        idx = self.font_combo.findData(default_font)
        if idx < 0:
            idx = self.font_combo.findData(13)
        self.font_combo.setCurrentIndex(idx)
        self.font_combo.currentIndexChanged.connect(
            lambda _: self.font_size_requested.emit(int(self.font_combo.currentData())))
        font_grid.addWidget(self.font_combo, 0, 1)

        font_grid.addWidget(QLabel("聊天气泡字体", self.settings_basic_page), 0, 2)
        self.chat_font_combo = QComboBox(self.settings_basic_page)
        for size in range(12, 23):
            self.chat_font_combo.addItem(f"{size} px", size)
        default_chat_font = int(self.cfg.gui.get("chat_font_size", 15) or 15)
        ci = self.chat_font_combo.findData(default_chat_font)
        if ci < 0:
            ci = self.chat_font_combo.findData(15)
        self.chat_font_combo.setCurrentIndex(ci)
        self.chat_font_combo.currentIndexChanged.connect(
            lambda _: self.chat_font_size_requested.emit(int(self.chat_font_combo.currentData())))
        font_grid.addWidget(self.chat_font_combo, 0, 3)

        # 用户昵称与头像
        font_grid.addWidget(QLabel("用户昵称", self.settings_basic_page), 1, 0)
        self.user_name_edit = QLineEdit(self.settings_basic_page)
        self.user_name_edit.setText(self._user_name)
        self.user_name_edit.editingFinished.connect(
            lambda: self.user_name_requested.emit(self.user_name_edit.text().strip()))
        font_grid.addWidget(self.user_name_edit, 1, 1, 1, 2)
        self.user_name_save_btn = QPushButton("应用昵称", self.settings_basic_page)
        self.user_name_save_btn.clicked.connect(
            lambda: self.user_name_requested.emit(self.user_name_edit.text().strip()))
        font_grid.addWidget(self.user_name_save_btn, 1, 3)

        font_grid.addWidget(QLabel("我的头像", self.settings_basic_page), 2, 0)
        self.user_avatar_label = QLabel("🧑（默认）", self.settings_basic_page)
        self.user_avatar_btn = QPushButton("选择图片…", self.settings_basic_page)
        self.user_avatar_btn.clicked.connect(lambda: self._on_select_avatar("user"))
        self.user_avatar_reset_btn = QPushButton("恢复默认", self.settings_basic_page)
        self.user_avatar_reset_btn.clicked.connect(
            lambda: self.avatar_requested.emit("user", ""))
        font_grid.addWidget(self.user_avatar_label, 2, 1)
        font_grid.addWidget(self.user_avatar_btn, 2, 2)
        font_grid.addWidget(self.user_avatar_reset_btn, 2, 3)

        # 智能体（当前人格）名字与头像
        font_grid.addWidget(QLabel("智能体名字", self.settings_basic_page), 3, 0)
        self.agent_name_edit = QLineEdit(self.settings_basic_page)
        self.agent_name_edit.setText(self._agent_name)
        self.agent_name_edit.editingFinished.connect(
            lambda: self.agent_name_requested.emit(self.agent_name_edit.text().strip()))
        font_grid.addWidget(self.agent_name_edit, 3, 1, 1, 2)
        self.agent_name_save_btn = QPushButton("应用名字", self.settings_basic_page)
        self.agent_name_save_btn.clicked.connect(
            lambda: self.agent_name_requested.emit(self.agent_name_edit.text().strip()))
        font_grid.addWidget(self.agent_name_save_btn, 3, 3)

        font_grid.addWidget(QLabel("智能体头像", self.settings_basic_page), 4, 0)
        self.agent_avatar_label = QLabel("🐱（默认）", self.settings_basic_page)
        self.agent_avatar_btn = QPushButton("选择图片…", self.settings_basic_page)
        self.agent_avatar_btn.clicked.connect(lambda: self._on_select_agent_avatar())
        self.agent_avatar_reset_btn = QPushButton("恢复默认", self.settings_basic_page)
        self.agent_avatar_reset_btn.clicked.connect(
            lambda: self.agent_avatar_requested.emit(""))
        font_grid.addWidget(self.agent_avatar_label, 4, 1)
        font_grid.addWidget(self.agent_avatar_btn, 4, 2)
        font_grid.addWidget(self.agent_avatar_reset_btn, 4, 3)
        layout.addWidget(font_box)

        # 上下文压缩
        comp_box = QGroupBox("上下文压缩（LLM）", self.settings_basic_page)
        comp_box.setObjectName("PanelBox")
        comp_grid = QGridLayout(comp_box)
        comp_grid.addWidget(QLabel("压缩模式", self.settings_basic_page), 0, 0)
        self.compression_mode_combo = QComboBox(self.settings_basic_page)
        self.compression_mode_combo.addItem("关闭", "off")
        self.compression_mode_combo.addItem("自动（推荐）", "auto")
        self.compression_mode_combo.addItem("始终压缩", "on")
        comp_cfg = self.cfg.llm.get("context_compression", {}) or {}
        mi = self.compression_mode_combo.findData(str(comp_cfg.get("mode", "auto")))
        self.compression_mode_combo.setCurrentIndex(mi if mi >= 0 else 1)
        self.compression_mode_combo.currentIndexChanged.connect(self._emit_compression)
        comp_grid.addWidget(self.compression_mode_combo, 0, 1)

        comp_grid.addWidget(QLabel("保留最近消息", self.settings_basic_page), 0, 2)
        self.compression_window_spin = QSpinBox(self.settings_basic_page)
        self.compression_window_spin.setRange(5, 50)
        self.compression_window_spin.setValue(int(comp_cfg.get("window_size", 20)))
        self.compression_window_spin.valueChanged.connect(self._emit_compression)
        comp_grid.addWidget(self.compression_window_spin, 0, 3)

        comp_grid.addWidget(QLabel("摘要最大字数", self.settings_basic_page), 1, 0)
        self.compression_chars_spin = QSpinBox(self.settings_basic_page)
        self.compression_chars_spin.setRange(100, 800)
        self.compression_chars_spin.setSingleStep(50)
        self.compression_chars_spin.setValue(int(comp_cfg.get("max_chars", 300)))
        self.compression_chars_spin.valueChanged.connect(self._emit_compression)
        comp_grid.addWidget(self.compression_chars_spin, 1, 1)
        layout.addWidget(comp_box)
        layout.addStretch(1)

    def _emit_compression(self):
        self.context_compression_requested.emit(
            self.compression_mode_combo.currentData(),
            self.compression_window_spin.value(),
            self.compression_chars_spin.value())

    def _sync_api_provider_from_base(self):
        base = self.api_base_edit.text().strip().lower()
        if "deepseek" in base:
            provider = "deepseek"
        elif "openai" in base:
            provider = "openai"
        elif "localhost" in base or "127.0.0.1" in base:
            provider = "ollama"
        else:
            provider = "custom"
        idx = self.api_provider_combo.findData(provider)
        if idx >= 0:
            self.api_provider_combo.blockSignals(True)
            self.api_provider_combo.setCurrentIndex(idx)
            self.api_provider_combo.blockSignals(False)

    def _on_api_provider_changed(self):
        provider = self.api_provider_combo.currentData()
        if provider == "deepseek":
            self.api_base_edit.setText("https://api.deepseek.com")
            if not self.api_model_combo.currentText().strip().startswith("deepseek"):
                self.api_model_combo.setCurrentText("deepseek-v4-flash")
        elif provider == "openai":
            self.api_base_edit.setText("https://api.openai.com/v1")
            if not self.api_model_combo.currentText().strip().startswith("gpt"):
                self.api_model_combo.setCurrentText("gpt-4o-mini")
        elif provider == "ollama":
            self.api_base_edit.setText("http://127.0.0.1:11434/v1")
            if not self.api_model_combo.currentText().strip():
                self.api_model_combo.setCurrentText("qwen2.5:7b")
            self.api_key_edit.setPlaceholderText("ollama 本地无需真实 Key")
        elif provider == "custom":
            self.api_key_edit.setPlaceholderText("sk-... 或本地服务所需 Key")

    def add_custom_model(self, name: str):
        """把自定义模型名加入下拉框（持久化由主进程负责）。"""
        name = (name or "").strip()
        if not name:
            return
        if self.api_model_combo.findText(name) < 0:
            self.api_model_combo.addItem(name)

    def remove_custom_model(self, name: str):
        """从 LLM 模型下拉框移除一个自定义模型名。"""
        idx = self.api_model_combo.findText(name)
        if idx >= 0:
            self.api_model_combo.removeItem(idx)

    def _emit_llm_config(self):
        model = self.api_model_combo.currentText().strip()
        self.add_custom_model(model)
        self.llm_config_requested.emit(
            self.api_key_edit.text().strip(),
            self.api_base_edit.text().strip(),
            model)

    def _emit_fetch_llm_models(self):
        self.llm_fetch_models_requested.emit()

    # ------------------------------------------------------------------ 其他 API 配置
    def _build_search_api_box(self) -> QGroupBox:
        page = self.settings_basic_page
        box = QGroupBox("联网搜索 API（百度智能云）", page)
        box.setObjectName("PanelBox")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("API Key", page), 0, 0)
        self.search_api_edit = QLineEdit(page)
        self.search_api_edit.setEchoMode(QLineEdit.Password)
        self.search_api_edit.setPlaceholderText("bce-v3/...（留空则使用环境变量）")
        self.search_api_edit.setText(str(self.cfg.search.get("api_key", "") or ""))
        grid.addWidget(self.search_api_edit, 0, 1, 1, 2)
        self.search_api_show = QCheckBox("显示", page)
        self.search_api_show.toggled.connect(
            lambda on: self.search_api_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        grid.addWidget(self.search_api_show, 0, 3)

        self.search_api_apply_btn = QPushButton("应用并保存", page)
        self.search_api_apply_btn.setObjectName("PrimaryButton")
        self.search_api_apply_btn.clicked.connect(self._emit_search_config)
        grid.addWidget(self.search_api_apply_btn, 1, 3)
        return box

    def _build_vision_api_box(self) -> QGroupBox:
        page = self.settings_basic_page
        box = QGroupBox("视觉 MCP API（火山方舟 Ark）", page)
        box.setObjectName("PanelBox")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        # 读取独立视觉 MCP 配置（vision_mcp/config.json），不存在则用默认值
        vision_cfg: dict = {}
        vision_path = self.cfg.root / "vision_mcp" / "config.json"
        try:
            if vision_path.exists():
                vision_cfg = json.loads(vision_path.read_text(encoding="utf-8")) or {}
        except Exception:
            vision_cfg = {}

        grid.addWidget(QLabel("API Key", page), 0, 0)
        self.vision_api_edit = QLineEdit(page)
        self.vision_api_edit.setEchoMode(QLineEdit.Password)
        self.vision_api_edit.setPlaceholderText("火山方舟 Ark API Key")
        self.vision_api_edit.setText(str(vision_cfg.get("api_key", "") or ""))
        grid.addWidget(self.vision_api_edit, 0, 1, 1, 2)
        self.vision_api_show = QCheckBox("显示", page)
        self.vision_api_show.toggled.connect(
            lambda on: self.vision_api_edit.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        grid.addWidget(self.vision_api_show, 0, 3)

        grid.addWidget(QLabel("Base URL", page), 1, 0)
        self.vision_base_edit = QLineEdit(page)
        self.vision_base_edit.setText(str(
            vision_cfg.get("base_url", "https://ark.cn-beijing.volces.com/api/v3")))
        grid.addWidget(self.vision_base_edit, 1, 1, 1, 2)

        grid.addWidget(QLabel("模型", page), 2, 0)
        self.vision_model_combo = QComboBox(page)
        self.vision_model_combo.setEditable(True)
        self.vision_model_combo.addItem("doubao-seed-2-1-pro-260628")
        self.vision_model_combo.setCurrentText(str(
            vision_cfg.get("model", "doubao-seed-2-1-pro-260628")))
        grid.addWidget(self.vision_model_combo, 2, 1, 1, 2)

        grid.addWidget(QLabel("MCP 端口", page), 3, 0)
        self.vision_port_spin = QSpinBox(page)
        self.vision_port_spin.setRange(1, 65535)
        self.vision_port_spin.setValue(int(vision_cfg.get("port", 47833) or 47833))
        grid.addWidget(self.vision_port_spin, 3, 1)

        self.vision_api_apply_btn = QPushButton("应用并保存", page)
        self.vision_api_apply_btn.setObjectName("PrimaryButton")
        self.vision_api_apply_btn.clicked.connect(self._emit_vision_config)
        grid.addWidget(self.vision_api_apply_btn, 3, 2, 1, 2)

        hint = QLabel("保存到 vision_mcp/config.json。若视觉 MCP 正在运行，需要重启 vision_mcp/server.py。",
                      page)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6d8; font-size:12px;")
        grid.addWidget(hint, 4, 0, 1, 4)
        return box

    def _emit_search_config(self):
        self.search_config_requested.emit(self.search_api_edit.text().strip())

    def _emit_vision_config(self):
        self.vision_config_requested.emit(
            self.vision_api_edit.text().strip(),
            self.vision_base_edit.text().strip(),
            self.vision_model_combo.currentText().strip(),
            int(self.vision_port_spin.value()))

    # ------------------------------------------------------------------ TTS 语音包
    def _build_tts_voice_box(self) -> QGroupBox:
        page = self.settings_basic_page
        box = QGroupBox("TTS 语音包（GPT-SoVITS）", page)
        box.setObjectName("PanelBox")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("当前语音包", page), 0, 0)
        self.tts_voice_combo = QComboBox(page)
        grid.addWidget(self.tts_voice_combo, 0, 1, 1, 3)

        self.tts_voice_refresh_btn = QPushButton("🔄 刷新", page)
        self.tts_voice_refresh_btn.clicked.connect(self._on_tts_voice_refresh)
        grid.addWidget(self.tts_voice_refresh_btn, 1, 0)

        self.tts_voice_import_btn = QPushButton("📂 导入语音包", page)
        self.tts_voice_import_btn.clicked.connect(self._on_tts_voice_import)
        grid.addWidget(self.tts_voice_import_btn, 1, 1)

        self.tts_voice_switch_btn = QPushButton("🔄 切换并重启", page)
        self.tts_voice_switch_btn.setObjectName("PrimaryButton")
        self.tts_voice_switch_btn.clicked.connect(self._on_tts_voice_switch)
        grid.addWidget(self.tts_voice_switch_btn, 1, 2)

        self.tts_voice_export_btn = QPushButton("📦 导出语音包", page)
        self.tts_voice_export_btn.clicked.connect(self._on_tts_voice_export)
        grid.addWidget(self.tts_voice_export_btn, 1, 3)

        self.tts_voice_status = QLabel("", page)
        self.tts_voice_status.setWordWrap(True)
        self.tts_voice_status.setStyleSheet("color:#8fa6d8; font-size:12px;")
        grid.addWidget(self.tts_voice_status, 2, 0, 1, 4)

        # 语音包导出目录（可在设置里修改，保存到 settings_overrides.json）
        grid.addWidget(QLabel("导出目录", page), 3, 0)
        self.voice_export_dir_edit = QLineEdit(page)
        self.voice_export_dir_edit.setText(self._voice_export_dir)
        self.voice_export_dir_edit.setPlaceholderText(
            f"留空则导出到 {Path.home() / 'Downloads'}")
        self.voice_export_dir_edit.editingFinished.connect(
            lambda: self.voice_export_dir_requested.emit(
                self.voice_export_dir_edit.text().strip()))
        grid.addWidget(self.voice_export_dir_edit, 3, 1, 1, 2)
        self.voice_export_dir_btn = QPushButton("📁 浏览…", page)
        self.voice_export_dir_btn.setToolTip("选择语音包导出目录")
        self.voice_export_dir_btn.clicked.connect(self._on_select_voice_export_dir)
        grid.addWidget(self.voice_export_dir_btn, 3, 3)
        return box

    def set_voice_export_dir(self, path: str):
        """由控制器在启动时同步当前导出目录到输入框。"""
        self._voice_export_dir = str(path or "")
        self.voice_export_dir_edit.blockSignals(True)
        self.voice_export_dir_edit.setText(self._voice_export_dir)
        self.voice_export_dir_edit.blockSignals(False)

    def _on_select_voice_export_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择语音包导出目录",
            self.voice_export_dir_edit.text() or str(self.cfg.root))
        if d:
            self.voice_export_dir_edit.setText(d)
            self.voice_export_dir_requested.emit(d)

    def set_tts_voices(self, voices: list[dict], current: str = ""):
        self.tts_voice_combo.blockSignals(True)
        self.tts_voice_combo.clear()
        for v in voices or []:
            self.tts_voice_combo.addItem(v.get("name", ""), v.get("name"))
        idx = self.tts_voice_combo.findData(current)
        if idx < 0 and self.tts_voice_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self.tts_voice_combo.setCurrentIndex(idx)
        self.tts_voice_combo.blockSignals(False)
        if current:
            self.tts_voice_status.setText(f"当前：{current}")
        else:
            self.tts_voice_status.setText("未选择语音包")

    def _on_tts_voice_refresh(self):
        self.tts_status_refresh_requested.emit()

    def _on_tts_voice_switch(self):
        name = self.tts_voice_combo.currentData()
        if name:
            self.tts_voice_switch_requested.emit(name)

    def _on_tts_voice_import(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择语音包文件夹（含参考音频 wav）", str(self.cfg.root))
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "或选择语音包 zip", str(self.cfg.root), "Zip (*.zip)")
        if path:
            self.tts_voice_import_requested.emit(path)

    def _on_tts_voice_export(self):
        name = self.tts_voice_combo.currentData()
        if name:
            self.tts_voice_export_requested.emit(name)

    def _on_select_avatar(self, role: str):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择头像图片", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if path:
            self.avatar_requested.emit(role, path)

    def _on_select_agent_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择智能体头像", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)")
        if path:
            self.agent_avatar_requested.emit(path)

    # ------------------------------------------------------------------ 聊天记录页
    def _build_history_page(self):
        layout = QVBoxLayout(self.history_page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 第一行：人格选择 + 新建对话
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("人格", self.history_page))
        self.history_persona_combo = QComboBox(self.history_page)
        self.history_persona_combo.currentIndexChanged.connect(
            lambda _: self.history_refresh_requested.emit(
                self.history_persona_combo.currentData() or ""))
        top.addWidget(self.history_persona_combo, 1)
        self.history_new_btn = QPushButton("＋ 新对话", self.history_page)
        self.history_new_btn.setObjectName("PrimaryButton")
        self.history_new_btn.clicked.connect(self._on_new_conversation)
        top.addWidget(self.history_new_btn)
        layout.addLayout(top)

        # 第二行：按名称筛选（本地过滤，不触发刷新）
        self.history_search_edit = QLineEdit(self.history_page)
        self.history_search_edit.setPlaceholderText("🔍 按名称筛选会话…")
        self.history_search_edit.setClearButtonEnabled(True)
        self.history_search_edit.textChanged.connect(lambda _t: self._render_history_list())
        layout.addWidget(self.history_search_edit)

        # 会话列表：双行卡片（标题 + 元信息），双击打开，右键菜单操作
        self.history_list = QListWidget(self.history_page)
        self.history_list.setObjectName("HistoryList")
        self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._show_history_menu)
        self.history_list.itemActivated.connect(lambda _item: self._on_open_conversation())
        layout.addWidget(self.history_list, 1)

        # 底部：当前会话 + 操作按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.current_conversation_label = QLabel("当前会话：未选择", self.history_page)
        self.current_conversation_label.setStyleSheet("color:#7dd3fc; font-size:12px;")
        bottom.addWidget(self.current_conversation_label, 1)
        self.history_open_btn = QPushButton("📂 打开到聊天", self.history_page)
        self.history_open_btn.clicked.connect(self._on_open_conversation)
        bottom.addWidget(self.history_open_btn)
        self.history_rename_btn = QPushButton("✏ 重命名", self.history_page)
        self.history_rename_btn.clicked.connect(self._on_rename_conversation)
        bottom.addWidget(self.history_rename_btn)
        self.history_delete_btn = QPushButton("🗑 删除", self.history_page)
        self.history_delete_btn.setObjectName("DangerButton")
        self.history_delete_btn.clicked.connect(self._on_delete_conversation)
        bottom.addWidget(self.history_delete_btn)
        layout.addLayout(bottom)

        self._conversation_rows: list[dict] = []
        self._conversation_current_id: int | None = None

    def set_history_personas(self, names: list[str], active: str):
        self.history_persona_combo.blockSignals(True)
        self.history_persona_combo.clear()
        for name in names or []:
            self.history_persona_combo.addItem(name, name)
        idx = self.history_persona_combo.findData(active)
        if idx < 0 and self.history_persona_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self.history_persona_combo.setCurrentIndex(idx)
        self.history_persona_combo.blockSignals(False)

    def set_conversations(self, rows: list[dict], current_id: int | None = None):
        """controller 推送会话列表；保存后统一交给 _render_history_list 渲染。"""
        self._conversation_rows = list(rows or [])
        self._conversation_current_id = current_id
        self._render_history_list()

    @staticmethod
    def _relative_time(ts: float) -> str:
        """把时间戳转成「刚刚 / N 分钟前 / …」；超过一周显示日期。"""
        try:
            delta = _datetime.now().timestamp() - float(ts)
        except Exception:
            return ""
        if delta < 0:
            return "刚刚"
        if delta < 60:
            return "刚刚"
        if delta < 3600:
            return f"{int(delta // 60)} 分钟前"
        if delta < 86400:
            return f"{int(delta // 3600)} 小时前"
        if delta < 7 * 86400:
            return f"{int(delta // 86400)} 天前"
        return _datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")

    def _render_history_list(self):
        """按搜索词过滤并渲染会话卡片（标题 + ★/条数/最近活跃）。"""
        flt = ""
        try:
            flt = self.history_search_edit.text().strip().lower()
        except AttributeError:
            pass
        rows = [r for r in self._conversation_rows
                if not flt or flt in str(r.get("title", "")).lower()]
        self.history_list.clear()
        if not rows:
            tip = QListWidgetItem(
                "（没有匹配的会话）" if flt
                else "（该人格还没有会话，点上方「＋ 新对话」开始）")
            tip.setFlags(Qt.NoItemFlags)
            tip.setForeground(QColor("#52638c"))
            self.history_list.addItem(tip)
            return
        for r in rows:
            title = str(r.get("title", ""))
            is_main = bool(r.get("is_main"))
            count = r.get("msg_count", 0) or 0
            last_ts = 0.0
            for key in ("last_ts", "updated"):
                try:
                    last_ts = float(r.get(key) or 0)
                    if last_ts > 0:
                        break
                except Exception:
                    last_ts = 0.0
            meta_bits = ["★ 主对话" if is_main else "🗨 普通对话",
                         f"{count} 条消息"]
            if last_ts > 0:
                meta_bits.append(self._relative_time(last_ts))
            current = r.get("id") == self._conversation_current_id

            card = QWidget(self.history_list)
            v = QVBoxLayout(card)
            v.setContentsMargins(10, 7, 10, 7)
            v.setSpacing(2)
            t = QLabel(("▶ " if current else "") + title, card)
            t.setObjectName("HistoryItemTitleActive" if current else "HistoryItemTitle")
            m = QLabel(" · ".join(meta_bits), card)
            m.setObjectName("HistoryItemMeta")
            v.addWidget(t)
            v.addWidget(m)

            item = QListWidgetItem()
            item.setData(Qt.UserRole, r.get("id"))
            item.setSizeHint(card.sizeHint())
            self.history_list.addItem(item)
            self.history_list.setItemWidget(item, card)
            if current:
                self.history_list.setCurrentItem(item)

    def _show_history_menu(self, pos):
        """会话列表右键菜单：打开 / 重命名 / 删除。"""
        item = self.history_list.itemAt(pos)
        if item is None or not (item.flags() & Qt.ItemIsSelectable):
            return
        self.history_list.setCurrentItem(item)
        menu = QMenu(self)
        a_open = menu.addAction("📂 打开到聊天")
        a_rename = menu.addAction("✏ 重命名")
        menu.addSeparator()
        a_delete = menu.addAction("🗑 删除")
        chosen = menu.exec(self.history_list.mapToGlobal(pos))
        if chosen is a_open:
            self._on_open_conversation()
        elif chosen is a_rename:
            self._on_rename_conversation()
        elif chosen is a_delete:
            self._on_delete_conversation()

    def set_current_conversation_label(self, text: str):
        self.current_conversation_label.setText(f"当前会话：{text}")

    def _selected_conversation_id(self):
        item = self.history_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _on_new_conversation(self):
        persona = self.history_persona_combo.currentData()
        if not persona:
            QMessageBox.information(self, "新对话", "请先选择人格。")
            return
        self.conversation_new_requested.emit(persona)

    def _on_open_conversation(self):
        conv_id = self._selected_conversation_id()
        if conv_id is None:
            QMessageBox.information(self, "聊天记录", "请先选择一个会话。")
            return
        self.conversation_open_requested.emit(int(conv_id))

    def _on_rename_conversation(self):
        conv_id = self._selected_conversation_id()
        if conv_id is None:
            QMessageBox.information(self, "重命名", "请先选择一个会话。")
            return
        title, ok = QInputDialog.getText(self, "重命名对话", "新名称：")
        if ok and title.strip():
            self.conversation_rename_requested.emit(int(conv_id), title.strip())

    def _on_delete_conversation(self):
        conv_id = self._selected_conversation_id()
        if conv_id is None:
            QMessageBox.information(self, "删除对话", "请先选择一个会话。")
            return
        if QMessageBox.question(self, "删除对话", "删除后该会话的历史不可恢复，确定吗？") \
                != QMessageBox.Yes:
            return
        self.conversation_delete_requested.emit(int(conv_id))

    def _build_quick_box(self) -> QGroupBox:
        page = self.settings_basic_page
        box = QGroupBox("⚙ 快速设置", page)
        box.setObjectName("PanelBox")
        grid = QGridLayout(box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        # 声音后端（仅保留 Nori 音色）
        grid.addWidget(QLabel("声音后端", page), 0, 0)
        self.backend_combo = QComboBox(page)
        self.backend_combo.addItem("GPT-SoVITS · Nori 音色", "gpt_sovits")
        self.backend_combo.currentIndexChanged.connect(
            lambda _: self.tts_backend_requested.emit(self.backend_combo.currentData()))
        grid.addWidget(self.backend_combo, 0, 1)

        # 语速
        grid.addWidget(QLabel("语速", page), 1, 0)
        self.speed_slider = QSlider(Qt.Horizontal, page)
        self.speed_slider.setRange(80, 130)
        self.speed_slider.setValue(100)
        self.speed_label = QLabel("1.00x", page)
        self.speed_label.setMinimumWidth(42)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(self.speed_label)
        grid.addLayout(speed_row, 1, 1, 1, 3)

        # 宠物大小（原生模式通过滑块调整）
        self.scale_label_title = QLabel("宠物大小", page)
        grid.addWidget(self.scale_label_title, 2, 0)
        self.scale_slider = QSlider(Qt.Horizontal, page)
        self.scale_slider.setRange(50, 200)
        self.scale_slider.setValue(100)
        self.scale_label = QLabel("1.00x", page)
        self.scale_label.setMinimumWidth(42)
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        self.scale_row = QHBoxLayout()
        self.scale_row.addWidget(self.scale_slider, 1)
        self.scale_row.addWidget(self.scale_label)
        grid.addLayout(self.scale_row, 2, 1, 1, 3)

        # Live2D 窗口控制
        grid.addWidget(QLabel("Live2D", page), 3, 0)
        self.l2d_show_btn = QPushButton("显示", page)
        self.l2d_hide_btn = QPushButton("隐藏", page)
        self.l2d_toggle_btn = QPushButton("切换", page)
        self.l2d_show_btn.clicked.connect(lambda: self.live2d_window_requested.emit("show"))
        self.l2d_hide_btn.clicked.connect(lambda: self.live2d_window_requested.emit("hide"))
        self.l2d_toggle_btn.clicked.connect(lambda: self.live2d_window_requested.emit("toggle"))
        l2d_row = QHBoxLayout()
        l2d_row.setSpacing(6)
        l2d_row.addWidget(self.l2d_show_btn)
        l2d_row.addWidget(self.l2d_hide_btn)
        l2d_row.addWidget(self.l2d_toggle_btn)
        self.top_check = QCheckBox("置顶", page)
        self.top_check.setChecked(True)
        self.top_check.toggled.connect(self.always_on_top_requested)
        l2d_row.addWidget(self.top_check)
        l2d_row.addStretch(1)
        grid.addLayout(l2d_row, 3, 1, 1, 2)

        self.save_btn = QPushButton("💾 保存设置", page)
        self.save_btn.setObjectName("SaveButton")
        self.save_btn.clicked.connect(self.save_settings_requested)
        grid.addWidget(self.save_btn, 3, 3)

        # Live2D 模型切换
        self.model_label_title = QLabel("Live2D 模型", page)
        grid.addWidget(self.model_label_title, 4, 0)
        self.model_combo = QComboBox(page)
        self.model_combo.setMinimumWidth(260)
        grid.addWidget(self.model_combo, 4, 1, 1, 2)
        self.model_refresh_btn = QPushButton("🔄", page)
        self.model_refresh_btn.setToolTip("刷新模型列表")
        self.model_refresh_btn.setFixedWidth(42)
        self.model_refresh_btn.clicked.connect(self.live2d_list_models_requested)
        self.model_switch_btn = QPushButton("加载模型", page)
        self.model_switch_btn.setObjectName("PrimaryButton")
        self.model_switch_btn.setToolTip("把选中的模型加载到 Live2D 窗口")
        self.model_switch_btn.clicked.connect(self._on_switch_model)
        self.model_import_btn = QPushButton("＋ 导入模型", page)
        self.model_import_btn.setToolTip("从本地文件夹或 ZIP 导入 Live2D 模型")
        self.model_import_btn.clicked.connect(self._on_import_model)
        l2d_model_row = QHBoxLayout()
        l2d_model_row.setSpacing(6)
        l2d_model_row.addWidget(self.model_refresh_btn)
        l2d_model_row.addWidget(self.model_switch_btn)
        l2d_model_row.addWidget(self.model_import_btn)
        grid.addLayout(l2d_model_row, 4, 3)

        is_native = str(self.cfg.live2d.get("controller", "") or "").lower() == "native"
        if self.live2d_mode and not is_native:
            self.scale_label_title.hide()
            self.scale_slider.hide()
            self.scale_label.hide()
            self.top_check.hide()
        else:
            if not self.live2d_mode:
                self.l2d_show_btn.hide()
                self.l2d_hide_btn.hide()
                self.l2d_toggle_btn.hide()
                self.model_label_title.hide()
                self.model_combo.hide()
                self.model_refresh_btn.hide()
                self.model_switch_btn.hide()
                self.model_import_btn.hide()

        return box

    # ------------------------------------------------------------------
    def _on_speed_changed(self, value: int):
        v = value / 100.0
        self.speed_label.setText(f"{v:.2f}x")
        self.speed_requested.emit(v)

    def _on_scale_changed(self, value: int):
        v = value / 100.0
        self.scale_label.setText(f"{v:.2f}x")
        self.scale_requested.emit(v)

    def _toggle_settings(self, checked: bool):
        self.tabs.setCurrentIndex(1 if checked else 0)
        self.settings_btn.setText("✕ 返回聊天" if checked else "⚙ 设置")

    def _on_switch_model(self):
        path = self.model_combo.currentData()
        if not path:
            QMessageBox.information(self, "加载 Live2D 模型", "请先刷新并选择一个模型。")
            return
        if QMessageBox.question(
                self, "加载 Live2D 模型",
                f"将加载模型：{path}\nLive2D 窗口会短暂重新加载，确定吗？") \
                != QMessageBox.Yes:
            return
        self.live2d_switch_model_requested.emit(path)

    def _on_import_model(self):
        directory = QFileDialog.getExistingDirectory(
            self, "选择 Live2D 模型文件夹（包含 .model3.json 与贴图/动作）",
            str(self.cfg.root))
        if not directory:
            path, _ = QFileDialog.getOpenFileName(
                self, "或选择 Live2D 模型压缩包", str(self.cfg.root), "Zip (*.zip)")
            if not path:
                return
            self.live2d_import_model_requested.emit(path)
            return
        self.live2d_import_model_requested.emit(directory)

    def set_live2d_models(self, models: list[dict], current: str = ""):
        """models: [{path, name}]；current 为当前模型相对路径。"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in models or []:
            label = f"{m.get('name', m.get('path', ''))}  ({m.get('path', '')})"
            self.model_combo.addItem(label, m.get("path", ""))
        idx = self.model_combo.findData(current)
        if idx < 0 and self.model_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)

    def _on_tab_changed(self, index: int):
        """用户直接点页签时，同步聊天页里的设置按钮状态。"""
        checked = index == 1
        if self.settings_btn.isChecked() != checked:
            self.settings_btn.blockSignals(True)
            self.settings_btn.setChecked(checked)
            self.settings_btn.blockSignals(False)
        self.settings_btn.setText("✕ 返回聊天" if checked else "⚙ 设置")
        if checked and self.settings_tabs.currentWidget() is self.console_page:
            self._refresh_console()

    def _on_settings_tab_changed(self, _index: int):
        """切到控制台页时立即刷新一次日志。"""
        if self.settings_tabs.currentWidget() is self.console_page:
            self._refresh_console()

    def set_status(self, text: str):
        self._base_status = text
        self.status_label.setText(text)

    def set_thinking(self, thinking: bool):
        """LLM 思考时把状态胶囊改成“思考中”，结束恢复原状态。"""
        if thinking:
            self.status_label.setText("💭 Nori 思考中…")
        else:
            self.status_label.setText(getattr(self, "_base_status", ""))

    def set_current_settings(self, backend: str, speed: float, scale: float,
                             always_on_top: bool,
                             font_size: int = 13, chat_font_size: int = 15):
        idx = self.backend_combo.findData(backend)
        if idx >= 0:
            self.backend_combo.blockSignals(True)
            self.backend_combo.setCurrentIndex(idx)
            self.backend_combo.blockSignals(False)
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(int(round(max(0.8, min(1.3, speed)) * 100)))
        self.speed_slider.blockSignals(False)
        self.speed_label.setText(f"{speed:.2f}x")
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(round(max(0.5, min(3.0, scale)) * 100)))
        self.scale_slider.blockSignals(False)
        self.scale_label.setText(f"{scale:.2f}x")
        self.top_check.blockSignals(True)
        self.top_check.setChecked(always_on_top)
        self.top_check.blockSignals(False)
        fi = self.font_combo.findData(font_size)
        if fi >= 0:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentIndex(fi)
            self.font_combo.blockSignals(False)
        ci = self.chat_font_combo.findData(chat_font_size)
        if ci >= 0:
            self.chat_font_combo.blockSignals(True)
            self.chat_font_combo.setCurrentIndex(ci)
            self.chat_font_combo.blockSignals(False)

    # ------------------------------------------------------------------ 外部填充
    def set_persona_list(self, names: list[str], active: str):
        """刷新人格下拉框；不改变编辑器内容。"""
        self.persona_combo.blockSignals(True)
        self.persona_combo.clear()
        for name in names or []:
            self.persona_combo.addItem(f"📜 {name}", name)
        idx = self.persona_combo.findData(active)
        if idx < 0 and self.persona_combo.count() > 0:
            idx = 0
        if idx >= 0:
            self.persona_combo.setCurrentIndex(idx)
        self.persona_combo.blockSignals(False)
        self._persona_active = active

    def set_persona_text(self, text: str, name: str, path: str = ""):
        self._persona_active = name
        self._restore_persona_combo(name)
        self.persona_edit.blockSignals(True)
        self.persona_edit.setPlainText(text)
        self.persona_edit.blockSignals(False)
        self.persona_path_label.setText(f"当前文件：{path}" if path else "")
        self._persona_dirty = False

    def set_persona(self, text: str, path: str = ""):
        """兼容入口：更新当前人格的编辑器内容。"""
        name = self._persona_active or self.persona_combo.currentData() or "nori"
        self.set_persona_text(text, name, path)

    def set_memories(self, rows: list[dict]):
        self.memory_table.setRowCount(len(rows or []))
        for row, r in enumerate(rows or []):
            ts = r.get("ts")
            try:
                ts_text = _datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
            except Exception:
                ts_text = ""
            vals = [
                str(r.get("id", "")),
                str(r.get("type", "")),
                str(r.get("content", "")),
                f"{float(r.get('importance', 0.0)):.2f}",
                str(r.get("access_count", 0)),
                ts_text,
            ]
            for col, val in enumerate(vals):
                self.memory_table.setItem(row, col, QTableWidgetItem(val))

    def set_rules(self, rows: list[dict]):
        self.rules_list.clear()
        for r in rows or []:
            rid = r.get("id")
            enabled = bool(r.get("enabled", 1))
            text = f"{'✅' if enabled else '⛔'} {r.get('rule', '')}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, rid)
            if not enabled:
                item.setForeground(Qt.gray)
            self.rules_list.addItem(item)

    # ------------------------------------------------------------------
    def _on_send(self):
        text = self.input.text().strip()
        if not text or not self._enabled:
            return
        self.input.clear()
        self.append_user(text)
        self.send_requested.emit(text)

    def _emit_media(self, paths: list[str], caption: str):
        """图片/表情包统一入口：先显示气泡，再通知控制器。"""
        if not self._enabled:
            return
        caption = (caption or "").strip()
        self.append_user_media(list(paths), caption)
        self.input.clear()
        self.media_send_requested.emit(list(paths), caption)

    def _on_send_images(self):
        if not self._enabled:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "发送图片（可多选）", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)")
        if not paths:
            return
        if len(paths) > 4:
            QMessageBox.information(self, "发送图片", "一次最多发送 4 张图片，超出部分已忽略。")
            paths = paths[:4]
        self._emit_media(paths, self.input.text().strip())

    def _show_sticker_menu(self):
        if not self._enabled:
            return
        try:
            ensure_default_stickers(self.cfg.root)
        except Exception as e:
            QMessageBox.warning(self, "表情包", f"生成内置表情包失败：{e}")
            return
        stickers = list_stickers(self.cfg.root)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #0c1530; border: 1px solid rgba(103,232,249,0.4);"
            " border-radius: 10px; color: #d7e3ff; }"
            "QMenu::item { padding: 6px 14px; border-radius: 6px; }"
            "QMenu::item:selected { background: #123c54; }")
        menu.setIconSize(QSize(64, 64))

        caption = self.input.text().strip()
        for s in stickers:
            icon = QIcon(s["path"])
            if icon.isNull():
                continue
            action = menu.addAction(icon, s["name"])
            action.triggered.connect(
                lambda _checked=False, path=s["path"]: self._emit_media([path], caption))
        if menu.isEmpty():
            menu.addAction("（暂无表情包）")
        menu.addSeparator()
        import_action = menu.addAction("📂 导入表情包…")
        import_action.triggered.connect(lambda _checked=False: self._on_import_stickers())
        open_action = menu.addAction("📁 打开表情包文件夹")
        open_action.triggered.connect(lambda _checked=False: self._open_stickers_dir())
        menu.exec(self.sticker_btn.mapToGlobal(
            QPoint(0, self.sticker_btn.height())))

    def _on_import_stickers(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入表情包（可多选）", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)")
        if not paths:
            return
        ok = 0
        for p in paths:
            try:
                if import_sticker(self.cfg.root, p):
                    ok += 1
            except Exception as e:
                self.append_system(f"导入表情失败 {Path(p).name}：{e}")
        if ok:
            self.append_system(f"😊 已导入 {ok} 个表情包到 data/stickers/imported/")

    def _open_stickers_dir(self):
        try:
            ensure_default_stickers(self.cfg.root)
            QDesktopServices.openUrl(QUrl.fromLocalFile(
                str(self.cfg.root / "data" / "stickers")))
        except Exception as e:
            self.append_system(f"打开表情包文件夹失败：{e}")

    def set_input_enabled(self, enabled: bool):
        self._enabled = enabled
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.image_btn.setEnabled(enabled)
        self.sticker_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    def clear_chat(self):
        while self.bubble_layout.count() > 1:
            item = self.bubble_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def set_chat_history(self, messages: list[dict]):
        self.clear_chat()
        for m in messages or []:
            if m.get("role") == "user":
                image_paths = m.get("image_paths") or []
                if image_paths:
                    self.append_user_media(image_paths, m.get("content", ""))
                else:
                    self.append_user(m.get("content", ""))
            elif m.get("role") == "assistant":
                self.append_assistant(m.get("content", ""))
        QTimer.singleShot(120, self._scroll_chat_to_bottom)

    def append_user(self, text: str):
        self._append_bubble(
            text,
            who=self._user_name,
            avatar=self._user_avatar or "🧑",
            name_color="#7dd3fc",
            align_right=True,
            tag="MASTER",
        )

    def append_user_media(self, image_paths: list[str], caption: str = ""):
        """显示用户发送的图片/表情包气泡；caption 可选。"""
        self._append_bubble(
            caption or "",
            who=self._user_name,
            avatar=self._user_avatar or "🧑",
            name_color="#7dd3fc",
            align_right=True,
            tag="MASTER",
            image_paths=image_paths,
        )

    def append_assistant(self, text: str):
        self._append_bubble(
            text,
            who=self._agent_name,
            avatar=self._agent_avatar or "🐱",
            name_color="#c4b5fd",
            align_right=False,
            tag=f"{self._agent_name.upper()} // NEURAL LINK",
        )

    def append_system(self, text: str):
        """所有系统/操作通知统一进控制台日志区，不再污染聊天气泡流。"""
        self.append_console_note(text)

    def _append_bubble(self, text: str, who: str, avatar: str, name_color: str,
                       align_right: bool, tag: str = "",
                       image_paths: list[str] | None = None):
        text = (text or "").strip()
        if not text and not image_paths:
            return
        bubble = MessageBubble(
            text, who, avatar, name_color, align_right, tag=tag,
            font_size=max(12, self._chat_font_size),
            image_paths=image_paths)
        self.bubble_layout.insertWidget(self.bubble_layout.count() - 1, bubble)
        # 布局需要两轮事件循环才会更新 scrollbar range，两个延迟都滚一次
        QTimer.singleShot(0, self._scroll_chat_to_bottom)
        QTimer.singleShot(80, self._scroll_chat_to_bottom)

    def _scroll_chat_to_bottom(self):
        try:
            self.log_content.adjustSize()
            sb = self.log.verticalScrollBar()
            sb.setValue(sb.maximum())
        except RuntimeError:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时把原生标题栏染成界面同色，使顶部白条融入暗色界面
        if not getattr(self, "_titlebar_styled", False):
            self._titlebar_styled = True
            apply_dark_title_bar(self, "#060a18")

    # ------------------------------------------------------------------ 拖放发送 ----
    def dragEnterEvent(self, event):
        if self._enabled and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in {
                    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                paths.append(str(p))
        if paths and self._enabled:
            self._emit_media(paths[:4], self.input.text().strip())
            event.acceptProposedAction()

    def closeEvent(self, event):
        # 右上角 × 就是“完全退出”：停止 Heart / GPT-SoVITS / Live2D 后退出程序
        # （旧版“有宠物时仅隐藏”的行为已废弃：× 一律完全退出）
        event.accept()
        self.quit_requested.emit()
