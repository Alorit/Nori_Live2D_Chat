"""首次使用向导：第一次启动时询问用户称呼。

只在 `gui.user_name` 为空且尚未跳过（`gui.first_run_done`）时弹出一次；
确定后由调用方把称呼写入 settings_overrides.json，之后可在
设置 → 基础设置 里随时修改。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from gui.winstyle import apply_dark_title_bar

_STYLE = """
QDialog { background: #14161f; }
QLabel { color: #e8ecf7; font-size: 14px; }
QLabel#WizardTitle { color: #ff9ecb; font-size: 19px; font-weight: bold; }
QLabel#WizardTip { color: #8fa6d8; font-size: 12px; }
QLineEdit {
    background: #1d2130; color: #e8ecf7;
    border: 1px solid #343d5c; border-radius: 8px;
    padding: 8px 10px; font-size: 14px;
    selection-background-color: #4a5a8a;
}
QLineEdit:focus { border-color: #ff9ecb; }
QPushButton {
    background: #262c42; color: #e8ecf7;
    border: 1px solid #3a4468; border-radius: 8px;
    padding: 6px 16px; font-size: 13px;
}
QPushButton:hover { background: #323a58; }
QPushButton#okBtn { background: #b0446c; border-color: #d76a94; }
QPushButton#okBtn:hover { background: #c95580; }
"""


class FirstRunDialog(QDialog):
    """询问用户称呼的极简向导。

    用法：
        dlg = FirstRunDialog(agent_name="Nori")
        dlg.exec()
        if dlg.user_name:   # 用户填了名字并点确定
            ...
    关闭/跳过时 user_name 为空字符串。
    """

    def __init__(self, agent_name: str = "Nori", parent=None):
        super().__init__(parent)
        self.agent_name = agent_name or "Nori"
        self.user_name = ""
        self.setWindowTitle("初次见面")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel(f"👋 你好，我是 {self.agent_name}！", self)
        title.setObjectName("WizardTitle")
        layout.addWidget(title)

        tip = QLabel("第一次见面，怎么称呼你呢？\n"
                     "以后我会在聊天里这样叫你，也可以随时在 设置 → 基础设置 里修改。",
                     self)
        tip.setObjectName("WizardTip")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#2a3149;")
        layout.addWidget(line)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("输入你的名字 / 昵称（留空则用“主人”）")
        self.name_edit.setMinimumHeight(38)
        self.name_edit.returnPressed.connect(self._on_accept)
        layout.addWidget(self.name_edit)

        buttons = QDialogButtonBox(self)
        ok_btn = buttons.addButton(QDialogButtonBox.Ok)
        skip_btn = buttons.addButton(QDialogButtonBox.Cancel)
        if ok_btn is not None:
            ok_btn.setObjectName("okBtn")
            ok_btn.setText("确定")
        if skip_btn is not None:
            skip_btn.setText("跳过")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.name_edit.setFocus()

    def showEvent(self, event):
        super().showEvent(event)
        # 与主窗口一致：把原生标题栏融入暗色界面
        if not getattr(self, "_titlebar_styled", False):
            self._titlebar_styled = True
            apply_dark_title_bar(self, "#14161f", "#e8ecf7")

    def _on_accept(self):
        self.user_name = self.name_edit.text().strip()
        self.accept()
