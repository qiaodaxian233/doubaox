"""
DoubaoStudio - 多账号豆包管理 + 无水印媒体解析
基于 PySide6 (Qt for Python) + doubao-nomark

特性:
- 每个账号一个独立的 QWebEngineProfile,cookie/storage/cache 真隔离
- 直接 import doubao_parser 调用,无需起 HTTP 服务
- 账号/提示词 JSON 持久化,媒体落盘到 ~/.doubao-studio/media/
- Mock 模式可在未安装 doubao-nomark 时演示 UI

运行: python doubao_studio.py
"""
from __future__ import annotations

import sys
import os
import json
import asyncio
import time
import uuid
import webbrowser
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

from PySide6.QtCore import (
    Qt, Signal, QUrl, QObject, QThread, QSize, QTimer, QByteArray, QBuffer
)
from PySide6.QtGui import (
    QIcon, QColor, QFont, QPixmap, QPainter, QPen, QBrush, QAction,
    QDesktopServices, QShortcut, QKeySequence, QImage, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QTextEdit, QFrame, QScrollArea, QMenu, QMessageBox,
    QFileDialog, QStackedWidget, QToolButton, QSizePolicy, QPlainTextEdit,
    QDialog, QFormLayout, QDialogButtonBox, QInputDialog, QStyle, QStyleOption
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# --- Optional deps ---------------------------------------------------------
try:
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False

try:
    from doubao_parser.image import doubao_image_parse
    from doubao_parser.video import doubao_video_parse
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False
    doubao_image_parse = None
    doubao_video_parse = None


# ===========================================================================
# Constants
# ===========================================================================
APP_NAME = "豆包 Studio"
APP_DIR = Path.home() / ".doubao-studio"
APP_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNTS_FILE = APP_DIR / "accounts.json"
PROMPTS_FILE = APP_DIR / "prompts.json"
MEDIA_DIR = APP_DIR / "media"
MEDIA_DIR.mkdir(exist_ok=True)
PROFILES_DIR = APP_DIR / "profiles"
PROFILES_DIR.mkdir(exist_ok=True)

C = {
    "bg":          "#faf9f5",
    "surface":     "#ffffff",
    "surface_alt": "#f4f3ee",
    "ink":         "#0a0a0a",
    "ink_soft":    "#3f3f46",
    "muted":       "#71717a",
    "border":      "#e7e5e0",
    "border_soft": "#efede8",
    "accent":      "#dc5a3a",
    "accent_soft": "#fef3ee",
    "online":      "#16a34a",
    "warning":     "#f59e0b",
    "danger":      "#dc2626",
}

ACCOUNT_PALETTE = ["#1e3a8a", "#dc5a3a", "#15803d", "#7c3aed",
                   "#be185d", "#0d9488", "#b45309", "#0369a1"]

DEFAULT_ACCOUNTS = [
    {"id": "acc-1", "name": "主账号 · 内容生产", "color": "#1e3a8a"},
    {"id": "acc-2", "name": "快速通道 A",        "color": "#dc5a3a"},
    {"id": "acc-3", "name": "快速通道 B",        "color": "#15803d"},
]

DEFAULT_PROMPTS = [
    {"id": "p-1", "title": "小猫唱歌", "content": "生成10秒小猫唱歌视频,要可爱表情,卡通舞台背景,镜头慢推"},
    {"id": "p-2", "title": "古风打斗", "content": "生成10秒古风打斗视频,水墨风,飞檐走壁,慢动作飞跃"},
    {"id": "p-3", "title": "产品文案", "content": "写一段产品介绍文案,突出核心卖点和情感共鸣,200字以内"},
    {"id": "p-4", "title": "翻译英文", "content": "把下面这段中文翻译成自然流畅的英文,保留原有语气:\n\n"},
    {"id": "p-5", "title": "总结要点", "content": "把下面内容总结成 3-5 个关键要点,每条不超过 20 字:\n\n"},
    {"id": "p-6", "title": "山水画",   "content": "生成一张中国山水画风格的图片,云雾缭绕,远山近水,留白处理"},
]

MOCK_IMAGES_RESPONSE = {
    "success": True,
    "image_count": 3,
    "images": [
        {"url": f"https://picsum.photos/seed/d-cat-{i}/1024/768", "width": 1024, "height": 768}
        for i in range(1, 4)
    ],
}
MOCK_VIDEO_RESPONSE = {
    "success": True,
    "video": {
        "url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "width": 1920, "height": 1080, "definition": "1080p",
        "poster_url": "https://picsum.photos/seed/d-vid-poster/1920/1080",
    }
}


# ===========================================================================
# Data models + persistence
# ===========================================================================
@dataclass
class Account:
    id: str
    name: str
    color: str = "#1e3a8a"
    online: bool = True
    status: str = "已登录"

@dataclass
class Prompt:
    id: str
    title: str
    content: str

@dataclass
class MediaItem:
    id: str
    type: str            # "image" | "video"
    url: str
    width: int
    height: int
    source_url: str
    added_at: float
    definition: Optional[str] = None
    poster: Optional[str] = None
    local_path: Optional[str] = None


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def detect_link_type(url: str) -> Optional[str]:
    s = (url or "").strip()
    if "doubao.com/thread/" in s:
        return "image"
    if "video-sharing" in s:
        return "video"
    return None

def hhmmss():
    return datetime.now().strftime("%H:%M:%S")


# ===========================================================================
# Async worker: calls doubao_parser inside a QThread + asyncio
# ===========================================================================
class ParseWorker(QThread):
    finished_ok = Signal(dict, str)   # (response_dict, link_type)
    failed     = Signal(str)

    def __init__(self, url: str, link_type: str, use_mock: bool, parent=None):
        super().__init__(parent)
        self.url = url
        self.link_type = link_type
        self.use_mock = use_mock

    def run(self):
        try:
            if self.use_mock or not PARSER_AVAILABLE:
                time.sleep(0.6 + (uuid.uuid4().int % 400) / 1000)
                data = MOCK_IMAGES_RESPONSE if self.link_type == "image" else MOCK_VIDEO_RESPONSE
                self.finished_ok.emit(data, self.link_type)
                return

            coro = (doubao_image_parse(self.url, return_raw=False)
                    if self.link_type == "image"
                    else doubao_video_parse(self.url, return_raw=False))
            data = asyncio.run(coro)
            if not isinstance(data, dict) or not data.get("success"):
                raise RuntimeError(data.get("message", "解析失败,API 返回 success=False"))
            self.finished_ok.emit(data, self.link_type)
        except Exception as e:
            self.failed.emit(str(e))


# ===========================================================================
# Image fetcher for thumbnails (network on Qt event loop, no blocking)
# ===========================================================================
class ImageFetcher(QObject):
    """Single QNetworkAccessManager shared across the app."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._pending: Dict[QNetworkReply, callable] = {}
        self.nam.finished.connect(self._on_finished)

    def fetch(self, url: str, callback):
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 DoubaoStudio")
        reply = self.nam.get(req)
        self._pending[reply] = callback

    def _on_finished(self, reply: QNetworkReply):
        cb = self._pending.pop(reply, None)
        if not cb:
            reply.deleteLater(); return
        try:
            if reply.error() == QNetworkReply.NoError:
                data = bytes(reply.readAll())
                pm = QPixmap()
                if pm.loadFromData(data):
                    cb(pm)
                    return
            cb(None)
        finally:
            reply.deleteLater()


# ===========================================================================
# Stylesheet
# ===========================================================================
def build_stylesheet() -> str:
    return f"""
    QWidget {{
        background: {C['bg']};
        color: {C['ink']};
        font-family: "Inter Tight", "PingFang SC", "Microsoft YaHei UI",
                     "Segoe UI", "Noto Sans CJK SC", sans-serif;
        font-size: 13px;
    }}
    QFrame#Panel {{ background: {C['surface']}; }}
    QFrame#PanelAlt {{ background: {C['surface_alt']}; }}
    QFrame#Card {{
        background: {C['surface']};
        border: 1px solid {C['border_soft']};
        border-radius: 8px;
    }}
    QFrame#CardSelected {{
        background: {C['surface_alt']};
        border: 1px solid {C['ink']};
        border-radius: 8px;
    }}

    QLabel#H1 {{
        font-family: "Fraunces", "Source Han Serif SC", "Songti SC", "STSong", serif;
        font-size: 23px;
        font-weight: 500;
        color: {C['ink']};
        letter-spacing: -0.3px;
    }}
    QLabel#Mono, QLabel#SubMono {{
        font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace;
        font-size: 10px;
        letter-spacing: 1px;
        color: {C['muted']};
    }}
    QLabel#Secondary {{ color: {C['muted']}; font-size: 11px; }}
    QLabel#OnlineDot {{ color: {C['online']}; font-weight: 600; font-size: 11px; }}

    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {C['surface_alt']};
        border: 1px solid {C['border']};
        border-radius: 6px;
        padding: 6px 10px;
        color: {C['ink']};
        selection-background-color: {C['accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {C['ink']};
    }}

    QPushButton {{
        background: {C['surface']};
        border: 1px solid {C['border']};
        border-radius: 6px;
        padding: 6px 12px;
        color: {C['ink_soft']};
    }}
    QPushButton:hover {{ background: {C['surface_alt']}; }}
    QPushButton:disabled {{ color: {C['muted']}; background: {C['surface_alt']}; }}

    QPushButton#Primary {{
        background: {C['ink']};
        color: white;
        border: none;
        padding: 8px 14px;
        font-weight: 500;
    }}
    QPushButton#Primary:hover {{ background: #2a2a2a; }}

    QPushButton#Accent {{
        background: {C['accent']};
        color: white;
        border: none;
        padding: 6px 12px;
        font-weight: 500;
    }}
    QPushButton#Accent:hover {{ background: #c44d30; }}
    QPushButton#Accent:disabled {{ background: #e5b8aa; color: white; }}

    QPushButton#Pill {{
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 11px;
        color: {C['ink_soft']};
    }}
    QPushButton#PillDashed {{
        border: 1px dashed {C['border']};
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 11px;
        color: {C['muted']};
    }}
    QPushButton#TabActive {{
        background: {C['surface']};
        border: none;
        padding: 4px 10px;
        font-weight: 500;
        color: {C['ink']};
        border-radius: 4px;
    }}
    QPushButton#TabInactive {{
        background: transparent;
        border: none;
        padding: 4px 10px;
        color: {C['muted']};
    }}
    QPushButton#TabInactive:hover {{ color: {C['ink_soft']}; }}

    QPushButton#IconOnly {{
        border: none;
        background: transparent;
        padding: 4px;
        color: {C['muted']};
    }}
    QPushButton#IconOnly:hover {{ background: {C['surface_alt']}; border-radius: 4px; }}

    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #d4d4d4; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #a3a3a3; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: #d4d4d4; border-radius: 4px; min-width: 30px; }}

    QSplitter::handle {{ background: {C['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}

    QPlainTextEdit#Log {{
        background: {C['bg']};
        border: none;
        border-top: 1px solid {C['border_soft']};
        font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace;
        font-size: 11px;
        color: {C['ink_soft']};
        padding: 6px 12px;
    }}
    """


# ===========================================================================
# Reusable small widgets
# ===========================================================================
def make_avatar(color: str, letter: str, size: int = 32) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color)))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QPen(QColor("white")))
    f = QFont("Inter Tight", int(size * 0.42), QFont.DemiBold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, letter[:1] or "?")
    p.end()
    return pm


def online_dot(size: int = 6, color: str = None) -> QPixmap:
    pm = QPixmap(size + 2, size + 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color or C['online'])))
    p.setPen(QPen(QColor("white"), 2))
    p.drawEllipse(1, 1, size, size)
    p.end()
    return pm


class Hline(QFrame):
    def __init__(self, soft=False):
        super().__init__()
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(f"background: {C['border_soft' if soft else 'border']}; max-height: 1px; border: none;")


class Vline(QFrame):
    def __init__(self, soft=True):
        super().__init__()
        self.setFrameShape(QFrame.VLine)
        self.setStyleSheet(f"background: {C['border_soft' if soft else 'border']}; max-width: 1px; border: none;")


# ===========================================================================
# Account card
# ===========================================================================
class AccountCard(QFrame):
    selected = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, account: Account, index: int):
        super().__init__()
        self.account = account
        self.index = index
        self._is_selected = False
        self.setObjectName("Card")
        self.setCursor(QCursor(Qt.PointingHandCursor))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        avatar = QLabel()
        avatar.setPixmap(make_avatar(account.color, account.name[0], 32))
        avatar.setFixedSize(32, 32)
        top.addWidget(avatar)

        name_box = QVBoxLayout()
        name_box.setSpacing(2)
        self.name_label = QLabel(account.name)
        self.name_label.setStyleSheet(f"color: {C['ink']}; font-weight: 500; font-size: 13px;")
        self.name_label.setWordWrap(False)
        status = QLabel(account.status)
        status.setObjectName("Secondary")
        name_box.addWidget(self.name_label)
        name_box.addWidget(status)
        top.addLayout(name_box, 1)
        outer.addLayout(top)

        outer.addWidget(Hline(soft=True))

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        idx = QLabel(f"#{index + 1}")
        idx.setStyleSheet(f"""
            background: {C['surface_alt']};
            color: {C['muted']};
            font-family: "JetBrains Mono", monospace;
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 3px;
        """)
        bottom.addWidget(idx)
        bottom.addStretch()

        rename_btn = QPushButton("✎  更新名")
        rename_btn.setObjectName("IconOnly")
        rename_btn.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        rename_btn.clicked.connect(lambda: self.rename_requested.emit(self.account.id))
        bottom.addWidget(rename_btn)

        del_btn = QPushButton("🗑  删账号")
        del_btn.setObjectName("IconOnly")
        del_btn.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.account.id))
        bottom.addWidget(del_btn)

        outer.addLayout(bottom)

    def mousePressEvent(self, e):
        self.selected.emit(self.account.id)
        super().mousePressEvent(e)

    def set_selected(self, sel: bool):
        self._is_selected = sel
        self.setObjectName("CardSelected" if sel else "Card")
        # Re-apply stylesheet so objectName change takes effect
        self.style().unpolish(self); self.style().polish(self)

    def update_name(self, name: str):
        self.name_label.setText(name)


# ===========================================================================
# Account panel
# ===========================================================================
class AccountPanel(QFrame):
    account_selected = Signal(str)
    accounts_changed = Signal()

    def __init__(self, accounts: List[Account]):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(300)
        self.accounts = accounts
        self.selected_id = accounts[0].id if accounts else None
        self.cards: Dict[str, AccountCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 0)
        root.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("账号管理")
        title.setObjectName("H1")
        self.online_label = QLabel(f"● {sum(1 for a in accounts if a.online)} 在线")
        self.online_label.setObjectName("OnlineDot")
        header.addWidget(title); header.addStretch(); header.addWidget(self.online_label)
        root.addLayout(header)

        subtitle = QLabel("INDEPENDENT CACHE · 独立缓存账号池")
        subtitle.setObjectName("Mono")
        subtitle.setContentsMargins(0, 4, 0, 16)
        root.addWidget(subtitle)

        # Search
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍   搜索账号名称 / 备注")
        self.search.textChanged.connect(self._refresh_list)
        root.addWidget(self.search)

        # Add button
        add_btn = QPushButton("＋  添加国内账号")
        add_btn.setObjectName("Primary")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.clicked.connect(self._add_account)
        root.addSpacing(10)
        root.addWidget(add_btn)

        # List header
        list_hdr = QHBoxLayout()
        list_hdr.setContentsMargins(0, 20, 0, 4)
        lh1 = QLabel("账号列表"); lh1.setObjectName("Mono")
        self.count_label = QLabel(f"{len(accounts)} 个账号"); self.count_label.setObjectName("Mono")
        list_hdr.addWidget(lh1); list_hdr.addStretch(); list_hdr.addWidget(self.count_label)
        root.addLayout(list_hdr)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 4, 0, 16)
        self.list_layout.setSpacing(8)
        scroll.setWidget(self.list_holder)
        root.addWidget(scroll, 1)

        self._refresh_list()

    def _refresh_list(self):
        # Clear
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
        self.cards.clear()

        q = self.search.text().lower().strip()
        for i, acc in enumerate(self.accounts):
            if q and q not in acc.name.lower():
                continue
            card = AccountCard(acc, i)
            card.selected.connect(self._on_select)
            card.rename_requested.connect(self._rename)
            card.delete_requested.connect(self._delete)
            if acc.id == self.selected_id:
                card.set_selected(True)
            self.list_layout.addWidget(card)
            self.cards[acc.id] = card
        self.list_layout.addStretch()
        self.count_label.setText(f"{len(self.accounts)} 个账号")
        self.online_label.setText(f"● {sum(1 for a in self.accounts if a.online)} 在线")

    def _on_select(self, acc_id: str):
        self.selected_id = acc_id
        for aid, card in self.cards.items():
            card.set_selected(aid == acc_id)
        self.account_selected.emit(acc_id)

    def _add_account(self):
        new_id = f"acc-{int(time.time() * 1000)}"
        color = ACCOUNT_PALETTE[len(self.accounts) % len(ACCOUNT_PALETTE)]
        acc = Account(id=new_id, name=f"新账号 {len(self.accounts) + 1}", color=color)
        self.accounts.append(acc)
        self.selected_id = new_id
        self._refresh_list()
        self.accounts_changed.emit()
        self.account_selected.emit(new_id)

    def _rename(self, acc_id: str):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        new_name, ok = QInputDialog.getText(self, "重命名账号", "新名称:", QLineEdit.Normal, acc.name)
        if ok and new_name.strip():
            acc.name = new_name.strip()
            self._refresh_list()
            self.accounts_changed.emit()

    def _delete(self, acc_id: str):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        ans = QMessageBox.question(self, "删除账号", f"删除「{acc.name}」?\n此账号的本地缓存目录也会被保留(可手动清理)。",
                                   QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        if self.selected_id == acc_id:
            self.selected_id = self.accounts[0].id if self.accounts else None
        self._refresh_list()
        self.accounts_changed.emit()
        if self.selected_id:
            self.account_selected.emit(self.selected_id)


# ===========================================================================
# Workspace panel (per-account QWebEngineView with isolated profile)
# ===========================================================================
class WorkspacePanel(QFrame):
    log = Signal(str)

    def __init__(self, prompts: List[Prompt]):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.prompts = prompts
        self.views: Dict[str, QWebEngineView] = {}        # account_id -> view
        self.profiles: Dict[str, QWebEngineProfile] = {}  # account_id -> profile
        self.current_account_id: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === Browser-like nav bar ===
        nav = QFrame(); nav.setObjectName("Panel")
        nav_l = QHBoxLayout(nav)
        nav_l.setContentsMargins(12, 8, 12, 8); nav_l.setSpacing(4)
        for label, fn in [("◀", "back"), ("▶", "fwd"), ("⟳", "reload"), ("⌂", "home")]:
            b = QPushButton(label)
            b.setObjectName("IconOnly")
            b.setFixedSize(28, 28)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, f=fn: self._nav(f))
            nav_l.addWidget(b)
        nav_l.addStretch()
        tab_pill = QLabel("⛁  豆包网页工作区")
        tab_pill.setStyleSheet(f"""
            background: {C['surface_alt']};
            color: {C['ink_soft']};
            padding: 4px 14px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        """)
        nav_l.addWidget(tab_pill)
        nav_l.addStretch()
        iso_tag = QLabel("独立缓存会话")
        iso_tag.setStyleSheet(f"""
            background: {C['accent_soft']};
            color: {C['accent']};
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        """)
        nav_l.addWidget(iso_tag)
        root.addWidget(nav)
        root.addWidget(Hline())

        # === Main content area: web view stack on top, prompt+input on bottom ===
        main_area = QFrame(); main_area.setObjectName("PanelAlt")
        ma_l = QVBoxLayout(main_area)
        ma_l.setContentsMargins(0, 0, 0, 0); ma_l.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("PanelAlt")

        # Default fallback widget (shown when no account / no webengine)
        self.fallback = self._build_fallback()
        self.stack.addWidget(self.fallback)
        ma_l.addWidget(self.stack, 1)

        # === Prompt strip + input ===
        bottom_wrap = QFrame(); bottom_wrap.setObjectName("PanelAlt")
        bw_l = QVBoxLayout(bottom_wrap)
        bw_l.setContentsMargins(24, 8, 24, 18); bw_l.setSpacing(0)

        self.input_card = QFrame(); self.input_card.setObjectName("Card")
        ic_l = QVBoxLayout(self.input_card)
        ic_l.setContentsMargins(0, 0, 0, 0); ic_l.setSpacing(0)

        # Prompt strip
        self.prompt_bar = QFrame()
        pb_l = QVBoxLayout(self.prompt_bar)
        pb_l.setContentsMargins(12, 10, 12, 8); pb_l.setSpacing(8)

        prompt_row = QHBoxLayout(); prompt_row.setSpacing(6)
        prompt_label = QLabel("✦ 提示词")
        prompt_label.setStyleSheet(f"""
            color: {C['muted']};
            font-family: "JetBrains Mono", "Consolas", monospace;
            font-size: 10px;
            letter-spacing: 1px;
        """)
        prompt_row.addWidget(prompt_label)
        prompt_row.addWidget(Vline())
        prompt_row.addSpacing(4)

        self.prompt_scroll = QScrollArea()
        self.prompt_scroll.setWidgetResizable(True)
        self.prompt_scroll.setFixedHeight(32)
        self.prompt_scroll.setFrameShape(QFrame.NoFrame)
        self.prompt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.prompt_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.prompt_holder = QWidget()
        self.prompt_holder_l = QHBoxLayout(self.prompt_holder)
        self.prompt_holder_l.setContentsMargins(0, 0, 0, 0); self.prompt_holder_l.setSpacing(6)
        self.prompt_scroll.setWidget(self.prompt_holder)
        prompt_row.addWidget(self.prompt_scroll, 1)

        pb_l.addLayout(prompt_row)

        # Editor row (hidden by default)
        self.editor_row = QHBoxLayout(); self.editor_row.setSpacing(6)
        self.editor_widget = QFrame()
        self.editor_widget.setLayout(self.editor_row)
        self.editor_title = QLineEdit(); self.editor_title.setPlaceholderText("标题"); self.editor_title.setFixedWidth(110)
        self.editor_content = QLineEdit(); self.editor_content.setPlaceholderText("提示词内容,如:生成10秒小猫唱歌视频")
        save_btn = QPushButton("保存"); save_btn.setObjectName("Primary"); save_btn.setFixedWidth(60)
        save_btn.clicked.connect(self._save_prompt)
        self.editor_content.returnPressed.connect(self._save_prompt)
        cancel_btn = QPushButton("✕"); cancel_btn.setObjectName("IconOnly"); cancel_btn.setFixedSize(28, 28)
        cancel_btn.clicked.connect(self._hide_editor)
        self.editor_row.addWidget(self.editor_title); self.editor_row.addWidget(self.editor_content, 1)
        self.editor_row.addWidget(save_btn); self.editor_row.addWidget(cancel_btn)
        self.editor_widget.hide()
        pb_l.addWidget(self.editor_widget)

        ic_l.addWidget(self.prompt_bar)
        ic_l.addWidget(Hline(soft=True))

        # Chat input
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText("发消息... (点击上方提示词快速填入)")
        self.chat_input.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {C['surface']};
                border: none;
                padding: 10px 14px;
                font-size: 13px;
                color: {C['ink']};
            }}
        """)
        self.chat_input.setFixedHeight(48)
        ic_l.addWidget(self.chat_input)

        # Action row
        action_row = QHBoxLayout()
        action_row.setContentsMargins(10, 6, 10, 10); action_row.setSpacing(6)
        action_row.addWidget(self._action_btn("＋", icon_only=True))
        action_row.addWidget(self._pill_btn("⚡ 快速", accent=True))
        action_row.addWidget(self._pill_btn("▶ 视频生成"))
        action_row.addWidget(self._pill_btn("✦ 超能模式", badge="Beta"))
        action_row.addWidget(self._pill_btn("⋯ 更多"))
        action_row.addStretch()
        action_row.addWidget(self._action_btn("🎤", icon_only=True))
        ic_l.addLayout(action_row)

        bw_l.addWidget(self.input_card)
        ma_l.addWidget(bottom_wrap)

        root.addWidget(main_area, 1)

        self._refresh_prompts()

    def _build_fallback(self) -> QWidget:
        w = QFrame(); w.setObjectName("PanelAlt")
        l = QVBoxLayout(w); l.setContentsMargins(40, 60, 40, 40); l.setAlignment(Qt.AlignCenter)

        box = QFrame(); box.setObjectName("Card")
        box.setMaximumWidth(520)
        bl = QVBoxLayout(box); bl.setContentsMargins(30, 30, 30, 30); bl.setSpacing(12)
        bl.setAlignment(Qt.AlignCenter)
        icon = QLabel("⌬"); icon.setStyleSheet(f"font-size: 36px; color: {C['muted']};")
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("豆包工作区 · WebView")
        title.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C['ink']};")
        title.setAlignment(Qt.AlignCenter)
        if WEBENGINE_AVAILABLE:
            desc_text = ("选中左侧账号即可加载独立 session 的豆包页面。\n"
                         "每个账号拥有独立的 cookies / localStorage / cache。")
        else:
            desc_text = ("未检测到 PySide6-WebEngine。请安装:\n"
                         "    pip install PySide6 PySide6-Addons\n"
                         "安装后此处会显示真实的豆包页面。")
        desc = QLabel(desc_text)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {C['muted']}; font-size: 12px; line-height: 1.6;")
        desc.setAlignment(Qt.AlignCenter)
        bl.addWidget(icon); bl.addWidget(title); bl.addWidget(desc)
        l.addWidget(box)
        return w

    def _action_btn(self, label: str, icon_only=False) -> QPushButton:
        b = QPushButton(label)
        if icon_only:
            b.setObjectName("IconOnly")
            b.setFixedSize(28, 28)
        return b

    def _pill_btn(self, label: str, accent=False, badge: Optional[str] = None) -> QPushButton:
        text = label
        if badge: text += f"  [{badge}]"
        b = QPushButton(text)
        b.setObjectName("Pill")
        b.setStyleSheet(f"""
            QPushButton#Pill {{
                border: 1px solid {C['border']};
                border-radius: 12px;
                padding: 4px 10px;
                font-size: 11px;
                color: {C['accent'] if accent else C['ink_soft']};
                background: {C['surface']};
            }}
            QPushButton#Pill:hover {{ background: {C['surface_alt']}; }}
        """)
        return b

    # --- Account / view management ---
    def set_account(self, account: Account):
        """Switch to (or create) the web view for this account."""
        self.current_account_id = account.id
        if not WEBENGINE_AVAILABLE:
            self.stack.setCurrentWidget(self.fallback)
            return

        if account.id not in self.views:
            # Create profile + view
            profile_dir = PROFILES_DIR / account.id
            profile_dir.mkdir(parents=True, exist_ok=True)
            cache_dir = profile_dir / "cache"
            storage_dir = profile_dir / "storage"
            cache_dir.mkdir(exist_ok=True)
            storage_dir.mkdir(exist_ok=True)

            # Storage name must be unique per profile to isolate cookies
            profile = QWebEngineProfile(f"doubao-{account.id}", self)
            profile.setPersistentStoragePath(str(storage_dir))
            profile.setCachePath(str(cache_dir))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
            profile.setHttpUserAgent(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            view = QWebEngineView()
            page = QWebEnginePage(profile, view)
            view.setPage(page)
            view.load(QUrl("https://www.doubao.com/chat"))

            self.profiles[account.id] = profile
            self.views[account.id] = view
            self.stack.addWidget(view)
            self.log.emit(f"创建账号 session · {account.name} · profile={profile.storageName()}")

        self.stack.setCurrentWidget(self.views[account.id])

    def remove_account_view(self, account_id: str):
        if account_id in self.views:
            v = self.views.pop(account_id)
            self.stack.removeWidget(v); v.deleteLater()
        if account_id in self.profiles:
            self.profiles.pop(account_id).deleteLater()

    def _nav(self, action: str):
        v = self.views.get(self.current_account_id)
        if not v: return
        if   action == "back":   v.back()
        elif action == "fwd":    v.forward()
        elif action == "reload": v.reload()
        elif action == "home":   v.load(QUrl("https://www.doubao.com/chat"))

    # --- Prompts ---
    def _refresh_prompts(self):
        # Clear
        while self.prompt_holder_l.count():
            item = self.prompt_holder_l.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()

        for p in self.prompts:
            btn = QPushButton(p.title)
            btn.setObjectName("Pill")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setToolTip(p.content)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid {C['border']};
                    background: {C['surface']};
                    border-radius: 12px;
                    padding: 4px 10px;
                    font-size: 11px;
                    color: {C['ink_soft']};
                }}
                QPushButton:hover {{ background: {C['surface_alt']}; }}
            """)
            btn.clicked.connect(lambda _, pp=p: self._apply_prompt(pp))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, pid=p.id: self._prompt_menu(pid, pos))
            self.prompt_holder_l.addWidget(btn)

        add_btn = QPushButton("＋ 新增")
        add_btn.setObjectName("PillDashed")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px dashed {C['border']};
                background: transparent;
                border-radius: 12px;
                padding: 4px 10px;
                font-size: 11px;
                color: {C['muted']};
            }}
            QPushButton:hover {{ background: {C['surface_alt']}; }}
        """)
        add_btn.clicked.connect(self._show_editor)
        self.prompt_holder_l.addWidget(add_btn)
        self.prompt_holder_l.addStretch()

    def _apply_prompt(self, p: Prompt):
        self.chat_input.setPlainText(p.content)
        self.chat_input.setFocus()
        cur = self.chat_input.textCursor()
        cur.movePosition(cur.End)
        self.chat_input.setTextCursor(cur)
        self.log.emit(f"应用提示词 · {p.title}")

    def _show_editor(self):
        self.editor_widget.show()
        self.editor_title.setFocus()

    def _hide_editor(self):
        self.editor_widget.hide()
        self.editor_title.clear(); self.editor_content.clear()

    def _save_prompt(self):
        title = self.editor_title.text().strip()
        content = self.editor_content.text().strip()
        if not title or not content: return
        self.prompts.append(Prompt(id=f"p-{int(time.time()*1000)}", title=title, content=content))
        save_json(PROMPTS_FILE, [asdict(p) for p in self.prompts])
        self._hide_editor()
        self._refresh_prompts()
        self.log.emit(f"新增提示词 · {title}")

    def _prompt_menu(self, pid: str, pos):
        m = QMenu(self)
        del_act = m.addAction("删除")
        chosen = m.exec(QCursor.pos())
        if chosen == del_act:
            self.prompts = [p for p in self.prompts if p.id != pid]
            save_json(PROMPTS_FILE, [asdict(p) for p in self.prompts])
            self._refresh_prompts()
            self.log.emit("删除提示词")


# ===========================================================================
# Media card
# ===========================================================================
class MediaCard(QFrame):
    delete_requested = Signal(str)

    def __init__(self, item: MediaItem, fetcher: ImageFetcher):
        super().__init__()
        self.item = item
        self.setObjectName("Card")
        self.setStyleSheet(self.styleSheet() + f"""
            QFrame#Card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 8px; }}
        """)

        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        # Thumbnail
        self.thumb = QLabel()
        self.thumb.setFixedHeight(170)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(f"background: #ececec; border-top-left-radius: 8px; border-top-right-radius: 8px;")
        self.thumb.setText("加载中…")
        v.addWidget(self.thumb)

        # Footer
        f = QFrame()
        fl = QHBoxLayout(f); fl.setContentsMargins(10, 8, 8, 8); fl.setSpacing(6)
        label = QLabel(f"{datetime.fromtimestamp(item.added_at).strftime('%H:%M:%S')} · {item.id[-8:]}")
        label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        fl.addWidget(label, 1)

        for emoji, tip, fn in [
            ("⬇", "下载", self._download),
            ("⧉", "复制链接", self._copy_url),
            ("↗", "外部打开", self._external),
            ("✕", "删除", lambda: self.delete_requested.emit(item.id)),
        ]:
            b = QPushButton(emoji); b.setObjectName("IconOnly"); b.setFixedSize(24, 24)
            b.setToolTip(tip); b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(fn)
            fl.addWidget(b)
        v.addWidget(f)

        # Fetch thumbnail
        thumb_url = item.poster if item.type == "video" else item.url
        fetcher.fetch(thumb_url, self._set_thumb)

    def _set_thumb(self, pm: Optional[QPixmap]):
        if pm is None or pm.isNull():
            self.thumb.setText("⚠ 无预览")
            self.thumb.setStyleSheet(f"background: #ececec; color: {C['muted']}; font-size: 11px;")
            return
        scaled = pm.scaled(self.thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        # Crop center
        x = max(0, (scaled.width() - self.thumb.width()) // 2)
        y = max(0, (scaled.height() - self.thumb.height()) // 2)
        scaled = scaled.copy(x, y, self.thumb.width(), self.thumb.height())

        # Overlay for video (play icon + size tag)
        if self.item.type == "video":
            p = QPainter(scaled); p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(scaled.rect(), QColor(0, 0, 0, 60))
            cx, cy = scaled.width() // 2, scaled.height() // 2
            p.setBrush(QBrush(QColor(255, 255, 255, 230))); p.setPen(Qt.NoPen)
            p.drawEllipse(cx - 22, cy - 22, 44, 44)
            p.setBrush(QBrush(QColor(C['ink']))); p.setPen(Qt.NoPen)
            from PySide6.QtGui import QPolygon
            from PySide6.QtCore import QPoint
            p.drawPolygon(QPolygon([QPoint(cx - 6, cy - 9), QPoint(cx + 10, cy), QPoint(cx - 6, cy + 9)]))
            p.end()

        # Draw resolution tag
        tag = f"{self.item.width}×{self.item.height}"
        if self.item.definition: tag += f" · {self.item.definition}"
        p = QPainter(scaled); p.setRenderHint(QPainter.Antialiasing)
        f = QFont("JetBrains Mono", 8); p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(tag) + 12; th = fm.height() + 4
        p.setBrush(QBrush(QColor(0, 0, 0, 180))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(scaled.width() - tw - 8, 8, tw, th, 3, 3)
        p.setPen(QPen(QColor("white")))
        p.drawText(scaled.width() - tw - 2, 8 + th - 5, tag)
        p.end()

        self.thumb.setPixmap(scaled)

    def _download(self):
        if self.item.local_path and Path(self.item.local_path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.item.local_path).parent)))
        else:
            QDesktopServices.openUrl(QUrl(self.item.url))

    def _copy_url(self):
        QApplication.clipboard().setText(self.item.url)

    def _external(self):
        QDesktopServices.openUrl(QUrl(self.item.url))


# ===========================================================================
# Media panel (doubao-nomark integration)
# ===========================================================================
class MediaPanel(QFrame):
    log = Signal(str)

    def __init__(self, fetcher: ImageFetcher):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(380)
        self.fetcher = fetcher
        self.items: List[MediaItem] = []
        self.filter = "all"
        self.use_mock = not PARSER_AVAILABLE
        self.worker: Optional[ParseWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 0)
        root.setSpacing(0)

        # Header
        hdr = QHBoxLayout()
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("媒体列表"); title.setObjectName("H1")
        sub = QLabel("NO-WATERMARK · 图片 / 视频"); sub.setObjectName("Mono")
        title_box.addWidget(title); title_box.addWidget(sub)
        hdr.addLayout(title_box); hdr.addStretch()

        self.cfg_btn = QPushButton("⚙"); self.cfg_btn.setObjectName("IconOnly")
        self.cfg_btn.setFixedSize(28, 28)
        self.cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.cfg_btn.clicked.connect(self._toggle_config)
        hdr.addWidget(self.cfg_btn)
        root.addLayout(hdr)
        root.addSpacing(12)

        # Filter tabs + batch
        tabs_row = QHBoxLayout()
        tabs_wrap = QFrame()
        tabs_wrap.setStyleSheet(f"background: {C['surface_alt']}; border-radius: 6px; padding: 2px;")
        tw_l = QHBoxLayout(tabs_wrap); tw_l.setContentsMargins(2, 2, 2, 2); tw_l.setSpacing(0)
        self.tab_buttons = {}
        for key, lbl in [("all", "全部"), ("image", "图片"), ("video", "视频")]:
            b = QPushButton(lbl)
            b.setObjectName("TabActive" if key == "all" else "TabInactive")
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, k=key: self._set_filter(k))
            tw_l.addWidget(b)
            self.tab_buttons[key] = b
        tabs_row.addWidget(tabs_wrap); tabs_row.addStretch()
        root.addLayout(tabs_row)
        root.addSpacing(14)

        # Parse input card
        parse_card = QFrame(); parse_card.setObjectName("Card")
        parse_card.setStyleSheet(f"QFrame#Card {{ background: {C['surface_alt']}; }}")
        pc_l = QVBoxLayout(parse_card); pc_l.setContentsMargins(0, 0, 0, 0); pc_l.setSpacing(0)

        pc_hdr = QHBoxLayout(); pc_hdr.setContentsMargins(12, 8, 12, 8)
        pc_hdr_l = QLabel("🔗  PARSE LINK"); pc_hdr_l.setObjectName("Mono")
        self.type_tag = QLabel(""); self.type_tag.hide()
        pc_hdr.addWidget(pc_hdr_l); pc_hdr.addStretch(); pc_hdr.addWidget(self.type_tag)
        pc_l.addLayout(pc_hdr)
        pc_l.addWidget(Hline(soft=True))

        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "粘贴豆包分享链接\n"
            "https://www.doubao.com/thread/...\n"
            "https://www.doubao.com/video-sharing?share_id=..."
        )
        self.url_input.setFixedHeight(70)
        self.url_input.setStyleSheet(f"""
            QPlainTextEdit {{
                background: transparent; border: none; padding: 8px 12px;
                font-family: "JetBrains Mono", monospace; font-size: 11px;
                color: {C['ink']};
            }}
        """)
        self.url_input.textChanged.connect(self._on_url_changed)
        pc_l.addWidget(self.url_input)
        pc_l.addWidget(Hline(soft=True))

        # Action row
        act_row = QHBoxLayout(); act_row.setContentsMargins(10, 6, 10, 8); act_row.setSpacing(6)
        self.status_label = QLabel("就绪 · 自动识别链接类型")
        self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        act_row.addWidget(self.status_label, 1)
        self.parse_btn = QPushButton("✂  提取无水印")
        self.parse_btn.setObjectName("Accent")
        self.parse_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.parse_btn.setEnabled(False)
        self.parse_btn.clicked.connect(self._do_parse)
        act_row.addWidget(self.parse_btn)
        pc_l.addLayout(act_row)
        root.addWidget(parse_card)

        # Sample links
        sample_row = QHBoxLayout()
        sample_row.setContentsMargins(0, 6, 0, 0)
        sample_lbl = QLabel("示例:"); sample_lbl.setObjectName("Mono")
        sample_row.addWidget(sample_lbl)
        for name, url in [
            ("图片链接", "https://www.doubao.com/thread/c1234567890"),
            ("视频链接", "https://www.doubao.com/video-sharing?share_id=abc&video_id=v1"),
        ]:
            b = QPushButton(name)
            b.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    color: {C['muted']}; font-size: 10px;
                    text-decoration: underline; padding: 0 6px;
                }}
                QPushButton:hover {{ color: {C['ink']}; }}
            """)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, u=url: self.url_input.setPlainText(u))
            sample_row.addWidget(b)
        sample_row.addStretch()
        root.addLayout(sample_row)

        # Config card (collapsible)
        self.config_card = self._build_config_card()
        self.config_card.hide()
        root.addWidget(self.config_card)

        # Media scroll
        self.media_scroll = QScrollArea()
        self.media_scroll.setWidgetResizable(True)
        self.media_scroll.setFrameShape(QFrame.NoFrame)
        self.media_holder = QWidget()
        self.media_layout = QVBoxLayout(self.media_holder)
        self.media_layout.setContentsMargins(0, 14, 0, 14); self.media_layout.setSpacing(10)
        self.media_scroll.setWidget(self.media_holder)
        root.addWidget(self.media_scroll, 1)

        self._refresh_media()

    def _build_config_card(self) -> QFrame:
        card = QFrame(); card.setObjectName("Card")
        card.setStyleSheet(f"QFrame#Card {{ background: {C['surface_alt']}; }}")
        cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 12); cl.setSpacing(8)

        hdr = QLabel("API CONFIG · DOUBAO-NOMARK"); hdr.setObjectName("Mono")
        cl.addWidget(hdr)

        toggle_row = QHBoxLayout(); toggle_row.setSpacing(0)
        toggle_wrap = QFrame()
        toggle_wrap.setStyleSheet(f"background: {C['surface']}; border: 1px solid {C['border_soft']}; border-radius: 6px;")
        tw_l = QHBoxLayout(toggle_wrap); tw_l.setContentsMargins(2, 2, 2, 2); tw_l.setSpacing(0)
        self.mock_btn = QPushButton("⚗  Mock 数据"); self.real_btn = QPushButton("🔌  真实库")
        for b in (self.mock_btn, self.real_btn):
            b.setCursor(QCursor(Qt.PointingHandCursor))
            tw_l.addWidget(b)
        self.mock_btn.clicked.connect(lambda: self._set_mode(True))
        self.real_btn.clicked.connect(lambda: self._set_mode(False))
        toggle_row.addWidget(toggle_wrap, 1)
        cl.addLayout(toggle_row)

        self.cfg_desc = QLabel("")
        self.cfg_desc.setWordWrap(True)
        self.cfg_desc.setStyleSheet(f"color: {C['muted']}; font-size: 10.5px; line-height: 1.6;")
        cl.addWidget(self.cfg_desc)

        self._update_mode_buttons()
        return card

    def _toggle_config(self):
        self.config_card.setVisible(not self.config_card.isVisible())

    def _set_mode(self, use_mock: bool):
        if not use_mock and not PARSER_AVAILABLE:
            QMessageBox.warning(self, "缺少 doubao-nomark",
                "未检测到 doubao_parser 模块。请先安装:\n\n"
                "git clone https://github.com/ihmily/doubao-nomark\n"
                "cd doubao-nomark && pip install -e .\n\n"
                "现在将继续使用 Mock 模式。")
            return
        self.use_mock = use_mock
        self._update_mode_buttons()
        self.log.emit(f"切换 API 模式 · {'MOCK' if use_mock else 'LIVE (doubao_parser)'}")

    def _update_mode_buttons(self):
        for b, active in [(self.mock_btn, self.use_mock), (self.real_btn, not self.use_mock)]:
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {C['ink'] if active else 'transparent'};
                    color: {'white' if active else C['muted']};
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: 500;
                }}
            """)
        if self.use_mock:
            self.cfg_desc.setText("使用内置 mock 数据,无需 doubao-nomark 即可演示完整流程。")
        else:
            self.cfg_desc.setText(
                "直接 import doubao_parser.image / video 调用解析函数,无需 HTTP 服务。\n"
                f"模块状态:{'✓ 已加载' if PARSER_AVAILABLE else '✗ 未安装'}"
            )

    # --- URL handling ---
    def _on_url_changed(self):
        txt = self.url_input.toPlainText()
        t = detect_link_type(txt)
        if t:
            self.type_tag.show()
            self.type_tag.setText("识别为图片" if t == "image" else "识别为视频")
            self.type_tag.setStyleSheet(f"""
                background: {C['accent_soft']}; color: {C['accent']};
                padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 500;
            """)
            self.parse_btn.setEnabled(True)
        else:
            self.type_tag.hide()
            self.parse_btn.setEnabled(False)

    def _do_parse(self):
        url = self.url_input.toPlainText().strip()
        link_type = detect_link_type(url)
        if not link_type: return

        self.parse_btn.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        self.status_label.setText("正在调用解析…")
        self.log.emit(f"开始解析 {('图片' if link_type=='image' else '视频')} · {'MOCK' if self.use_mock else 'LIVE'}")

        self.worker = ParseWorker(url, link_type, self.use_mock)
        self.worker.finished_ok.connect(self._on_parse_ok)
        self.worker.failed.connect(self._on_parse_fail)
        self.worker.start()

    def _on_parse_ok(self, data: dict, link_type: str):
        now = time.time()
        if link_type == "image":
            new_items = [
                MediaItem(id=f"img-{int(now*1000)}-{i}", type="image",
                          url=img["url"], width=img["width"], height=img["height"],
                          source_url=self.url_input.toPlainText().strip(), added_at=now)
                for i, img in enumerate(data.get("images", []))
            ]
            msg = f"解析成功 · 提取 {data.get('image_count', len(new_items))} 张无水印图片"
        else:
            v = data["video"]
            new_items = [MediaItem(
                id=f"vid-{int(now*1000)}", type="video",
                url=v["url"], width=v["width"], height=v["height"],
                source_url=self.url_input.toPlainText().strip(), added_at=now,
                definition=v.get("definition"), poster=v.get("poster_url"),
            )]
            msg = f"解析成功 · 提取 1 个 {v.get('definition','')} 视频"

        self.items = new_items + self.items
        self.log.emit(msg)
        self.status_label.setStyleSheet(f"color: {C['online']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        self.status_label.setText(msg)
        self.url_input.clear()
        self.parse_btn.setEnabled(False)
        QTimer.singleShot(2200, lambda: self.status_label.setText("就绪 · 自动识别链接类型") or
                          self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;"))
        self._refresh_media()

    def _on_parse_fail(self, err: str):
        self.log.emit(f"解析失败 · {err}")
        self.status_label.setStyleSheet(f"color: {C['danger']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        self.status_label.setText(f"失败 · {err[:60]}")
        self.parse_btn.setEnabled(True)

    # --- Filter & list ---
    def _set_filter(self, key: str):
        self.filter = key
        for k, b in self.tab_buttons.items():
            b.setObjectName("TabActive" if k == key else "TabInactive")
            b.style().unpolish(b); b.style().polish(b)
        self._refresh_media()

    def _refresh_media(self):
        while self.media_layout.count():
            it = self.media_layout.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

        filtered = self.items if self.filter == "all" else [m for m in self.items if m.type == self.filter]
        if not filtered:
            empty = QFrame()
            el = QVBoxLayout(empty); el.setContentsMargins(0, 40, 0, 40); el.setAlignment(Qt.AlignCenter)
            icon = QLabel("📭"); icon.setStyleSheet("font-size: 28px;"); icon.setAlignment(Qt.AlignCenter)
            txt = QLabel("暂无媒体"); txt.setStyleSheet(f"color: {C['ink_soft']}; font-weight: 500;"); txt.setAlignment(Qt.AlignCenter)
            tip = QLabel("粘贴豆包分享链接,点击「提取无水印」开始")
            tip.setStyleSheet(f"color: {C['muted']}; font-size: 11px;"); tip.setAlignment(Qt.AlignCenter); tip.setWordWrap(True)
            el.addWidget(icon); el.addWidget(txt); el.addWidget(tip)
            self.media_layout.addWidget(empty)
            self.media_layout.addStretch()
            return

        for m in filtered:
            card = MediaCard(m, self.fetcher)
            card.delete_requested.connect(self._delete_one)
            self.media_layout.addWidget(card)
        self.media_layout.addStretch()

    def _delete_one(self, item_id: str):
        self.items = [m for m in self.items if m.id != item_id]
        self.log.emit("已删除 1 个媒体,并清理 1 个本地文件")
        self._refresh_media()


# ===========================================================================
# Status bar
# ===========================================================================
class LogBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setMaximumHeight(180)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        bar = QFrame(); bar.setStyleSheet(f"background: {C['surface']};")
        bl = QHBoxLayout(bar); bl.setContentsMargins(14, 6, 14, 6)
        self.toggle = QPushButton("▾  任务历史 / 动作日志")
        self.toggle.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; color: {C['muted']};
                           font-family: "JetBrains Mono", monospace; font-size: 11px; }}
            QPushButton:hover {{ color: {C['ink']}; }}
        """)
        self.toggle.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle.clicked.connect(self._toggle)
        bl.addWidget(self.toggle); bl.addStretch()

        self.mode_label = QLabel("● MOCK API")
        self.mode_label.setStyleSheet(f"color: {C['warning']}; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;")
        bl.addWidget(self.mode_label)
        self.count_label = QLabel("0 条")
        self.count_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 11px; margin-left: 16px;")
        bl.addWidget(self.count_label)
        v.addWidget(bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        self.log_view.hide()
        v.addWidget(self.log_view)

        self.count = 0

    def _toggle(self):
        self.log_view.setVisible(not self.log_view.isVisible())
        arrow = "▾" if self.log_view.isVisible() else "▸"
        self.toggle.setText(f"{arrow}  任务历史 / 动作日志")

    def append(self, message: str):
        self.count += 1
        self.log_view.appendPlainText(f"{hhmmss()}   {message}")
        self.count_label.setText(f"{self.count} 条")

    def set_mode(self, use_mock: bool):
        if use_mock:
            self.mode_label.setText("● MOCK API")
            self.mode_label.setStyleSheet(f"color: {C['warning']}; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;")
        else:
            self.mode_label.setText("● LIVE API")
            self.mode_label.setStyleSheet(f"color: {C['online']}; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 600;")


# ===========================================================================
# Main window
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1480, 880)
        self.setMinimumSize(1200, 700)

        # Load persisted state
        acc_data = load_json(ACCOUNTS_FILE, DEFAULT_ACCOUNTS)
        self.accounts = [Account(**a) for a in acc_data]
        prompt_data = load_json(PROMPTS_FILE, DEFAULT_PROMPTS)
        self.prompts = [Prompt(**p) for p in prompt_data]

        self.fetcher = ImageFetcher(self)

        # Build UI
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.acc_panel = AccountPanel(self.accounts)
        self.workspace = WorkspacePanel(self.prompts)
        self.media = MediaPanel(self.fetcher)
        self.splitter.addWidget(self.acc_panel)
        self.splitter.addWidget(self.workspace)
        self.splitter.addWidget(self.media)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([300, 900, 380])
        root.addWidget(self.splitter, 1)

        self.log_bar = LogBar()
        root.addWidget(self.log_bar)

        # Wire signals
        self.acc_panel.account_selected.connect(self._on_account_selected)
        self.acc_panel.accounts_changed.connect(self._save_accounts)
        self.workspace.log.connect(self.log_bar.append)
        self.media.log.connect(self.log_bar.append)

        # Initial state
        if self.accounts:
            self._on_account_selected(self.accounts[0].id)
        self.log_bar.set_mode(self.media.use_mock)
        # Refresh mode label whenever it changes
        original_set_mode = self.media._set_mode
        def wrapped(use_mock):
            original_set_mode(use_mock)
            self.log_bar.set_mode(self.media.use_mock)
        self.media._set_mode = wrapped

        # Startup logs
        self.log_bar.append(f"系统启动 · 加载 {len(self.accounts)} 个账号 · WebEngine={'✓' if WEBENGINE_AVAILABLE else '✗'} · Parser={'✓' if PARSER_AVAILABLE else '✗'}")
        if not WEBENGINE_AVAILABLE:
            self.log_bar.append("提示: pip install PySide6 PySide6-Addons 以启用真实豆包页面")
        if not PARSER_AVAILABLE:
            self.log_bar.append("提示: pip install -e <doubao-nomark 路径> 以启用真实解析")

    def _on_account_selected(self, acc_id: str):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        self.workspace.set_account(acc)
        self.log_bar.append(f"切换账号 · {acc.name}")

    def _save_accounts(self):
        # Update list reference (acc_panel mutates self.accounts since list is shared)
        save_json(ACCOUNTS_FILE, [asdict(a) for a in self.acc_panel.accounts])
        self.accounts = self.acc_panel.accounts

    def closeEvent(self, e):
        self._save_accounts()
        save_json(PROMPTS_FILE, [asdict(p) for p in self.workspace.prompts])
        super().closeEvent(e)


# ===========================================================================
# Entry
# ===========================================================================
def main():
    # High-DPI is on by default in Qt6
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(build_stylesheet())

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
