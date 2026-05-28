"""共用小组件:头像、分隔线、可点击的图、徽章等。"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QPixmap, QPainter, QBrush, QColor, QPen, QFont, QCursor
from PySide6.QtWidgets import QLabel, QFrame, QHBoxLayout, QVBoxLayout, QPushButton, QWidget, QSizePolicy

from .theme import C


def make_avatar(color: str, letter: str, size: int = 32) -> QPixmap:
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color))); p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QPen(QColor("white")))
    p.setFont(QFont("Inter Tight", int(size * 0.42), QFont.DemiBold))
    p.drawText(pm.rect(), Qt.AlignCenter, (letter or "?")[:1])
    p.end()
    return pm


def placeholder_pixmap(size: QSize, label: str = "无图") -> QPixmap:
    pm = QPixmap(size); pm.fill(QColor(C["surface_alt"]))
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(C["muted"])))
    p.setFont(QFont("Inter Tight", 10))
    p.drawText(pm.rect(), Qt.AlignCenter, label)
    p.end()
    return pm


class Hline(QFrame):
    def __init__(self, soft: bool = False):
        super().__init__()
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(
            f"background: {C['border_soft' if soft else 'border']}; max-height: 1px; border: none;"
        )


class Vline(QFrame):
    def __init__(self, soft: bool = True):
        super().__init__()
        self.setFrameShape(QFrame.VLine)
        self.setStyleSheet(
            f"background: {C['border_soft' if soft else 'border']}; max-width: 1px; border: none;"
        )


class Badge(QLabel):
    """彩色小徽章。"""
    def __init__(self, text: str, bg: str = None, fg: str = None, mono: bool = False):
        super().__init__(text)
        bg = bg or C["surface_alt"]
        fg = fg or C["muted"]
        font_family = '"JetBrains Mono", monospace' if mono else '"Inter Tight", sans-serif'
        self.setStyleSheet(f"""
            background: {bg}; color: {fg};
            font-family: {font_family}; font-size: 10px; font-weight: 500;
            padding: 2px 7px; border-radius: 3px;
        """)
        self.setAlignment(Qt.AlignCenter)


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("FieldLabel")
    return lbl


def section_header(title: str, subtitle: str = None) -> QWidget:
    w = QWidget()
    l = QVBoxLayout(w); l.setContentsMargins(0, 0, 0, 0); l.setSpacing(2)
    t = QLabel(title); t.setObjectName("H1")
    l.addWidget(t)
    if subtitle:
        s = QLabel(subtitle); s.setObjectName("Mono")
        l.addWidget(s)
    return w


class ThumbLabel(QLabel):
    """显示一张缩略图(优先本地路径,无则占位)。可点击。"""
    clicked = Signal()

    def __init__(self, size: tuple = (120, 80), placeholder_text: str = "无参考图"):
        super().__init__()
        self._size = QSize(*size)
        self._placeholder = placeholder_text
        self._path: Optional[Path] = None
        self.setFixedSize(self._size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"""
            background: {C['surface_alt']};
            border: 1px solid {C['border_soft']};
            border-radius: 6px; color: {C['muted']};
            font-size: 10px;
        """)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.set_image(None)

    def set_image(self, path: Optional[Path]):
        self._path = path
        if path and Path(path).exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                scaled = pm.scaled(self._size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                # 居中裁切
                x = max(0, (scaled.width() - self._size.width()) // 2)
                y = max(0, (scaled.height() - self._size.height()) // 2)
                cropped = scaled.copy(x, y, self._size.width(), self._size.height())
                self.setPixmap(cropped)
                return
        self.setPixmap(placeholder_pixmap(self._size, self._placeholder))

    def mousePressEvent(self, e):
        self.clicked.emit()
        super().mousePressEvent(e)


class ToolbarButton(QPushButton):
    """工具栏上的紧凑按钮。"""
    def __init__(self, text: str, primary: bool = False, accent: bool = False):
        super().__init__(text)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        if primary:    self.setObjectName("Primary")
        elif accent:   self.setObjectName("Accent")
        else:          self.setObjectName("Subtle")
