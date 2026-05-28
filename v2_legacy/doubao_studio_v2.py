"""
DoubaoStudio v2 - 多账号豆包管理 + 无水印媒体解析
基于 PySide6 (UI) + Playwright (真 Chrome 自动化) + doubao-nomark (解析)

核心架构(参考 novel_ai 项目的成功模式):
- 每个账号一个 launch_persistent_context(user_data_dir=...) → 真实 Chrome 完整隔离
- 真 cookie 状态来源 = context.cookies(),不再猜 cookie 名
- 真 DOM 抓取 = page.evaluate(SCAN_JS),反检测能力 >> QWebEngine
- SITE_PROFILES 字典适配各站点选择器,改 selector 不动逻辑
- 一键「发送到豆包」 → Playwright 自动 fill+click,抓回复+媒体
- doubao_parser 直接 import,无需起 HTTP 服务

安装:
    pip install PySide6 playwright
    python -m playwright install chromium
    # (可选)解析库:
    git clone https://github.com/ihmily/doubao-nomark
    cd doubao-nomark && pip install -e .

运行:
    python doubao_studio.py
"""
from __future__ import annotations

import sys
import os
import json
import asyncio
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Callable

from PySide6.QtCore import (
    Qt, Signal, QUrl, QObject, QThread, QSize, QTimer, QByteArray
)
from PySide6.QtGui import (
    QIcon, QColor, QFont, QPixmap, QPainter, QPen, QBrush,
    QDesktopServices, QCursor, QImage, QPolygon
)
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea, QSplitter, QFrame, QMessageBox,
    QStackedWidget, QSizePolicy, QPlainTextEdit, QMenu, QInputDialog, QDialog
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

# -------- Optional deps --------
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from doubao_parser.image import doubao_image_parse
    from doubao_parser.video import doubao_video_parse
    PARSER_AVAILABLE = True
except ImportError:
    PARSER_AVAILABLE = False
    doubao_image_parse = None
    doubao_video_parse = None


# ===========================================================================
# Paths + theme
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

# 强 signal cookie:出现其一 → 已登录
AUTH_PRIMARY = {"sessionid", "sid_guard"}
# 二级辅助 cookie(用于日志诊断)
AUTH_AUXILIARY = {
    "sessionid_ss", "sid_tt", "uid_tt", "uid_tt_ss",
    "ssid_ucp_v1", "passport_csrf_token", "passport_csrf_token_default",
    "sso_uid_tt", "n_mh",
}

# 站点选择器配置 —— 参考 novel_ai 的 SITE_PROFILES 模式
# DOM 变了改这里,不动逻辑
SITE_PROFILES = {
    "doubao.com": {
        "home_url":   "https://www.doubao.com/chat",
        # 多个 selector 用逗号分隔,Playwright locator 会逐一尝试
        "input":      'textarea[data-testid="chat_input_input"], textarea[placeholder*="发消息"], textarea',
        "send_btn":   'button[data-testid="chat_input_send_button"], button[type="submit"], button[aria-label*="发送"]',
        "response":   '[data-testid*="message"][data-testid*="assistant"], .markdown-body, .message-content',
        "stop_btn":   'button:has-text("停止生成"), button[aria-label*="停止"]',
    },
    "_default": {
        "home_url":   "about:blank",
        "input":      'textarea, [contenteditable="true"]',
        "send_btn":   'button[type="submit"]',
        "response":   '.message, .response',
        "stop_btn":   None,
    },
}

# 注入到豆包页面的扫描脚本,从 DOM 抓 <img>/<video>
# Playwright 的 evaluate 返回值会自动 JSON 序列化
PAGE_MEDIA_SCAN_JS = r"""
(() => {
  const isMedia = s => s && /doubao\.com|byteimg|bytecdn|toutiaoimg|sf[0-9]+\.|aweme|p\d+-bot/i.test(s);
  const seen = new Set();
  const out = [];
  document.querySelectorAll('img').forEach(el => {
    const src = el.currentSrc || el.src;
    if (!isMedia(src) || seen.has(src)) return;
    if ((el.naturalWidth || el.width) < 100) return;
    if ((el.naturalHeight || el.height) < 100) return;
    seen.add(src);
    out.push({type:'image', src, w: el.naturalWidth || el.width, h: el.naturalHeight || el.height});
  });
  document.querySelectorAll('video').forEach(el => {
    const src = el.currentSrc || el.src;
    if (!src || seen.has(src)) return;
    seen.add(src);
    out.push({type:'video', src, w: el.videoWidth || 0, h: el.videoHeight || 0, poster: el.poster || null});
  });
  return out;
})();
"""

DEFAULT_ACCOUNTS = [
    {"id": "acc-1", "name": "主账号 · 内容生产", "color": "#1e3a8a", "online": False, "status": "未启动"},
    {"id": "acc-2", "name": "快速通道 A",        "color": "#dc5a3a", "online": False, "status": "未启动"},
    {"id": "acc-3", "name": "快速通道 B",        "color": "#15803d", "online": False, "status": "未启动"},
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
    "success": True, "image_count": 3,
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
# Data models
# ===========================================================================
@dataclass
class Account:
    id: str
    name: str
    color: str = "#1e3a8a"
    online: bool = False        # = 真 cookie 验证后的状态
    status: str = "未启动"      # 未启动 / 启动中 / 未登录 / 已登录 / 已停止

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
    source: str = "parsed"   # "parsed" / "auto"


def load_json(path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def detect_link_type(url):
    s = (url or "").strip()
    if "doubao.com/thread/" in s: return "image"
    if "video-sharing" in s:      return "video"
    return None

def hhmmss():
    return datetime.now().strftime("%H:%M:%S")


# ===========================================================================
# ParseWorker - 在 QThread 里跑 doubao_parser (原样保留)
# ===========================================================================
class ParseWorker(QThread):
    finished_ok = Signal(dict, str)
    failed      = Signal(str)

    def __init__(self, url, link_type, use_mock, parent=None):
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
                raise RuntimeError(data.get("message", "API 返回 success=False"))
            self.finished_ok.emit(data, self.link_type)
        except Exception as e:
            self.failed.emit(str(e))


# ===========================================================================
# ImageFetcher - 缩略图异步抓取
# ===========================================================================
class ImageFetcher(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._pending: Dict[QNetworkReply, Callable] = {}
        self.nam.finished.connect(self._on_finished)

    def fetch(self, url, callback):
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 DoubaoStudio")
        reply = self.nam.get(req)
        self._pending[reply] = callback

    def _on_finished(self, reply):
        cb = self._pending.pop(reply, None)
        if not cb:
            reply.deleteLater(); return
        try:
            if reply.error() == QNetworkReply.NoError:
                data = bytes(reply.readAll())
                pm = QPixmap()
                if pm.loadFromData(data):
                    cb(pm); return
            cb(None)
        finally:
            reply.deleteLater()


# ===========================================================================
# Playwright Worker — 在自己的 QThread 里跑 asyncio + Playwright,长存
# ===========================================================================
class PlaywrightWorker(QObject):
    """
    每个账号一个 worker。在自己 QThread 里 spin 一个 asyncio loop,
    挂一个 Chromium persistent context,长存,直到主线程调 stop。
    主线程通过 submit_async 把协程丢到 worker 的 loop。
    """
    log              = Signal(str)
    status_changed   = Signal(bool, str)     # online, status_text
    url_changed      = Signal(str)
    title_changed    = Signal(str)
    page_media       = Signal(list)
    screenshot_ready = Signal(bytes)
    started          = Signal()
    stopped          = Signal()
    send_finished    = Signal(bool, str)     # ok, info

    def __init__(self, account: Account):
        super().__init__()
        self.account = account
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.context = None
        self.page = None
        self._running = False
        self._loop_ready = threading.Event()
        self._last_url = ""
        self._last_logged_in: Optional[bool] = None

    # --- Entry point: called by QThread.started ---
    def start_in_thread(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self._loop_ready.set()
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            self.log.emit(f"[Playwright] 致命错误: {e}")
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for t in pending: t.cancel()
                self.loop.run_until_complete(asyncio.sleep(0.1))
            except Exception:
                pass
            try: self.loop.close()
            except Exception: pass
            self.stopped.emit()

    async def _async_main(self):
        if not PLAYWRIGHT_AVAILABLE:
            self.log.emit("[Playwright] 未安装。pip install playwright && python -m playwright install chromium")
            self.status_changed.emit(False, "未安装")
            return

        user_data_dir = str(PROFILES_DIR / self.account.id / "chrome_data")
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)

        self.log.emit(f"[{self.account.name}] 启动 Chrome · user_data_dir={user_data_dir}")
        self.status_changed.emit(False, "启动中")

        try:
            async with async_playwright() as pw:
                self.context = await pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    viewport={"width": 1280, "height": 800},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-default-browser-check",
                        "--no-first-run",
                    ],
                )

                self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
                self.page.on("framenavigated", self._on_navigated)
                self.context.on("close", self._on_context_close)

                try:
                    await self.page.goto(SITE_PROFILES["doubao.com"]["home_url"], wait_until="domcontentloaded", timeout=30000)
                except Exception as e:
                    self.log.emit(f"[{self.account.name}] 首次加载警告: {e}")

                self.started.emit()
                self._running = True
                self.log.emit(f"[{self.account.name}] Chrome 已就绪")

                # 后台并行任务
                tasks = [
                    asyncio.create_task(self._scan_loop()),
                    asyncio.create_task(self._cookie_loop()),
                    asyncio.create_task(self._screenshot_loop()),
                ]
                try:
                    while self._running:
                        await asyncio.sleep(0.3)
                except asyncio.CancelledError:
                    pass
                finally:
                    for t in tasks: t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                try: await self.context.close()
                except Exception: pass

        except Exception as e:
            self.log.emit(f"[{self.account.name}] Chromium 启动失败: {e}")
            self.status_changed.emit(False, "启动失败")

    def _on_navigated(self, frame):
        try:
            if frame.parent_frame is None:
                url = frame.url
                if url != self._last_url:
                    self._last_url = url
                    self.url_changed.emit(url)
        except Exception:
            pass

    def _on_context_close(self):
        self.log.emit(f"[{self.account.name}] Chrome 已被用户关闭")
        self._running = False

    async def _scan_loop(self):
        while self._running:
            await asyncio.sleep(4)
            try:
                if not self.page or self.page.is_closed(): continue
                if "doubao.com" not in (self.page.url or ""): continue
                items = await self.page.evaluate(PAGE_MEDIA_SCAN_JS)
                if items:
                    self.page_media.emit(items)
            except Exception:
                pass

    async def _cookie_loop(self):
        while self._running:
            await asyncio.sleep(2)
            try:
                cookies = await self.context.cookies()
                doubao_cookies = [c for c in cookies if "doubao" in c.get("domain", "")]
                names = {c["name"] for c in doubao_cookies}
                logged_in = bool(names & AUTH_PRIMARY)
                if logged_in != self._last_logged_in:
                    self._last_logged_in = logged_in
                    if logged_in:
                        primary = names & AUTH_PRIMARY
                        self.log.emit(f"[{self.account.name}] 登录确认 · 命中 {','.join(sorted(primary))}")
                        self.status_changed.emit(True, "已登录")
                    else:
                        self.status_changed.emit(False, "未登录")
            except Exception:
                pass

    async def _screenshot_loop(self):
        while self._running:
            await asyncio.sleep(2.5)
            try:
                if not self.page or self.page.is_closed(): continue
                png = await self.page.screenshot(type="jpeg", quality=55, full_page=False)
                self.screenshot_ready.emit(png)
            except Exception:
                pass

    # ---- 主线程调用 ----
    def submit_async(self, coro_factory):
        if not self.loop or not self.loop.is_running():
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro_factory(), self.loop)
        except RuntimeError:
            return None

    def navigate(self, url):
        self.submit_async(lambda: self._safe_goto(url))

    async def _safe_goto(self, url):
        try: await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e: self.log.emit(f"[{self.account.name}] 跳转失败: {e}")

    def reload(self):
        self.submit_async(lambda: self.page.reload())

    def back(self):
        self.submit_async(lambda: self.page.go_back())

    def forward(self):
        self.submit_async(lambda: self.page.go_forward())

    def send_prompt(self, text):
        self.submit_async(lambda: self._do_send_prompt(text))

    async def _do_send_prompt(self, text):
        try:
            host = "doubao.com" if "doubao.com" in (self.page.url or "") else "_default"
            sel = SITE_PROFILES.get(host, SITE_PROFILES["_default"])
            input_el = self.page.locator(sel["input"]).first
            await input_el.wait_for(state="visible", timeout=10000)
            await input_el.click()
            await input_el.fill(text)
            await asyncio.sleep(0.3)
            try:
                send_el = self.page.locator(sel["send_btn"]).first
                await send_el.click(timeout=3000)
            except Exception:
                # fallback:按回车
                await input_el.press("Enter")
            self.send_finished.emit(True, "已发送")
            self.log.emit(f"[{self.account.name}] 提示词已注入并发送")
        except Exception as e:
            self.send_finished.emit(False, str(e))
            self.log.emit(f"[{self.account.name}] 发送失败: {e}")

    def stop(self):
        self._running = False


class PlaywrightSession(QObject):
    """每账号 worker 的 QThread 容器,把信号转发出去时带上 account_id"""
    log                 = Signal(str)
    status_changed      = Signal(str, bool, str)  # acc_id, online, text
    url_changed         = Signal(str, str)
    page_media_detected = Signal(str, list)
    screenshot_ready    = Signal(str, bytes)
    started             = Signal(str)
    stopped             = Signal(str)
    send_finished       = Signal(str, bool, str)

    def __init__(self, account: Account, parent=None):
        super().__init__(parent)
        self.account = account
        self.thread = QThread()
        self.worker = PlaywrightWorker(account)
        self.worker.moveToThread(self.thread)

        aid = account.id
        self.worker.log.connect(self.log)
        self.worker.status_changed.connect(lambda o, t: self.status_changed.emit(aid, o, t))
        self.worker.url_changed.connect(lambda u: self.url_changed.emit(aid, u))
        self.worker.page_media.connect(lambda items: self.page_media_detected.emit(aid, items))
        self.worker.screenshot_ready.connect(lambda b: self.screenshot_ready.emit(aid, b))
        self.worker.started.connect(lambda: self.started.emit(aid))
        self.worker.stopped.connect(lambda: self.stopped.emit(aid))
        self.worker.send_finished.connect(lambda ok, m: self.send_finished.emit(aid, ok, m))

        self.thread.started.connect(self.worker.start_in_thread)
        self.thread.start()

    def navigate(self, url): self.worker.navigate(url)
    def reload(self):        self.worker.reload()
    def back(self):          self.worker.back()
    def forward(self):       self.worker.forward()
    def send_prompt(self, t): self.worker.send_prompt(t)

    def cleanup(self):
        self.worker.stop()
        self.thread.quit()
        if not self.thread.wait(5000):
            self.thread.terminate()


# ===========================================================================
# Stylesheet (大部分沿用)
# ===========================================================================
def build_stylesheet():
    return f"""
    QWidget {{
        background: {C['bg']}; color: {C['ink']};
        font-family: "Inter Tight", "PingFang SC", "Microsoft YaHei UI",
                     "Segoe UI", "Noto Sans CJK SC", sans-serif;
        font-size: 13px;
    }}
    QFrame#Panel    {{ background: {C['surface']}; }}
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
        font-family: "Fraunces", "Source Han Serif SC", "Songti SC", serif;
        font-size: 23px; font-weight: 500; color: {C['ink']};
        letter-spacing: -0.3px;
    }}
    QLabel#Mono {{
        font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace;
        font-size: 10px; letter-spacing: 1px; color: {C['muted']};
    }}
    QLabel#Secondary {{ color: {C['muted']}; font-size: 11px; }}
    QLineEdit, QPlainTextEdit {{
        background: {C['surface_alt']}; border: 1px solid {C['border']};
        border-radius: 6px; padding: 6px 10px;
        color: {C['ink']}; selection-background-color: {C['accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {C['ink']}; }}
    QPushButton {{
        background: {C['surface']}; border: 1px solid {C['border']};
        border-radius: 6px; padding: 6px 12px; color: {C['ink_soft']};
    }}
    QPushButton:hover {{ background: {C['surface_alt']}; }}
    QPushButton:disabled {{ color: {C['muted']}; background: {C['surface_alt']}; }}
    QPushButton#Primary {{
        background: {C['ink']}; color: white; border: none;
        padding: 8px 14px; font-weight: 500;
    }}
    QPushButton#Primary:hover {{ background: #2a2a2a; }}
    QPushButton#Accent {{
        background: {C['accent']}; color: white; border: none;
        padding: 6px 12px; font-weight: 500;
    }}
    QPushButton#Accent:hover {{ background: #c44d30; }}
    QPushButton#Accent:disabled {{ background: #e5b8aa; color: white; }}
    QPushButton#TabActive {{
        background: {C['surface']}; border: none; padding: 4px 10px;
        font-weight: 500; color: {C['ink']}; border-radius: 4px;
    }}
    QPushButton#TabInactive {{
        background: transparent; border: none; padding: 4px 10px; color: {C['muted']};
    }}
    QPushButton#IconOnly {{
        border: none; background: transparent; padding: 4px; color: {C['muted']};
    }}
    QPushButton#IconOnly:hover {{ background: {C['surface_alt']}; border-radius: 4px; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical   {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #d4d4d4; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #a3a3a3; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: #d4d4d4; border-radius: 4px; min-width: 30px; }}
    QSplitter::handle {{ background: {C['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QPlainTextEdit#Log {{
        background: {C['bg']}; border: none;
        border-top: 1px solid {C['border_soft']};
        font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace;
        font-size: 11px; color: {C['ink_soft']}; padding: 6px 12px;
    }}
    """


# ===========================================================================
# Small widgets
# ===========================================================================
def make_avatar(color, letter, size=32):
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(color))); p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    p.setPen(QPen(QColor("white")))
    p.setFont(QFont("Inter Tight", int(size * 0.42), QFont.DemiBold))
    p.drawText(pm.rect(), Qt.AlignCenter, letter[:1] or "?")
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
# Account widgets
# ===========================================================================
class AccountCard(QFrame):
    selected         = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    launch_requested = Signal(str)

    def __init__(self, account: Account, index: int):
        super().__init__()
        self.account = account
        self.index = index
        self._is_selected = False
        self.setObjectName("Card")
        self.setCursor(QCursor(Qt.PointingHandCursor))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12); outer.setSpacing(10)

        top = QHBoxLayout(); top.setSpacing(10)
        ava_wrap = QWidget(); ava_wrap.setFixedSize(36, 36)
        ag = QGridLayout(ava_wrap); ag.setContentsMargins(0,0,0,0); ag.setSpacing(0)
        avatar = QLabel(); avatar.setPixmap(make_avatar(account.color, account.name[0], 32))
        avatar.setFixedSize(32, 32)
        ag.addWidget(avatar, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        self.dot_label = QLabel(); self.dot_label.setFixedSize(11, 11)
        ag.addWidget(self.dot_label, 0, 0, Qt.AlignBottom | Qt.AlignRight)
        self._paint_dot(account.online)
        top.addWidget(ava_wrap)

        name_box = QVBoxLayout(); name_box.setSpacing(2)
        self.name_label = QLabel(account.name)
        self.name_label.setStyleSheet(f"color: {C['ink']}; font-weight: 500; font-size: 13px;")
        self.status_label = QLabel(account.status)
        self._paint_status(account.online, account.status)
        name_box.addWidget(self.name_label)
        name_box.addWidget(self.status_label)
        top.addLayout(name_box, 1)
        outer.addLayout(top)

        outer.addWidget(Hline(soft=True))

        bottom = QHBoxLayout(); bottom.setSpacing(8)
        idx = QLabel(f"#{index + 1}")
        idx.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-family: "JetBrains Mono", monospace; font-size: 10px;
            padding: 2px 6px; border-radius: 3px;
        """)
        bottom.addWidget(idx)
        bottom.addStretch()

        launch_btn = QPushButton("▶ 启动")
        launch_btn.setObjectName("IconOnly")
        launch_btn.setStyleSheet(f"color: {C['accent']}; font-size: 11px; font-weight: 500;")
        launch_btn.clicked.connect(lambda: self.launch_requested.emit(self.account.id))
        bottom.addWidget(launch_btn)

        rename_btn = QPushButton("✎")
        rename_btn.setObjectName("IconOnly")
        rename_btn.setStyleSheet(f"color: {C['muted']}; font-size: 13px;")
        rename_btn.setToolTip("重命名")
        rename_btn.clicked.connect(lambda: self.rename_requested.emit(self.account.id))
        bottom.addWidget(rename_btn)

        del_btn = QPushButton("🗑")
        del_btn.setObjectName("IconOnly")
        del_btn.setStyleSheet(f"color: {C['muted']}; font-size: 13px;")
        del_btn.setToolTip("删账号")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.account.id))
        bottom.addWidget(del_btn)

        outer.addLayout(bottom)

    def _paint_dot(self, online):
        color = C['online'] if online else "#cbd5e1"
        self.dot_label.setStyleSheet(
            f"background: {color}; border: 2px solid {C['surface']}; border-radius: 5px;"
        )

    def _paint_status(self, online, text):
        if "启动" in text and text != "未启动": color = C['accent']
        elif text == "未启动":                  color = C['muted']
        elif online:                             color = C['online']
        else:                                    color = C['warning']
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.status_label.setText(text)

    def update_status(self, online, status_text):
        self.account.online = online
        self.account.status = status_text
        self._paint_dot(online)
        self._paint_status(online, status_text)

    def mousePressEvent(self, e):
        self.selected.emit(self.account.id)
        super().mousePressEvent(e)

    def set_selected(self, sel):
        self._is_selected = sel
        self.setObjectName("CardSelected" if sel else "Card")
        self.style().unpolish(self); self.style().polish(self)


class AccountPanel(QFrame):
    account_selected = Signal(str)
    account_launch   = Signal(str)
    accounts_changed = Signal()

    def __init__(self, accounts):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(300)
        self.accounts = accounts
        self.selected_id = accounts[0].id if accounts else None
        self.cards: Dict[str, AccountCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 0); root.setSpacing(0)

        header = QHBoxLayout()
        title = QLabel("账号管理"); title.setObjectName("H1")
        self.online_label = QLabel(f"● {sum(1 for a in accounts if a.online)} 在线")
        self.online_label.setStyleSheet(f"color: {C['online']}; font-weight: 600; font-size: 11px;")
        header.addWidget(title); header.addStretch(); header.addWidget(self.online_label)
        root.addLayout(header)

        sub = QLabel("CHROMIUM USER-DATA-DIR · 真账号隔离")
        sub.setObjectName("Mono")
        sub.setContentsMargins(0, 4, 0, 16)
        root.addWidget(sub)

        self.search = QLineEdit(); self.search.setPlaceholderText("🔍   搜索账号名称")
        self.search.textChanged.connect(self._refresh_list)
        root.addWidget(self.search)

        add_btn = QPushButton("＋  添加账号")
        add_btn.setObjectName("Primary")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.clicked.connect(self._add_account)
        root.addSpacing(10); root.addWidget(add_btn)

        list_hdr = QHBoxLayout(); list_hdr.setContentsMargins(0, 20, 0, 4)
        lh1 = QLabel("账号列表"); lh1.setObjectName("Mono")
        self.count_label = QLabel(f"{len(accounts)} 个"); self.count_label.setObjectName("Mono")
        list_hdr.addWidget(lh1); list_hdr.addStretch(); list_hdr.addWidget(self.count_label)
        root.addLayout(list_hdr)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.list_holder = QWidget()
        self.list_layout = QVBoxLayout(self.list_holder)
        self.list_layout.setContentsMargins(0, 4, 0, 16); self.list_layout.setSpacing(8)
        scroll.setWidget(self.list_holder)
        root.addWidget(scroll, 1)

        self._refresh_list()

    def _refresh_list(self):
        while self.list_layout.count():
            w = self.list_layout.takeAt(0).widget()
            if w: w.deleteLater()
        self.cards.clear()

        q = self.search.text().lower().strip()
        for i, acc in enumerate(self.accounts):
            if q and q not in acc.name.lower(): continue
            card = AccountCard(acc, i)
            card.selected.connect(self._on_select)
            card.rename_requested.connect(self._rename)
            card.delete_requested.connect(self._delete)
            card.launch_requested.connect(self.account_launch)
            if acc.id == self.selected_id: card.set_selected(True)
            self.list_layout.addWidget(card)
            self.cards[acc.id] = card
        self.list_layout.addStretch()
        self.count_label.setText(f"{len(self.accounts)} 个")
        self.online_label.setText(f"● {sum(1 for a in self.accounts if a.online)} 在线")

    def _on_select(self, acc_id):
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

    def _rename(self, acc_id):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称:", QLineEdit.Normal, acc.name)
        if ok and new_name.strip():
            acc.name = new_name.strip()
            self._refresh_list()
            self.accounts_changed.emit()

    def _delete(self, acc_id):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        ans = QMessageBox.question(self, "删除账号",
            f"删除「{acc.name}」?\n本地缓存目录 ~/.doubao-studio/profiles/{acc_id}/ 会保留(可手动清理)。",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        if self.selected_id == acc_id:
            self.selected_id = self.accounts[0].id if self.accounts else None
        self._refresh_list()
        self.accounts_changed.emit()
        if self.selected_id: self.account_selected.emit(self.selected_id)

    def set_account_status(self, acc_id, online, status_text):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        acc.online = online; acc.status = status_text
        card = self.cards.get(acc_id)
        if card: card.update_status(online, status_text)
        self.online_label.setText(f"● {sum(1 for a in self.accounts if a.online)} 在线")


# ===========================================================================
# Workspace - 不再嵌 webview,改为:状态条 + 截图预览 + 提示词 + 输入 + "发送到豆包"
# ===========================================================================
class WorkspacePanel(QFrame):
    log                  = Signal(str)
    launch_requested     = Signal(str)
    send_to_chrome       = Signal(str, str)    # acc_id, prompt_text

    def __init__(self, prompts):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.prompts = prompts
        self.current_account_id: Optional[str] = None
        self.current_account_name: str = "(未选择)"
        self.current_url: str = ""
        self.last_screenshot: Optional[QPixmap] = None

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # === 顶部:URL / 启动按钮 / 独立缓存标签 ===
        nav = QFrame(); nav.setObjectName("Panel")
        nav_l = QHBoxLayout(nav); nav_l.setContentsMargins(12, 8, 12, 8); nav_l.setSpacing(6)
        for label, action in [("◀", "back"), ("▶", "fwd"), ("⟳", "reload"), ("⌂", "home")]:
            b = QPushButton(label); b.setObjectName("IconOnly")
            b.setFixedSize(28, 28); b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, a=action: self._nav_action.emit(a) if hasattr(self, '_nav_action') else None)
            nav_l.addWidget(b)

        self.url_label = QLabel("等待启动 Chromium…")
        self.url_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        nav_l.addWidget(self.url_label, 1)

        self.iso_tag = QLabel("独立缓存账号池 (persistent_context)")
        self.iso_tag.setStyleSheet(f"""
            background: {C['accent_soft']}; color: {C['accent']};
            padding: 4px 12px; border-radius: 12px;
            font-size: 11px; font-weight: 500;
        """)
        nav_l.addWidget(self.iso_tag)

        self.launch_btn = QPushButton("🚀 启动浏览器")
        self.launch_btn.setObjectName("Primary")
        self.launch_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.launch_btn.clicked.connect(self._on_launch_click)
        nav_l.addWidget(self.launch_btn)

        root.addWidget(nav); root.addWidget(Hline())

        # === 中部:截图预览 ===
        self.preview_holder = QFrame(); self.preview_holder.setObjectName("PanelAlt")
        ph = QVBoxLayout(self.preview_holder); ph.setContentsMargins(20, 14, 20, 8); ph.setSpacing(8)

        meta_row = QHBoxLayout()
        self.account_label = QLabel("当前账号:(未选择)")
        self.account_label.setStyleSheet(f"color: {C['ink']}; font-weight: 500;")
        meta_row.addWidget(self.account_label)
        meta_row.addStretch()
        self.preview_meta = QLabel("快照间隔 2.5s · 实际操作请在 Chrome 窗口里")
        self.preview_meta.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        meta_row.addWidget(self.preview_meta)
        ph.addLayout(meta_row)

        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(260)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(f"""
            background: {C['surface']};
            border: 1px solid {C['border_soft']};
            border-radius: 8px;
            color: {C['muted']};
        """)
        self._set_preview_text("启动 Chromium 后此处会显示页面截图")
        ph.addWidget(self.preview_label, 1)

        root.addWidget(self.preview_holder, 1)

        # === 底部:提示词 + 输入 + 发送 ===
        bottom_wrap = QFrame(); bottom_wrap.setObjectName("PanelAlt")
        bw_l = QVBoxLayout(bottom_wrap)
        bw_l.setContentsMargins(20, 4, 20, 16); bw_l.setSpacing(0)

        self.input_card = QFrame(); self.input_card.setObjectName("Card")
        ic_l = QVBoxLayout(self.input_card); ic_l.setContentsMargins(0, 0, 0, 0); ic_l.setSpacing(0)

        # 提示词 strip
        self.prompt_bar = QFrame()
        pb_l = QVBoxLayout(self.prompt_bar)
        pb_l.setContentsMargins(12, 10, 12, 8); pb_l.setSpacing(8)
        prompt_row = QHBoxLayout(); prompt_row.setSpacing(6)
        prompt_label = QLabel("✦ 提示词")
        prompt_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px;")
        prompt_row.addWidget(prompt_label)
        prompt_row.addWidget(Vline())
        prompt_row.addSpacing(4)

        self.prompt_scroll = QScrollArea()
        self.prompt_scroll.setWidgetResizable(True); self.prompt_scroll.setFixedHeight(32)
        self.prompt_scroll.setFrameShape(QFrame.NoFrame)
        self.prompt_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.prompt_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.prompt_holder = QWidget()
        self.prompt_holder_l = QHBoxLayout(self.prompt_holder)
        self.prompt_holder_l.setContentsMargins(0,0,0,0); self.prompt_holder_l.setSpacing(6)
        self.prompt_scroll.setWidget(self.prompt_holder)
        prompt_row.addWidget(self.prompt_scroll, 1)
        pb_l.addLayout(prompt_row)

        # editor row
        self.editor_row = QHBoxLayout(); self.editor_row.setSpacing(6)
        self.editor_widget = QFrame(); self.editor_widget.setLayout(self.editor_row)
        self.editor_title = QLineEdit(); self.editor_title.setPlaceholderText("标题"); self.editor_title.setFixedWidth(110)
        self.editor_content = QLineEdit(); self.editor_content.setPlaceholderText("提示词内容")
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

        # 输入框
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText("输入提示词,点右下「发送到豆包」 → 自动在 Chrome 中填入并发送")
        self.chat_input.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {C['surface']}; border: none;
                padding: 10px 14px; font-size: 13px; color: {C['ink']};
            }}
        """)
        self.chat_input.setFixedHeight(72)
        ic_l.addWidget(self.chat_input)

        # action row
        action_row = QHBoxLayout()
        action_row.setContentsMargins(10, 6, 10, 10); action_row.setSpacing(6)
        action_row.addStretch()

        self.send_btn = QPushButton("▶  发送到豆包")
        self.send_btn.setObjectName("Accent")
        self.send_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.send_btn.clicked.connect(self._on_send_click)
        self.send_btn.setEnabled(False)
        action_row.addWidget(self.send_btn)
        ic_l.addLayout(action_row)

        bw_l.addWidget(self.input_card)
        root.addWidget(bottom_wrap)

        self._refresh_prompts()
        self._refresh_account_meta()

    # --- 截图预览 ---
    def _set_preview_text(self, text):
        self.preview_label.setText(text)
        self.preview_label.setPixmap(QPixmap())

    def update_screenshot(self, acc_id, png_bytes):
        if acc_id != self.current_account_id: return
        pm = QPixmap()
        if pm.loadFromData(png_bytes):
            self.last_screenshot = pm
            self._render_preview()

    def _render_preview(self):
        if not self.last_screenshot or self.last_screenshot.isNull(): return
        target = self.preview_label.size()
        scaled = self.last_screenshot.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render_preview()

    # --- 账号 / URL ---
    def set_current_account(self, account: Account):
        self.current_account_id = account.id
        self.current_account_name = account.name
        self.last_screenshot = None
        self._set_preview_text(f"账号「{account.name}」 - 点右上「🚀 启动浏览器」开启 Chrome")
        self._refresh_account_meta()

    def update_account_status(self, acc_id, online, status_text):
        if acc_id == self.current_account_id:
            self._refresh_account_meta(status_override=status_text, online=online)
        if online and acc_id == self.current_account_id:
            self.send_btn.setEnabled(True)

    def update_url(self, acc_id, url):
        if acc_id == self.current_account_id:
            self.current_url = url
            self.url_label.setText(url[:90] + ("…" if len(url) > 90 else ""))

    def on_session_started(self, acc_id):
        if acc_id == self.current_account_id:
            self.launch_btn.setText("● 已启动")
            self.launch_btn.setEnabled(False)
            self.send_btn.setEnabled(True)

    def on_session_stopped(self, acc_id):
        if acc_id == self.current_account_id:
            self.launch_btn.setText("🚀 启动浏览器")
            self.launch_btn.setEnabled(True)
            self.send_btn.setEnabled(False)
            self._set_preview_text("Chromium 已停止")

    def _refresh_account_meta(self, status_override=None, online=None):
        text = f"当前账号:{self.current_account_name}"
        if status_override:
            color = C['online'] if online else (C['warning'] if online is False else C['muted'])
            text += f"  ·  {status_override}"
            self.account_label.setStyleSheet(f"color: {color}; font-weight: 500;")
        else:
            self.account_label.setStyleSheet(f"color: {C['ink']}; font-weight: 500;")
        self.account_label.setText(text)

    def _on_launch_click(self):
        if not self.current_account_id:
            QMessageBox.information(self, "提示", "请先在左侧选中一个账号"); return
        self.launch_btn.setText("启动中…"); self.launch_btn.setEnabled(False)
        self.launch_requested.emit(self.current_account_id)

    def _on_send_click(self):
        text = self.chat_input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请输入要发送的提示词"); return
        if not self.current_account_id:
            return
        self.send_to_chrome.emit(self.current_account_id, text)
        self.chat_input.clear()

    # --- prompts ---
    def _refresh_prompts(self):
        while self.prompt_holder_l.count():
            w = self.prompt_holder_l.takeAt(0).widget()
            if w: w.deleteLater()
        for p in self.prompts:
            btn = QPushButton(p.title)
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setToolTip(p.content)
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid {C['border']}; background: {C['surface']};
                    border-radius: 12px; padding: 4px 10px;
                    font-size: 11px; color: {C['ink_soft']};
                }}
                QPushButton:hover {{ background: {C['surface_alt']}; }}
            """)
            btn.clicked.connect(lambda _, pp=p: self._apply_prompt(pp))
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, pid=p.id: self._prompt_menu(pid, pos))
            self.prompt_holder_l.addWidget(btn)
        add_btn = QPushButton("＋ 新增")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.setStyleSheet(f"""
            QPushButton {{
                border: 1px dashed {C['border']}; background: transparent;
                border-radius: 12px; padding: 4px 10px;
                font-size: 11px; color: {C['muted']};
            }}
            QPushButton:hover {{ background: {C['surface_alt']}; }}
        """)
        add_btn.clicked.connect(self._show_editor)
        self.prompt_holder_l.addWidget(add_btn)
        self.prompt_holder_l.addStretch()

    def _apply_prompt(self, p):
        self.chat_input.setPlainText(p.content)
        self.chat_input.setFocus()
        cur = self.chat_input.textCursor(); cur.movePosition(cur.End)
        self.chat_input.setTextCursor(cur)
        self.log.emit(f"应用提示词 · {p.title}")

    def _show_editor(self): self.editor_widget.show(); self.editor_title.setFocus()
    def _hide_editor(self): self.editor_widget.hide(); self.editor_title.clear(); self.editor_content.clear()
    def _save_prompt(self):
        title = self.editor_title.text().strip(); content = self.editor_content.text().strip()
        if not title or not content: return
        self.prompts.append(Prompt(id=f"p-{int(time.time()*1000)}", title=title, content=content))
        save_json(PROMPTS_FILE, [asdict(p) for p in self.prompts])
        self._hide_editor(); self._refresh_prompts()
        self.log.emit(f"新增提示词 · {title}")
    def _prompt_menu(self, pid, pos):
        m = QMenu(self); del_act = m.addAction("删除")
        if m.exec(QCursor.pos()) == del_act:
            self.prompts = [p for p in self.prompts if p.id != pid]
            save_json(PROMPTS_FILE, [asdict(p) for p in self.prompts])
            self._refresh_prompts()
            self.log.emit("删除提示词")


# ===========================================================================
# MediaCard / MediaPanel - 沿用之前 (含 source 标签 + auto_parse + add_detected_media)
# ===========================================================================
class MediaCard(QFrame):
    delete_requested = Signal(str)

    def __init__(self, item: MediaItem, fetcher: ImageFetcher):
        super().__init__()
        self.item = item
        self.setObjectName("Card")
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        self.thumb = QLabel()
        self.thumb.setFixedHeight(170)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background: #ececec; border-top-left-radius: 8px; border-top-right-radius: 8px;")
        self.thumb.setText("加载中…")
        v.addWidget(self.thumb)

        f = QFrame(); fl = QHBoxLayout(f); fl.setContentsMargins(10, 8, 8, 8); fl.setSpacing(6)
        if item.source == "auto":
            tag = QLabel("页面"); tag.setStyleSheet(f"""
                background: {C['surface_alt']}; color: {C['muted']};
                font-size: 9.5px; padding: 1px 5px; border-radius: 3px;
                font-family: "JetBrains Mono", monospace;
            """)
        else:
            tag = QLabel("无水印"); tag.setStyleSheet(f"""
                background: {C['accent_soft']}; color: {C['accent']};
                font-size: 9.5px; padding: 1px 5px; border-radius: 3px; font-weight: 500;
            """)
        fl.addWidget(tag)

        label = QLabel(f"{datetime.fromtimestamp(item.added_at).strftime('%H:%M:%S')} · {item.id[-8:]}")
        label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        fl.addWidget(label, 1)
        for emoji, tip, fn in [
            ("⬇", "在浏览器打开下载", self._download),
            ("⧉", "复制链接", self._copy_url),
            ("↗", "新窗口打开", self._external),
            ("✕", "删除", lambda: self.delete_requested.emit(item.id)),
        ]:
            b = QPushButton(emoji); b.setObjectName("IconOnly"); b.setFixedSize(24, 24)
            b.setToolTip(tip); b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(fn); fl.addWidget(b)
        v.addWidget(f)

        thumb_url = item.poster if item.type == "video" else item.url
        fetcher.fetch(thumb_url, self._set_thumb)

    def _set_thumb(self, pm):
        if pm is None or pm.isNull():
            self.thumb.setText("⚠ 无预览")
            self.thumb.setStyleSheet(f"background: #ececec; color: {C['muted']}; font-size: 11px;")
            return
        scaled = pm.scaled(self.thumb.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - self.thumb.width()) // 2)
        y = max(0, (scaled.height() - self.thumb.height()) // 2)
        scaled = scaled.copy(x, y, self.thumb.width(), self.thumb.height())
        if self.item.type == "video":
            p = QPainter(scaled); p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(scaled.rect(), QColor(0, 0, 0, 60))
            cx, cy = scaled.width() // 2, scaled.height() // 2
            p.setBrush(QBrush(QColor(255, 255, 255, 230))); p.setPen(Qt.NoPen)
            p.drawEllipse(cx - 22, cy - 22, 44, 44)
            p.setBrush(QBrush(QColor(C['ink']))); p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygon([QPoint(cx - 6, cy - 9), QPoint(cx + 10, cy), QPoint(cx - 6, cy + 9)]))
            p.end()
        tag = f"{self.item.width}×{self.item.height}"
        if self.item.definition: tag += f" · {self.item.definition}"
        p = QPainter(scaled); p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("JetBrains Mono", 8))
        fm = p.fontMetrics(); tw = fm.horizontalAdvance(tag) + 12; th = fm.height() + 4
        p.setBrush(QBrush(QColor(0, 0, 0, 180))); p.setPen(Qt.NoPen)
        p.drawRoundedRect(scaled.width() - tw - 8, 8, tw, th, 3, 3)
        p.setPen(QPen(QColor("white"))); p.drawText(scaled.width() - tw - 2, 8 + th - 5, tag)
        p.end()
        self.thumb.setPixmap(scaled)

    def _download(self): QDesktopServices.openUrl(QUrl(self.item.url))
    def _copy_url(self): QApplication.clipboard().setText(self.item.url)
    def _external(self): QDesktopServices.openUrl(QUrl(self.item.url))


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

        root = QVBoxLayout(self); root.setContentsMargins(20, 20, 20, 0); root.setSpacing(0)

        hdr = QHBoxLayout()
        title_box = QVBoxLayout(); title_box.setSpacing(2)
        title = QLabel("媒体列表"); title.setObjectName("H1")
        sub = QLabel("NO-WATERMARK · 图片 / 视频"); sub.setObjectName("Mono")
        title_box.addWidget(title); title_box.addWidget(sub)
        hdr.addLayout(title_box); hdr.addStretch()
        self.cfg_btn = QPushButton("⚙"); self.cfg_btn.setObjectName("IconOnly")
        self.cfg_btn.setFixedSize(28, 28); self.cfg_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.cfg_btn.clicked.connect(self._toggle_config)
        hdr.addWidget(self.cfg_btn)
        root.addLayout(hdr); root.addSpacing(12)

        tabs_wrap = QFrame()
        tabs_wrap.setStyleSheet(f"background: {C['surface_alt']}; border-radius: 6px; padding: 2px;")
        tw_l = QHBoxLayout(tabs_wrap); tw_l.setContentsMargins(2,2,2,2); tw_l.setSpacing(0)
        self.tab_buttons = {}
        for key, lbl in [("all", "全部"), ("image", "图片"), ("video", "视频")]:
            b = QPushButton(lbl)
            b.setObjectName("TabActive" if key == "all" else "TabInactive")
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, k=key: self._set_filter(k))
            tw_l.addWidget(b); self.tab_buttons[key] = b
        tabs_row = QHBoxLayout(); tabs_row.addWidget(tabs_wrap); tabs_row.addStretch()
        root.addLayout(tabs_row); root.addSpacing(14)

        parse_card = QFrame(); parse_card.setObjectName("Card")
        parse_card.setStyleSheet(f"QFrame#Card {{ background: {C['surface_alt']}; }}")
        pc_l = QVBoxLayout(parse_card); pc_l.setContentsMargins(0,0,0,0); pc_l.setSpacing(0)

        pc_hdr = QHBoxLayout(); pc_hdr.setContentsMargins(12, 8, 12, 8)
        pc_hdr_l = QLabel("🔗  PARSE LINK"); pc_hdr_l.setObjectName("Mono")
        self.type_tag = QLabel(""); self.type_tag.hide()
        pc_hdr.addWidget(pc_hdr_l); pc_hdr.addStretch(); pc_hdr.addWidget(self.type_tag)
        pc_l.addLayout(pc_hdr); pc_l.addWidget(Hline(soft=True))

        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "粘贴豆包分享链接\n"
            "https://www.doubao.com/thread/...\n"
            "https://www.doubao.com/video-sharing?share_id=..."
        )
        self.url_input.setFixedHeight(70)
        self.url_input.setStyleSheet(f"""
            QPlainTextEdit {{ background: transparent; border: none; padding: 8px 12px;
                font-family: "JetBrains Mono", monospace; font-size: 11px; color: {C['ink']}; }}
        """)
        self.url_input.textChanged.connect(self._on_url_changed)
        pc_l.addWidget(self.url_input); pc_l.addWidget(Hline(soft=True))

        act_row = QHBoxLayout(); act_row.setContentsMargins(10, 6, 10, 8); act_row.setSpacing(6)
        self.status_label = QLabel("就绪 · 自动识别链接类型")
        self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        act_row.addWidget(self.status_label, 1)
        self.parse_btn = QPushButton("✂  提取无水印")
        self.parse_btn.setObjectName("Accent"); self.parse_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.parse_btn.setEnabled(False); self.parse_btn.clicked.connect(self._do_parse)
        act_row.addWidget(self.parse_btn)
        pc_l.addLayout(act_row)
        root.addWidget(parse_card)

        sample_row = QHBoxLayout(); sample_row.setContentsMargins(0, 6, 0, 0)
        sample_lbl = QLabel("示例:"); sample_lbl.setObjectName("Mono")
        sample_row.addWidget(sample_lbl)
        for name, url in [
            ("图片链接", "https://www.doubao.com/thread/c1234567890"),
            ("视频链接", "https://www.doubao.com/video-sharing?share_id=abc&video_id=v1"),
        ]:
            b = QPushButton(name)
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: none; color: {C['muted']};
                    font-size: 10px; text-decoration: underline; padding: 0 6px; }}
                QPushButton:hover {{ color: {C['ink']}; }}
            """)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.clicked.connect(lambda _, u=url: self.url_input.setPlainText(u))
            sample_row.addWidget(b)
        sample_row.addStretch()
        root.addLayout(sample_row)

        self.config_card = self._build_config_card()
        self.config_card.hide()
        root.addWidget(self.config_card)

        self.media_scroll = QScrollArea(); self.media_scroll.setWidgetResizable(True); self.media_scroll.setFrameShape(QFrame.NoFrame)
        self.media_holder = QWidget()
        self.media_layout = QVBoxLayout(self.media_holder)
        self.media_layout.setContentsMargins(0, 14, 0, 14); self.media_layout.setSpacing(10)
        self.media_scroll.setWidget(self.media_holder)
        root.addWidget(self.media_scroll, 1)

        self._refresh_media()

    def _build_config_card(self):
        card = QFrame(); card.setObjectName("Card")
        card.setStyleSheet(f"QFrame#Card {{ background: {C['surface_alt']}; }}")
        cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 12); cl.setSpacing(8)
        hdr = QLabel("API CONFIG · DOUBAO-NOMARK"); hdr.setObjectName("Mono"); cl.addWidget(hdr)
        toggle_wrap = QFrame()
        toggle_wrap.setStyleSheet(f"background: {C['surface']}; border: 1px solid {C['border_soft']}; border-radius: 6px;")
        tw_l = QHBoxLayout(toggle_wrap); tw_l.setContentsMargins(2,2,2,2); tw_l.setSpacing(0)
        self.mock_btn = QPushButton("⚗  Mock 数据"); self.real_btn = QPushButton("🔌  真实库")
        for b in (self.mock_btn, self.real_btn):
            b.setCursor(QCursor(Qt.PointingHandCursor)); tw_l.addWidget(b)
        self.mock_btn.clicked.connect(lambda: self._set_mode(True))
        self.real_btn.clicked.connect(lambda: self._set_mode(False))
        cl.addWidget(toggle_wrap)
        self.cfg_desc = QLabel(""); self.cfg_desc.setWordWrap(True)
        self.cfg_desc.setStyleSheet(f"color: {C['muted']}; font-size: 10.5px; line-height: 1.6;")
        cl.addWidget(self.cfg_desc)
        self._update_mode_buttons()
        return card

    def _toggle_config(self): self.config_card.setVisible(not self.config_card.isVisible())

    def _set_mode(self, use_mock):
        if not use_mock and not PARSER_AVAILABLE:
            QMessageBox.warning(self, "缺少 doubao-nomark",
                "未检测到 doubao_parser 模块。请先安装:\n\n"
                "git clone https://github.com/ihmily/doubao-nomark\n"
                "cd doubao-nomark && pip install -e .\n\n继续使用 Mock 模式。")
            return
        self.use_mock = use_mock
        self._update_mode_buttons()
        self.log.emit(f"切换 API 模式 · {'MOCK' if use_mock else 'LIVE'}")

    def _update_mode_buttons(self):
        for b, active in [(self.mock_btn, self.use_mock), (self.real_btn, not self.use_mock)]:
            b.setStyleSheet(f"""
                QPushButton {{ background: {C['ink'] if active else 'transparent'};
                    color: {'white' if active else C['muted']};
                    border: none; border-radius: 4px; padding: 6px 10px;
                    font-size: 11px; font-weight: 500; }}
            """)
        if self.use_mock:
            self.cfg_desc.setText("使用内置 mock 数据,无需 doubao-nomark 即可演示。")
        else:
            self.cfg_desc.setText("直接 import doubao_parser 调用。"
                                  f"\n模块状态:{'✓ 已加载' if PARSER_AVAILABLE else '✗ 未安装'}")

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
            self.type_tag.hide(); self.parse_btn.setEnabled(False)

    def _do_parse(self):
        url = self.url_input.toPlainText().strip()
        link_type = detect_link_type(url)
        if not link_type: return
        self.parse_btn.setEnabled(False)
        self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        self.status_label.setText("正在调用解析…")
        self.log.emit(f"开始解析 {'图片' if link_type=='image' else '视频'} · {'MOCK' if self.use_mock else 'LIVE'}")
        self.worker = ParseWorker(url, link_type, self.use_mock)
        self.worker.finished_ok.connect(self._on_parse_ok)
        self.worker.failed.connect(self._on_parse_fail)
        self.worker.start()

    def _on_parse_ok(self, data, link_type):
        now = time.time()
        if link_type == "image":
            new_items = [MediaItem(
                id=f"img-{int(now*1000)}-{i}", type="image",
                url=img["url"], width=img["width"], height=img["height"],
                source_url=self.url_input.toPlainText().strip(), added_at=now,
            ) for i, img in enumerate(data.get("images", []))]
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
        self.url_input.clear(); self.parse_btn.setEnabled(False)
        QTimer.singleShot(2200, lambda: (
            self.status_label.setText("就绪 · 自动识别链接类型"),
            self.status_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        ))
        self._refresh_media()

    def _on_parse_fail(self, err):
        self.log.emit(f"解析失败 · {err}")
        self.status_label.setStyleSheet(f"color: {C['danger']}; font-family: 'JetBrains Mono', monospace; font-size: 10px;")
        self.status_label.setText(f"失败 · {err[:60]}")
        self.parse_btn.setEnabled(True)

    def _set_filter(self, key):
        self.filter = key
        for k, b in self.tab_buttons.items():
            b.setObjectName("TabActive" if k == key else "TabInactive")
            b.style().unpolish(b); b.style().polish(b)
        self._refresh_media()

    def _refresh_media(self):
        while self.media_layout.count():
            w = self.media_layout.takeAt(0).widget()
            if w: w.deleteLater()
        filtered = self.items if self.filter == "all" else [m for m in self.items if m.type == self.filter]
        if not filtered:
            empty = QFrame()
            el = QVBoxLayout(empty); el.setContentsMargins(0, 40, 0, 40); el.setAlignment(Qt.AlignCenter)
            icon = QLabel("📭"); icon.setStyleSheet("font-size: 28px;"); icon.setAlignment(Qt.AlignCenter)
            t = QLabel("暂无媒体"); t.setStyleSheet(f"color: {C['ink_soft']}; font-weight: 500;"); t.setAlignment(Qt.AlignCenter)
            tip = QLabel("浏览豆包页面会自动识别;\n粘贴分享链接可提取无水印")
            tip.setStyleSheet(f"color: {C['muted']}; font-size: 11px;"); tip.setAlignment(Qt.AlignCenter); tip.setWordWrap(True)
            el.addWidget(icon); el.addWidget(t); el.addWidget(tip)
            self.media_layout.addWidget(empty); self.media_layout.addStretch()
            return
        for m in filtered:
            card = MediaCard(m, self.fetcher)
            card.delete_requested.connect(self._delete_one)
            self.media_layout.addWidget(card)
        self.media_layout.addStretch()

    def _delete_one(self, item_id):
        self.items = [m for m in self.items if m.id != item_id]
        self.log.emit("已删除 1 个媒体,并清理 1 个本地文件")
        self._refresh_media()

    def auto_parse(self, url):
        if self.worker and self.worker.isRunning():
            self.log.emit("自动解析跳过 · 已有任务"); return
        self.url_input.setPlainText(url); self._on_url_changed()
        if self.parse_btn.isEnabled(): self._do_parse()

    def add_detected_media(self, account_id, items):
        if not items: return
        existing = {m.url for m in self.items}
        now = time.time()
        new_items = []
        for raw in items:
            src = raw.get("src")
            if not src or src in existing: continue
            mtype = raw.get("type", "image")
            new_items.append(MediaItem(
                id=f"{mtype[:3]}-auto-{int(now*1000)}-{len(new_items)}",
                type=mtype, url=src,
                width=int(raw.get("w") or 0), height=int(raw.get("h") or 0),
                source_url=f"[页面] {account_id}", added_at=now,
                poster=raw.get("poster"), source="auto",
            ))
        if not new_items: return
        self.items = new_items + self.items
        self.log.emit(f"页面媒体识别 · 新增 {len(new_items)} 项")
        self._refresh_media()


# ===========================================================================
# LogBar
# ===========================================================================
class LogBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setMaximumHeight(200)
        v = QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
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
        self.engine_label = QLabel(self._engine_text())
        self.engine_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 11px; margin-right: 16px;")
        bl.addWidget(self.engine_label)
        self.count_label = QLabel("0 条")
        self.count_label.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        bl.addWidget(self.count_label)
        v.addWidget(bar)
        self.log_view = QPlainTextEdit(); self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(140); self.log_view.hide()
        v.addWidget(self.log_view)
        self.count = 0

    def _engine_text(self):
        pw = "✓" if PLAYWRIGHT_AVAILABLE else "✗"
        ps = "✓" if PARSER_AVAILABLE else "✗"
        return f"Playwright {pw}    doubao-nomark {ps}"

    def _toggle(self):
        self.log_view.setVisible(not self.log_view.isVisible())
        self.toggle.setText(("▾" if self.log_view.isVisible() else "▸") + "  任务历史 / 动作日志")

    def append(self, message):
        self.count += 1
        self.log_view.appendPlainText(f"{hhmmss()}   {message}")
        self.count_label.setText(f"{self.count} 条")


# ===========================================================================
# MainWindow
# ===========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1480, 880)
        self.setMinimumSize(1200, 700)

        acc_data = load_json(ACCOUNTS_FILE, DEFAULT_ACCOUNTS)
        self.accounts = [Account(**a) for a in acc_data]
        # 启动时强制重置 online (上次结束的状态不可信)
        for a in self.accounts:
            a.online = False
            if a.status not in ("未启动",): a.status = "未启动"

        prompt_data = load_json(PROMPTS_FILE, DEFAULT_PROMPTS)
        self.prompts = [Prompt(**p) for p in prompt_data]

        self.fetcher = ImageFetcher(self)
        self.sessions: Dict[str, PlaywrightSession] = {}

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

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

        # --- Wiring ---
        self.acc_panel.account_selected.connect(self._on_account_selected)
        self.acc_panel.account_launch.connect(self._launch_session)
        self.acc_panel.accounts_changed.connect(self._save_accounts)

        self.workspace.log.connect(self.log_bar.append)
        self.workspace.launch_requested.connect(self._launch_session)
        self.workspace.send_to_chrome.connect(self._send_to_chrome)

        self.media.log.connect(self.log_bar.append)

        if self.accounts:
            self._on_account_selected(self.accounts[0].id)

        self.log_bar.append(f"系统启动 · 加载 {len(self.accounts)} 个账号 · Playwright={'✓' if PLAYWRIGHT_AVAILABLE else '✗'} · Parser={'✓' if PARSER_AVAILABLE else '✗'}")
        if not PLAYWRIGHT_AVAILABLE:
            self.log_bar.append("提示: pip install playwright && python -m playwright install chromium")
        if not PARSER_AVAILABLE:
            self.log_bar.append("提示: pip install -e <doubao-nomark 路径>")

    def _on_account_selected(self, acc_id):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        self.workspace.set_current_account(acc)
        self.log_bar.append(f"切换账号 · {acc.name}")
        # 如果该账号 session 已经在运行,重连预览
        if acc_id in self.sessions:
            self.workspace.on_session_started(acc_id)
            self.workspace.update_account_status(acc_id, acc.online, acc.status)

    def _launch_session(self, acc_id):
        if acc_id in self.sessions:
            self.log_bar.append(f"账号 {acc_id} session 已存在,跳过启动"); return
        if not PLAYWRIGHT_AVAILABLE:
            QMessageBox.critical(self, "Playwright 未安装",
                "请先安装:\n\npip install playwright\npython -m playwright install chromium")
            return
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return

        self.log_bar.append(f"启动 Playwright session · {acc.name}")
        session = PlaywrightSession(acc, parent=self)
        session.log.connect(self.log_bar.append)
        session.status_changed.connect(self._on_session_status)
        session.url_changed.connect(self._on_session_url)
        session.page_media_detected.connect(self.media.add_detected_media)
        session.screenshot_ready.connect(self.workspace.update_screenshot)
        session.started.connect(self.workspace.on_session_started)
        session.stopped.connect(self._on_session_stopped)
        self.sessions[acc_id] = session

        # 立即把账号状态改成"启动中"
        self.acc_panel.set_account_status(acc_id, False, "启动中")
        self.workspace.update_account_status(acc_id, False, "启动中")

    def _on_session_status(self, acc_id, online, text):
        self.acc_panel.set_account_status(acc_id, online, text)
        self.workspace.update_account_status(acc_id, online, text)
        self._save_accounts()

    def _on_session_url(self, acc_id, url):
        self.workspace.update_url(acc_id, url)
        # 命中分享链接自动解析
        if detect_link_type(url):
            self.log_bar.append(f"侦测到分享链接 · 自动调用 doubao-nomark")
            self.media.auto_parse(url)

    def _on_session_stopped(self, acc_id):
        self.sessions.pop(acc_id, None)
        self.acc_panel.set_account_status(acc_id, False, "已停止")
        self.workspace.on_session_stopped(acc_id)

    def _send_to_chrome(self, acc_id, text):
        sess = self.sessions.get(acc_id)
        if not sess:
            QMessageBox.information(self, "未启动", "请先启动该账号的浏览器"); return
        sess.send_prompt(text)
        self.log_bar.append(f"已下发提示词到 {acc_id} · {len(text)} 字符")

    def _save_accounts(self):
        save_json(ACCOUNTS_FILE, [asdict(a) for a in self.acc_panel.accounts])
        self.accounts = self.acc_panel.accounts

    def closeEvent(self, e):
        self._save_accounts()
        save_json(PROMPTS_FILE, [asdict(p) for p in self.workspace.prompts])
        for sess in list(self.sessions.values()):
            try: sess.cleanup()
            except Exception: pass
        super().closeEvent(e)


# ===========================================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(build_stylesheet())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
