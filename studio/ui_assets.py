"""
右栏:制作台
- 顶部: Backend 配额面板(分两组:图片后端 + 视频后端)
- 中部: 任务队列(M2 占位)
- 底部: 已生成素材库
"""
from __future__ import annotations
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QInputDialog, QMessageBox, QFileDialog
)

from .theme import C, PALETTE
from .widgets import Hline, make_avatar, ThumbLabel
from .models import Account, GenerationBackend, BACKEND_IMAGE, BACKEND_VIDEO
from . import storage as ST


class AssetsPanel(QFrame):
    """右栏总容器。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(360)
        self.current_pid: Optional[str] = None

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Header
        h = QFrame()
        hl = QVBoxLayout(h); hl.setContentsMargins(20, 18, 20, 12); hl.setSpacing(2)
        t = QLabel("制作台"); t.setObjectName("H1")
        s = QLabel("BACKENDS · QUEUE · ASSETS"); s.setObjectName("Mono")
        hl.addWidget(t); hl.addWidget(s)
        root.addWidget(h); root.addWidget(Hline())

        # 1. 后端配额面板(可滚动,内容多)
        self.backend_panel = BackendPanel()
        self.backend_panel.log.connect(self.log)
        backend_scroll = QScrollArea()
        backend_scroll.setWidgetResizable(True)
        backend_scroll.setFrameShape(QFrame.NoFrame)
        backend_scroll.setWidget(self.backend_panel)
        backend_scroll.setMaximumHeight(360)
        root.addWidget(backend_scroll)

        # 2. 任务队列(真实)
        root.addWidget(Hline(soft=True))
        self.queue_panel = QueuePanel()
        self.queue_panel.log.connect(self.log)
        root.addWidget(self.queue_panel)

        # 3. 素材库
        root.addWidget(Hline(soft=True))
        ah = QFrame()
        ahl = QHBoxLayout(ah); ahl.setContentsMargins(20, 12, 20, 8)
        aht = QLabel("素材库")
        aht.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; "
                          f"font-size: 10px; letter-spacing: 1px;")
        ahl.addWidget(aht); ahl.addStretch()
        imp = QPushButton("⬇ 导入"); imp.setObjectName("IconOnly")
        imp.setStyleSheet(f"color: {C['accent']}; font-size: 11px;")
        imp.setToolTip("把外部生成的图/视频导入素材库")
        imp.clicked.connect(self._on_import)
        ahl.addWidget(imp)
        root.addWidget(ah)

        self.assets_scroll = QScrollArea()
        self.assets_scroll.setWidgetResizable(True)
        self.assets_scroll.setFrameShape(QFrame.NoFrame)
        self.assets_holder = QWidget()
        self.assets_layout = QVBoxLayout(self.assets_holder)
        self.assets_layout.setContentsMargins(12, 4, 12, 12); self.assets_layout.setSpacing(8)
        self.assets_scroll.setWidget(self.assets_holder)
        root.addWidget(self.assets_scroll, 1)

        self._render_assets()

    def set_current_project(self, pid: Optional[str]):
        self.current_pid = pid
        self._render_assets()

    def reload_accounts(self):
        self.backend_panel.reload()

    def _render_assets(self):
        while self.assets_layout.count():
            it = self.assets_layout.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        if not self.current_pid:
            empty = QLabel("选个项目看素材")
            empty.setStyleSheet(f"color: {C['muted']}; padding: 40px 0;")
            empty.setAlignment(Qt.AlignCenter)
            self.assets_layout.addWidget(empty)
            self.assets_layout.addStretch()
            return

        assets_dir = ST.project_dir(self.current_pid) / "assets"
        files = sorted([f for f in assets_dir.iterdir() if f.is_file()],
                       key=lambda p: p.stat().st_mtime, reverse=True)

        if not files:
            tip = QLabel("素材库为空\n生成参考图/视频后会自动出现在这里")
            tip.setStyleSheet(f"color: {C['muted']}; font-size: 11px; padding: 40px 0;")
            tip.setAlignment(Qt.AlignCenter)
            self.assets_layout.addWidget(tip)
            self.assets_layout.addStretch()
            return

        for f in files[:50]:
            self.assets_layout.addWidget(self._make_asset_card(f))
        self.assets_layout.addStretch()

    def _make_asset_card(self, f: Path) -> QFrame:
        card = QFrame(); card.setObjectName("Card")
        l = QHBoxLayout(card); l.setContentsMargins(8, 8, 8, 8); l.setSpacing(10)
        is_video = f.suffix.lower() in (".mp4", ".mov", ".webm", ".avi")
        thumb = ThumbLabel((72, 54), "VID" if is_video else "IMG")
        if not is_video: thumb.set_image(f)
        l.addWidget(thumb)
        info = QVBoxLayout(); info.setSpacing(2)
        name = QLabel(f.name)
        name.setStyleSheet(f"font-size: 11px; color: {C['ink']};")
        info.addWidget(name)
        meta = QLabel(f"{f.stat().st_size // 1024} KB · "
                      f"{datetime.fromtimestamp(f.stat().st_mtime).strftime('%m-%d %H:%M')}")
        meta.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; "
                           f"font-size: 9.5px;")
        info.addWidget(meta)
        l.addLayout(info, 1)
        return card

    def _on_import(self):
        if not self.current_pid:
            QMessageBox.information(self, "提示", "请先选个项目"); return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "导入素材到当前项目", "",
            "媒体 (*.png *.jpg *.jpeg *.webp *.mp4 *.mov *.webm);;所有 (*.*)"
        )
        for p in paths:
            ST.import_asset(self.current_pid, Path(p))
        if paths:
            self.log.emit(f"导入 {len(paths)} 个素材")
            self._render_assets()


# ==============================================================
class BackendPanel(QFrame):
    """生成后端配额面板 - 分图片/视频两组显示。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.backends: List[GenerationBackend] = ST.load_backends()
        self.accounts: List[Account] = self._init_accounts()

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 12, 20, 14)
        v.setSpacing(10)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        v.addLayout(self.body)

        # hint
        hint = QLabel(
            "💡 点账号行的 🌐 按钮打开浏览器扫码登录,cookie 自动保存\n"
            "图片后端(GPT/即梦)用于生成 角色三视图 / 道具 / 分镜板大图;\n"
            "视频后端(豆包)用于把分镜板转成 10s 视频。"
        )
        hint.setStyleSheet(f"color: {C['muted']}; font-size: 10px; line-height: 1.4;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._render()

    def _init_accounts(self) -> List[Account]:
        accts = ST.load_accounts()
        if accts:
            # 老数据迁移:确保 backend_id 字段有值
            for a in accts:
                if not getattr(a, "backend_id", None):
                    a.backend_id = "doubao"
                # 兼容:把旧的 video_quota 字段映射到 daily_quota
                if not a.daily_quota_total and a.video_quota_total:
                    a.daily_quota_total = a.video_quota_total
                    a.daily_quota_used  = a.video_quota_used
            ST.save_accounts(accts)
            return accts

        # 首启:GPT 镜像 1 个 + 豆包 3 个
        import time
        ts = int(time.time() * 1000)
        accts = [
            Account(id=f"acc-gpt-{ts}", name="GPT 账号", backend_id="gpt-mirror",
                    color=PALETTE[3], daily_quota_total=0, daily_quota_used=0),
            *[
                Account(id=f"acc-db{i}-{ts}", name=f"豆包账号 {i}", backend_id="doubao",
                        color=PALETTE[i - 1], daily_quota_total=5, daily_quota_used=0,
                        video_quota_total=5, video_quota_used=0)
                for i in (1, 2, 3)
            ],
        ]
        ST.save_accounts(accts)
        return accts

    def reload(self):
        self.backends = ST.load_backends()
        self.accounts = ST.load_accounts()
        self._render()

    def _render(self):
        while self.body.count():
            it = self.body.takeAt(0); w = it.widget()
            if w: w.deleteLater()
            elif it.layout():
                while it.layout().count():
                    sub = it.layout().takeAt(0)
                    if sub.widget(): sub.widget().deleteLater()

        # 按 backend 分组
        image_backends = [b for b in self.backends if b.kind == BACKEND_IMAGE and b.enabled]
        video_backends = [b for b in self.backends if b.kind == BACKEND_VIDEO and b.enabled]

        if image_backends:
            self.body.addWidget(self._make_section_header("🖼  图片后端", "用于角色三视图 / 道具 / 分镜板"))
            for b in image_backends:
                self.body.addWidget(self._make_backend_card(b))

        if video_backends:
            self.body.addWidget(self._make_section_header("🎬  视频后端", "用于 10s 视频片段"))
            for b in video_backends:
                self.body.addWidget(self._make_backend_card(b))

    def _make_section_header(self, title: str, sub: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w); l.setContentsMargins(0, 6, 0, 0); l.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet(f"color: {C['ink']}; font-weight: 500; font-size: 12px;")
        s = QLabel(sub)
        s.setStyleSheet(f"color: {C['muted']}; font-size: 10px;")
        l.addWidget(t); l.addWidget(s)
        return w

    def _make_backend_card(self, b: GenerationBackend) -> QFrame:
        card = QFrame(); card.setObjectName("Card")
        l = QVBoxLayout(card); l.setContentsMargins(10, 8, 10, 8); l.setSpacing(6)

        # backend 头(图标 + 名 + URL)
        top = QHBoxLayout(); top.setSpacing(6)
        ic = QLabel(b.icon); ic.setStyleSheet("font-size: 14px;")
        top.addWidget(ic)
        name = QLabel(b.name)
        name.setStyleSheet(f"font-size: 12px; font-weight: 500;")
        top.addWidget(name)
        top.addStretch()
        url_lbl = QLabel(b.url.replace("https://", "").rstrip("/"))
        url_lbl.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; "
                              f"font-size: 9.5px;")
        top.addWidget(url_lbl)
        l.addLayout(top)

        # 此 backend 下的账号
        my_accts = [a for a in self.accounts if a.backend_id == b.id]
        if not my_accts:
            none_lbl = QLabel("无账号")
            none_lbl.setStyleSheet(f"color: {C['muted']}; font-size: 10px; padding: 2px 4px;")
            l.addWidget(none_lbl)
        else:
            for acc in my_accts:
                l.addWidget(self._make_account_row(acc))

        # 操作行
        actions = QHBoxLayout(); actions.setSpacing(4)
        add_btn = QPushButton("＋ 添加账号"); add_btn.setObjectName("Subtle")
        add_btn.setStyleSheet(f"""
            background: transparent; border: 1px dashed {C['border']};
            padding: 3px 8px; font-size: 10px; color: {C['muted']};
            border-radius: 4px;
        """)
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.clicked.connect(lambda: self._add_account(b.id))
        actions.addWidget(add_btn)
        actions.addStretch()
        l.addLayout(actions)

        return card

    def _make_account_row(self, acc: Account) -> QFrame:
        row = QFrame()
        row.setStyleSheet(f"background: {C['surface_alt']}; border-radius: 5px;")
        h = QHBoxLayout(row); h.setContentsMargins(8, 6, 8, 6); h.setSpacing(6)

        # 头像 + 在线指示点(右下角)
        av_box = QFrame()
        av_box.setFixedSize(22, 22)
        av = QLabel(av_box)
        av.setPixmap(make_avatar(acc.color, acc.name[0], 20))
        av.setFixedSize(20, 20)
        av.move(0, 0)
        is_online = self._is_session_online(acc.id)
        dot = QLabel(av_box)
        dot.setFixedSize(8, 8)
        dot.move(14, 14)
        dot.setStyleSheet(
            f"background: {C['online'] if is_online else C['muted']};"
            f"border-radius: 4px; border: 1.5px solid {C['surface_alt']};"
        )
        h.addWidget(av_box)

        name = QLabel(acc.name)
        name.setStyleSheet(f"font-size: 11px; color: {C['ink']};")
        h.addWidget(name, 1)

        # 配额
        if acc.is_unlimited():
            q = QLabel("∞")
            q.setStyleSheet(f"""
                color: {C['online']}; font-family: 'JetBrains Mono', monospace;
                font-size: 14px; font-weight: 600;
            """)
            h.addWidget(q)
        else:
            remaining = acc.remaining()
            total = acc.daily_quota_total
            qcolor = (C['online'] if remaining >= 3 else
                      (C['warning'] if remaining > 0 else C['danger']))
            q = QLabel(f"{remaining}/{total}")
            q.setStyleSheet(f"""
                color: {qcolor}; font-family: 'JetBrains Mono', monospace;
                font-size: 12px; font-weight: 600;
            """)
            h.addWidget(q)
            minus = QPushButton("−"); minus.setObjectName("IconOnly")
            minus.setFixedSize(20, 20); minus.setToolTip("模拟用掉 1 个额度")
            minus.clicked.connect(lambda: self._adjust(acc.id, +1))
            h.addWidget(minus)
            plus = QPushButton("+"); plus.setObjectName("IconOnly")
            plus.setFixedSize(20, 20); plus.setToolTip("退还 1 个额度")
            plus.clicked.connect(lambda: self._adjust(acc.id, -1))
            h.addWidget(plus)

        # 🌐 打开浏览器扫码登录 — 关键功能
        login_btn = QPushButton("🌐"); login_btn.setObjectName("IconOnly")
        login_btn.setFixedSize(22, 22)
        attach_mode = "CDP" if acc.attach_cdp_url else "Playwright"
        if is_online:
            login_btn.setToolTip(
                f"模式: {attach_mode} (已在线)\n"
                f"点击聚焦或重新跳转;扫码登录后 cookie 自动保存"
            )
        elif acc.attach_cdp_url:
            login_btn.setToolTip(
                f"模式: 挂载本机 Chrome ({acc.attach_cdp_url})\n"
                f"先确保你已用 --remote-debugging-port 启动了 Chrome\n"
                f"点击 → 工具通过 CDP 连过去,复用你的登录"
            )
        else:
            login_btn.setToolTip(
                f"模式: Playwright 自启 Chromium(隔离环境)\n"
                f"打开浏览器跳到 {acc.backend_id} 主页\n"
                f"扫码登录后 cookie 保存,以后任务无需重登\n"
                f"\n"
                f"👉 想用你自己的 Chrome?点旁边的 ⚙ 切到 CDP 挂载模式"
            )
        login_btn.setStyleSheet(
            f"font-size: 13px;"
            f"color: {C['online'] if is_online else C['accent']};"
        )
        login_btn.clicked.connect(lambda: self._launch_browser(acc.id))
        h.addWidget(login_btn)

        # ⚙ 切换挂载模式
        mode_btn = QPushButton("⚙"); mode_btn.setObjectName("IconOnly")
        mode_btn.setFixedSize(20, 20)
        mode_btn.setToolTip(
            f"切换浏览器挂载模式\n"
            f"当前: {attach_mode}\n\n"
            f"Playwright: 工具自启隔离 Chromium(默认,需扫码)\n"
            f"CDP: 挂载本机已开的 Chrome(复用你的登录)"
        )
        mode_btn.clicked.connect(lambda: self._toggle_attach_mode(acc.id))
        h.addWidget(mode_btn)

        rm = QPushButton("✕"); rm.setObjectName("IconOnly")
        rm.setFixedSize(20, 20); rm.setToolTip("删除账号")
        rm.clicked.connect(lambda: self._delete(acc.id))
        h.addWidget(rm)
        return row

    def _is_session_online(self, acc_id: str) -> bool:
        """该账号的 Chromium 会话是否已启动。"""
        try:
            from .playwright_session import get_pool, HAS_PLAYWRIGHT
            if not HAS_PLAYWRIGHT: return False
            sess = get_pool().get(acc_id)
            return bool(sess and sess.status.online)
        except Exception:
            return False

    def _launch_browser(self, acc_id: str):
        """启动账号 Chromium → 跳到 backend home_url → 用户扫码登录。

        cookie 通过 launch_persistent_context 自动保存,
        以后任务派发时无需重新登录。

        若 acc.attach_cdp_url 非空,改走 CDP 挂载到已开 Chrome(复用用户登录)。
        """
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc:
            QMessageBox.warning(self, "错误", "找不到该账号"); return

        # 1. Playwright 装了吗
        try:
            from .playwright_session import HAS_PLAYWRIGHT, get_pool
        except ImportError:
            HAS_PLAYWRIGHT = False
        if not HAS_PLAYWRIGHT:
            QMessageBox.warning(
                self, "Playwright 未安装",
                "需要先装 Playwright 才能启动浏览器:\n\n"
                "  pip install playwright\n"
                "  playwright install chromium\n\n"
                "或者你可以手动打开浏览器登录,"
                "之后用「📋 复制 prompt」按钮配合手动操作。"
            ); return

        # 2. backend 配置
        backend = ST.get_backend(acc.backend_id)
        if not backend:
            QMessageBox.warning(self, "错误",
                f"找不到 backend 配置: {acc.backend_id}\n"
                f"右栏底部应该有「+ 添加账号」按钮重建"
            ); return

        # 3. 启动 / 复用 session(同步阻塞 → WaitCursor)
        pool = get_pool()
        sess = pool.get_or_create(acc)
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            if not sess.status.online:
                if acc.attach_cdp_url:
                    self.log.emit(f"[{acc.name}] 挂载到 {acc.attach_cdp_url}...")
                    sess.attach_cdp(acc.attach_cdp_url)
                    self.log.emit(f"[{acc.name}] 已挂载本机 Chrome")
                else:
                    self.log.emit(f"[{acc.name}] 启动 Chromium...")
                    sess.start(headless=False)
                    self.log.emit(f"[{acc.name}] 浏览器已启动,跳转到 {backend.url}")
            sess.goto(backend.url)
            self.log.emit(
                f"[{acc.name}] 已打开 {backend.name} — 请在弹出的浏览器扫码登录\n"
                f"  cookie 会自动保存到 ~/.doubao-studio/profiles/{acc_id}/\n"
                f"  以后生成任务时无需重新登录"
            )
            self._render()
        except Exception as e:
            err_msg = str(e)
            tip = ""
            low = err_msg.lower()
            if "has been closed" in low or "target" in low:
                tip = ("\n\n看起来浏览器在刚才被关掉了。\n"
                       "再点一次 🌐 应该会重新启动。")
            elif "chrome" in low or "chromium" in low:
                tip = ("\n\n可能原因:\n"
                       "1. 未装 Chromium → 跑 `playwright install chromium`\n"
                       "2. 本机 Chrome 版本过旧 → 升级或装 Chromium")
            elif "cdp" in low or "9222" in err_msg or "connect" in low:
                tip = ("\n\nCDP 挂载失败。检查:\n"
                       "1. Chrome 是否用 --remote-debugging-port=9222 启动了\n"
                       "2. 端口号是否对(默认 9222)\n"
                       "3. 浏览器里访问 http://localhost:9222 看是否有响应")
            QMessageBox.critical(self, "启动失败", f"{err_msg}{tip}")
            self.log.emit(f"[{acc.name}] 启动失败: {err_msg}")
        finally:
            QGuiApplication.restoreOverrideCursor()

    def _toggle_attach_mode(self, acc_id: str):
        """切换账号的挂载模式(Playwright vs CDP)。"""
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return

        if acc.attach_cdp_url:
            # 当前 = CDP 模式 → 切回 Playwright
            from PySide6.QtWidgets import QMessageBox as _M
            r = _M.question(
                self, "切回 Playwright 模式",
                f"切回工具自启 Chromium 模式吗?\n"
                f"(隔离 cookie,首次需在工具的浏览器里重新扫码登录)"
            )
            if r != _M.Yes: return
            # 先停掉现有 session
            try:
                from .playwright_session import get_pool
                sess = get_pool().get(acc.id)
                if sess: sess.stop()
            except Exception: pass
            acc.attach_cdp_url = ""
            ST.save_accounts(self.accounts)
            self.log.emit(f"[{acc.name}] 已切回 Playwright 模式")
            self._render()
        else:
            # 当前 = Playwright → 切到 CDP
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(
                self, "挂载到已开 Chrome",
                "调试端口 URL(默认 http://localhost:9222):\n\n"
                "先在终端启动 Chrome:\n"
                "  macOS:  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222\n"
                "  Win:    \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port=9222\n"
                "  Linux:  google-chrome --remote-debugging-port=9222\n\n"
                "然后在新开的 Chrome 里登录账号,再回来确定。",
                text="http://localhost:9222"
            )
            if not ok or not text.strip(): return
            # 先停掉现有
            try:
                from .playwright_session import get_pool
                sess = get_pool().get(acc.id)
                if sess: sess.stop()
            except Exception: pass
            acc.attach_cdp_url = text.strip()
            ST.save_accounts(self.accounts)
            self.log.emit(f"[{acc.name}] 已切到 CDP 挂载模式: {acc.attach_cdp_url}")
            self._render()

    def _add_account(self, backend_id: str):
        b = ST.get_backend(backend_id)
        prefix = "GPT 账号" if backend_id == "gpt-mirror" else "豆包账号"
        name, ok = QInputDialog.getText(self, f"添加 {b.name if b else backend_id} 账号", "账号名:",
                                        text=f"{prefix} {len([a for a in self.accounts if a.backend_id == backend_id]) + 1}")
        if not ok or not name.strip(): return

        is_image = b and b.kind == BACKEND_IMAGE
        import time
        new = Account(
            id=f"acc-{int(time.time() * 1000)}",
            name=name.strip(),
            backend_id=backend_id,
            color=PALETTE[len(self.accounts) % len(PALETTE)],
            daily_quota_total=0 if is_image else 5,
            daily_quota_used=0,
            video_quota_total=0 if is_image else 5,
            video_quota_used=0,
        )
        self.accounts.append(new)
        ST.save_accounts(self.accounts)
        self._render()
        self.log.emit(f"新增账号: {name}")

    def _adjust(self, acc_id: str, delta: int):
        for acc in self.accounts:
            if acc.id == acc_id:
                acc._maybe_reset()
                if acc.is_unlimited(): return
                acc.daily_quota_used = max(0, min(acc.daily_quota_total,
                                                  (acc.daily_quota_used or 0) + delta))
                acc.video_quota_used = acc.daily_quota_used   # 同步旧字段
                break
        ST.save_accounts(self.accounts)
        self._render()
        self.log.emit(f"配额调整: {acc.name} 余 {acc.remaining()}")

    def _delete(self, acc_id: str):
        acc = next((a for a in self.accounts if a.id == acc_id), None)
        if not acc: return
        ans = QMessageBox.question(
            self, "删除账号",
            f"确定删除 「{acc.name}」 ?\n"
            f"~/.doubao-studio/profiles/{acc_id}/ 会保留(M2 时还能复用 Chrome 数据)",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        ST.save_accounts(self.accounts)
        self._render()


# ==============================================================
class QueuePanel(QFrame):
    """实时任务队列显示。订阅 TaskQueue.changed 信号自动刷新。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        from .task_queue import get_queue
        self.queue = get_queue()

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 12, 20, 12); v.setSpacing(6)

        hd = QHBoxLayout()
        t = QLabel("任务队列")
        t.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; "
                        f"font-size: 10px; letter-spacing: 1px;")
        hd.addWidget(t)
        hd.addStretch()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {C['muted']}; font-size: 9.5px;")
        hd.addWidget(self.status_lbl)
        clear_btn = QPushButton("清历史"); clear_btn.setObjectName("IconOnly")
        clear_btn.setStyleSheet(f"color: {C['muted']}; font-size: 10px;")
        clear_btn.clicked.connect(self._on_clear)
        hd.addWidget(clear_btn)
        v.addLayout(hd)

        self.list_box = QVBoxLayout(); self.list_box.setSpacing(4)
        v.addLayout(self.list_box)

        self.queue.changed.connect(self._render)
        self._render()

    def _render(self):
        while self.list_box.count():
            it = self.list_box.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        all_tasks = self.queue.recent(8)
        pending = self.queue.pending()
        active = self.queue.active()
        self.status_lbl.setText(f"{len(pending)} 待 · {len(active)} 跑")

        if not all_tasks:
            tip = QLabel("队列空。点角色/分镜的「🤖 用 GPT 生成」就会有任务进来。")
            tip.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
            tip.setWordWrap(True)
            self.list_box.addWidget(tip)
            return

        for t in all_tasks:
            self.list_box.addWidget(self._make_task_row(t))

    def _make_task_row(self, t) -> QFrame:
        from .models import (
            TASK_PENDING, TASK_RUNNING, TASK_AWAITING, TASK_DONE, TASK_FAILED, TASK_CANCELED,
        )
        row = QFrame()
        status_colors = {
            TASK_PENDING:  C["muted"],
            TASK_RUNNING:  C["info"],
            TASK_AWAITING: C["warning"],
            TASK_DONE:     C["online"],
            TASK_FAILED:   C["danger"],
            TASK_CANCELED: C["muted"],
        }
        bg_colors = {
            TASK_DONE:     C["surface_alt"],
            TASK_FAILED:   "#fef2f2",
            TASK_RUNNING:  "#eff6ff",
            TASK_AWAITING: "#fffbeb",
        }
        bg = bg_colors.get(t.status, C["surface_alt"])
        fg = status_colors.get(t.status, C["muted"])
        row.setStyleSheet(f"background: {bg}; border-radius: 5px;")

        h = QHBoxLayout(row); h.setContentsMargins(8, 6, 8, 6); h.setSpacing(6)

        # icon
        icon_map = {"image": "🖼", "video": "🎬", "ai_chat": "🧠"}
        ic = QLabel(icon_map.get(t.task_type, "•"))
        ic.setStyleSheet("font-size: 12px;")
        h.addWidget(ic)

        # title
        title = QLabel(t.title or "(未命名任务)")
        title.setStyleSheet(f"font-size: 11px; color: {C['ink']};")
        h.addWidget(title, 1)

        # status
        st = QLabel(t.queued_label())
        st.setStyleSheet(f"color: {fg}; font-family: 'JetBrains Mono', monospace; "
                         f"font-size: 9.5px;")
        h.addWidget(st)

        # 操作 - 仅 pending 时可取消
        if t.status == TASK_PENDING:
            x = QPushButton("✕"); x.setObjectName("IconOnly")
            x.setFixedSize(18, 18)
            x.clicked.connect(lambda: (self.queue.cancel(t.id),
                                       self.log.emit(f"取消任务: {t.title}")))
            h.addWidget(x)

        return row

    def _on_clear(self):
        self.queue.clear_history()
        self.log.emit("已清空任务历史")
