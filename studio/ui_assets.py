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

        # 2. 任务队列
        root.addWidget(Hline(soft=True))
        queue_box = QFrame()
        ql = QVBoxLayout(queue_box); ql.setContentsMargins(20, 12, 20, 12); ql.setSpacing(6)
        qh = QHBoxLayout()
        qt = QLabel("任务队列")
        qt.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; "
                         f"font-size: 10px; letter-spacing: 1px;")
        qh.addWidget(qt); qh.addStretch()
        m2 = QLabel("M2 接通")
        m2.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-size: 9.5px; padding: 1px 6px; border-radius: 3px;
            font-family: 'JetBrains Mono', monospace;
        """)
        qh.addWidget(m2)
        ql.addLayout(qh)
        empty_q = QLabel("接通 Playwright 后,这里显示等待中的图片/视频生成任务")
        empty_q.setStyleSheet(f"color: {C['muted']}; font-size: 11px; padding: 4px 0;")
        empty_q.setWordWrap(True)
        ql.addWidget(empty_q)
        root.addWidget(queue_box)

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

        av = QLabel()
        av.setPixmap(make_avatar(acc.color, acc.name[0], 20))
        av.setFixedSize(20, 20)
        h.addWidget(av)

        name = QLabel(acc.name)
        name.setStyleSheet(f"font-size: 11px; color: {C['ink']};")
        h.addWidget(name, 1)

        # 配额(无限或 X/N)
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

        rm = QPushButton("✕"); rm.setObjectName("IconOnly")
        rm.setFixedSize(20, 20); rm.setToolTip("删除账号")
        rm.clicked.connect(lambda: self._delete(acc.id))
        h.addWidget(rm)
        return row

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
