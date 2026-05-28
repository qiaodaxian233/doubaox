"""共用弹窗。"""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QPlainTextEdit, QDialogButtonBox, QFormLayout
)

from .theme import C
from .models import Project, Character, Scene, Prop, Episode, Shot


STYLE_OPTIONS = ["都市言情", "国风仙侠", "校园修仙", "古装宫廷", "悬疑推理",
                 "科幻末日", "情景喜剧", "真人写实", "童年回忆", "其他"]
ASPECT_OPTIONS = ["9:16 竖屏", "16:9 横屏", "1:1 方形", "4:5"]


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建项目")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {C['surface']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        title = QLabel("新建短剧项目")
        title.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C['ink']};")
        layout.addWidget(title)

        form = QFormLayout(); form.setSpacing(10); form.setContentsMargins(0, 6, 0, 6)

        self.name = QLineEdit(); self.name.setPlaceholderText("例:雨夜邂逅 / 童年回忆")
        form.addRow("项目名称", self.name)

        self.style = QComboBox(); self.style.addItems(STYLE_OPTIONS); self.style.setEditable(True)
        form.addRow("风格类型", self.style)

        self.aspect = QComboBox(); self.aspect.addItems(ASPECT_OPTIONS)
        form.addRow("画面比例", self.aspect)

        self.duration = QSpinBox()
        self.duration.setRange(10, 600); self.duration.setSingleStep(10)
        self.duration.setValue(60); self.duration.setSuffix(" 秒")
        form.addRow("目标时长", self.duration)

        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText("一句话简介(可选)")
        self.desc.setFixedHeight(70)
        form.addRow("简介", self.desc)

        layout.addLayout(form)

        btns = QDialogButtonBox()
        cancel = btns.addButton("取消", QDialogButtonBox.RejectRole)
        ok = btns.addButton("创建", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary"); ok.setCursor(QCursor(Qt.PointingHandCursor))
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def build_project(self) -> Project:
        return Project(
            name=self.name.text().strip() or "未命名项目",
            style=self.style.currentText().strip(),
            aspect_ratio=self.aspect.currentText().split()[0],  # 取 "9:16" 部分
            target_duration=self.duration.value(),
            description=self.desc.toPlainText().strip(),
        )


class NewEpisodeDialog(QDialog):
    def __init__(self, parent=None, next_number: int = 1):
        super().__init__(parent)
        self.setWindowTitle("新建集")
        self.setMinimumWidth(380)

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)
        title = QLabel("新建一集")
        title.setStyleSheet(f"font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        f = QFormLayout(); f.setSpacing(10)
        self.number = QSpinBox(); self.number.setRange(1, 999); self.number.setValue(next_number)
        f.addRow("集号", self.number)
        self.title = QLineEdit(); self.title.setPlaceholderText("第一集标题")
        f.addRow("标题", self.title)
        self.synopsis = QPlainTextEdit(); self.synopsis.setFixedHeight(60)
        self.synopsis.setPlaceholderText("剧情简介")
        f.addRow("简介", self.synopsis)
        self.arc = QLineEdit(); self.arc.setPlaceholderText("平静 → 惊愕 → 决绝")
        f.addRow("情绪曲线", self.arc)
        l.addLayout(f)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("创建", QDialogButtonBox.AcceptRole); ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def build_episode(self, project_id: str) -> Episode:
        return Episode(
            project_id=project_id,
            number=self.number.value(),
            title=self.title.text().strip() or f"第{self.number.value()}集",
            synopsis=self.synopsis.toPlainText().strip(),
            emotional_arc=self.arc.text().strip(),
        )
