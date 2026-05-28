"""
Playwright session 管理。每个账号一个独立 Chromium(launch_persistent_context),
独立 cookie / 历史 / Downloads,避免账号互相污染。

设计原则(沿用 novel_ai 项目验证过的模式):
- 用 launch_persistent_context 而不是 launch + new_context → 状态自动持久化
- 每账号一个 user_data_dir → ~/.doubao-studio/profiles/<acc_id>/chrome_data/
- channel="chrome" 优先用本机 Chrome(指纹更真实,反爬过率高)
- 显式 viewport + 模拟真人 user-agent
- 单独 downloads_path → 工具能定位下载文件
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional, Callable, Dict
from dataclasses import dataclass
import asyncio, threading, time

from .models import Account
from . import storage as ST


# Playwright 是可选依赖,未装时模块仍可 import(M2 才用到)
try:
    from playwright.sync_api import sync_playwright, BrowserContext, Page
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


@dataclass
class SessionStatus:
    account_id: str
    online: bool = False
    logged_in: bool = False
    current_url: str = ""
    error: str = ""


class AccountSession:
    """单个账号的 Chromium 会话。线程不安全:必须在专属线程内使用。"""

    def __init__(self, account: Account):
        if not HAS_PLAYWRIGHT:
            raise RuntimeError(
                "Playwright 未安装。运行: pip install playwright && playwright install chromium"
            )
        self.account = account
        self.status = SessionStatus(account_id=account.id)
        self._pw = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.downloads_dir = ST.PROFILES_DIR / account.id / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.user_data_dir = ST.PROFILES_DIR / account.id / "chrome_data"
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

    def start(self, headless: bool = False):
        """启动 Chromium。headless=False(默认)便于扫码登录。"""
        if self._ctx: return
        self._pw = sync_playwright().start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                channel="chrome",     # 本机 Chrome 优先
                headless=headless,
                viewport={"width": 1366, "height": 900},
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
                args=[
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except Exception:
            # 本机没装 Chrome → 退化到 chromium
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=headless,
                viewport={"width": 1366, "height": 900},
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
            )
        # 注册 close 回调 — 用户手关浏览器时同步 online=False
        try:
            self._ctx.on("close", lambda _ctx=None: self._on_ctx_closed())
        except Exception:
            pass
        # 第一个页面
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        # 页面关闭也记一下
        try:
            self._page.on("close", lambda _p=None: self._on_page_closed())
        except Exception:
            pass
        self.status.online = True
        self.status.error = ""

    def attach_cdp(self, cdp_url: str = "http://localhost:9222"):
        """挂载到已运行的 Chrome(用户用 --remote-debugging-port=9222 启动的)。

        用法:
          1. 关掉所有 Chrome 窗口(否则 --user-data-dir 会被锁)
          2. 终端跑:
             macOS: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
             Win:   "C:/Program Files/Google/Chrome/Application/chrome.exe" --remote-debugging-port=9222
             Linux: google-chrome --remote-debugging-port=9222
          3. 在新开的 Chrome 里登好账号
          4. 工具调本方法,通过 CDP 连过去
        """
        if self._ctx: return
        self._pw = sync_playwright().start()
        # connect_over_cdp 返回 Browser 对象,默认有一个 context
        browser = self._pw.chromium.connect_over_cdp(cdp_url)
        contexts = browser.contexts
        if not contexts:
            self._ctx = browser.new_context()
        else:
            self._ctx = contexts[0]
        # 拿第一个已有页面或新建
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        try:
            self._page.on("close", lambda _p=None: self._on_page_closed())
        except Exception:
            pass
        self._browser_attached = browser  # 保引用避免 GC
        self.status.online = True
        self.status.current_url = self._page.url if self._page else ""
        self.status.error = ""

    def _on_ctx_closed(self):
        self.status.online = False
        self._ctx = None
        self._page = None

    def _on_page_closed(self):
        # 页面没了,但 ctx 可能还活着(用户只关了 tab)。尝试取第一个 page
        try:
            if self._ctx and self._ctx.pages:
                self._page = self._ctx.pages[0]
                return
        except Exception:
            pass
        # 没救了
        self.status.online = False
        self._page = None

    def stop(self):
        try:
            if self._ctx: self._ctx.close()
            if self._pw: self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None
        self._pw = None
        self.status.online = False

    def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 30_000):
        """打开 URL。若浏览器已被手动关闭,自动重启再试一次。"""
        if not self._page or not self.status.online:
            # 已掉线 → 重启再试
            self.stop()
            self.start(headless=False)
        try:
            self._page.goto(url, wait_until=wait_until, timeout=timeout)
            self.status.current_url = url
        except Exception as e:
            err = str(e).lower()
            # 检测 closed:Page.goto/Target page/browser has been closed
            closed_signals = ("has been closed", "target closed", "target page",
                              "browser has been closed", "context was closed")
            if any(s in err for s in closed_signals):
                # 重启 + 重试一次
                self.stop()
                self.start(headless=False)
                self._page.goto(url, wait_until=wait_until, timeout=timeout)
                self.status.current_url = url
                return
            raise

    def page(self) -> Optional[Page]:
        return self._page

    def fill_clipboard_paste(self, selector: str, text: str) -> bool:
        """选择器找到 input,聚焦,然后 type 文本(慢速,模拟人手)。失败返回 False。"""
        if not self._page: return False
        try:
            el = self._page.wait_for_selector(selector, timeout=5000)
            if not el: return False
            el.click()
            self._page.keyboard.type(text, delay=10)
            return True
        except Exception as e:
            self.status.error = str(e)
            return False

    def click(self, selector: str) -> bool:
        if not self._page: return False
        try:
            self._page.click(selector, timeout=5000)
            return True
        except Exception:
            return False

    def set_input_files(self, selector: str, files) -> bool:
        """把文件注入到 file input(用于 TXT 附件上传、参考图上传)。

        files: 单个 str/Path 或列表
        """
        if not self._page: return False
        if not isinstance(files, (list, tuple)):
            files = [files]
        paths = [str(p) for p in files]
        # 多 selector 用逗号拆,挨个试
        for sel in [s.strip() for s in selector.split(',') if s.strip()]:
            try:
                # set_input_files 对 hidden input 也工作
                self._page.set_input_files(sel, paths, timeout=5000)
                return True
            except Exception:
                continue
        return False

    def upload_txt(self, text: str, file_name: str = "script.txt",
                   upload_selector: str = "", use_bom: bool = True) -> bool:
        """把文本写成 .txt 文件 + 注入到 file input。

        - use_bom=True (默认):头部加 \\uFEFF (UTF-8 BOM),给 GPT 镜像/ChatGPT 用,防中文乱码
        - use_bom=False:豆包/即梦 等国产平台,原生吃 UTF-8 无 BOM
        - 临时文件存到 downloads_dir/_uploads/
        - 调 set_input_files 注入
        """
        if not self._page: return False
        upload_root = self.downloads_dir / "_uploads"
        upload_root.mkdir(parents=True, exist_ok=True)
        target = upload_root / file_name
        try:
            prefix = "\ufeff" if use_bom else ""
            target.write_text(prefix + text, encoding="utf-8")
        except Exception:
            return False
        if not upload_selector:
            upload_selector = (
                '#upload-files, '
                'input[type="file"][multiple], '
                'input[type="file"]'
            )
        return self.set_input_files(upload_selector, [target])

    def is_logged_in(self, cookie_names: list) -> bool:
        if not self._ctx: return False
        try:
            cookies = self._ctx.cookies()
            names = {c.get("name", "") for c in cookies}
            ok = any(c in names for c in cookie_names)
            self.status.logged_in = ok
            return ok
        except Exception:
            return False


# ---- 全局会话池 ----
class SessionPool:
    """每个账号最多一个会话。"""
    def __init__(self):
        self._sessions: Dict[str, AccountSession] = {}
        self._lock = threading.RLock()

    def get_or_create(self, account: Account) -> AccountSession:
        with self._lock:
            if account.id not in self._sessions:
                self._sessions[account.id] = AccountSession(account)
            return self._sessions[account.id]

    def get(self, acc_id: str) -> Optional[AccountSession]:
        return self._sessions.get(acc_id)

    def close_all(self):
        with self._lock:
            for s in self._sessions.values():
                try: s.stop()
                except Exception: pass
            self._sessions.clear()


_pool: Optional[SessionPool] = None

def get_pool() -> SessionPool:
    global _pool
    if _pool is None:
        _pool = SessionPool()
    return _pool
