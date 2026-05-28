"""
右栏:
- 上半:账号配额面板(每账号 X/5 视频额度)
- 中:任务队列(M1 占位,M2 实现)
- 下:已生成素材库(图片/视频混合,可拖回分镜)
"""
from __future__ import annotations
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QInputDialog, QMessageBox, QFileDialog
)

from .theme import C, PALETTE
from .widgets import Hline, make_avatar, ThumbLabel
from .models import Account
from . import storage as ST


class AssetsPanel(QFrame):
    """右栏总容器。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(360)

        self.accounts: List[Account] = []
        self.current_pid: Optional[str] = None

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header
        h = QFrame(); hl = QVBoxLayout(h); hl.setContentsMargins(20, 18, 20, 12); hl.setSpacing(2)
        t = QLabel("制作台"); t.setObjectName("H1")
        s = QLabel("ACCOUNTS · QUEUE · ASSETS"); s.setObjectName("Mono")
        hl.addWidget(t); hl.addWidget(s)
        root.addWidget(h); root.addWidget(Hline())

        # 1. 账号配额面板
        self.quota_panel = QuotaPanel()
        self.quota_panel.log.connect(self.log)
        root.addWidget(self.quota_panel)

        # 2. 任务队列 (M1 占位)
        root.addWidget(Hline(soft=True))
        queue_box = QFrame()
        ql = QVBoxLayout(queue_box); ql.setContentsMargins(20, 12, 20, 12); ql.setSpacing(6)
        qh = QHBoxLayout()
        qt = QLabel("任务队列"); qt.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px;")
        qh.addWidget(qt); qh.addStretch()
        m2 = QLabel("M2 实现"); m2.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-size: 9.5px; padding: 1px 6px; border-radius: 3px;
            font-family: 'JetBrains Mono', monospace;
        """)
        qh.addWidget(m2)
        ql.addLayout(qh)
        empty_q = QLabel("队列为空 · M2 接通生成后这里会显示等待中的任务")
        empty_q.setStyleSheet(f"color: {C['muted']}; font-size: 11px; padding: 4px 0;")
        empty_q.setWordWrap(True)
        ql.addWidget(empty_q)
        root.addWidget(queue_box)

        # 3. 已生成素材库
        root.addWidget(Hline(soft=True))
        ah = QFrame(); ahl = QHBoxLayout(ah); ahl.setContentsMargins(20, 12, 20, 8)
        ahl_t = QLabel("素材库"); ahl_t.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px;")
        ahl.addWidget(ahl_t); ahl.addStretch()
        imp = QPushButton("⬇ 导入"); imp.setObjectName("IconOnly")
        imp.setStyleSheet(f"color: {C['accent']}; font-size: 11px;")
        imp.setToolTip("把外部生成结果导入素材库")
        imp.clicked.connect(self._on_import)
        ahl.addWidget(imp)
        root.addWidget(ah)

        self.assets_scroll = QScrollArea(); self.assets_scroll.setWidgetResizable(True); self.assets_scroll.setFrameShape(QFrame.NoFrame)
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
        self.quota_panel.reload()

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

        # 扫描 project assets/ 目录
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

        for f in files[:50]:   # 最多显示 50 个
            self.assets_layout.addWidget(self._make_asset_card(f))
        self.assets_layout.addStretch()

    def _make_asset_card(self, f: Path) -> QFrame:
        card = QFrame(); card.setObjectName("Card")
        l = QHBoxLayout(card); l.setContentsMargins(8, 8, 8, 8); l.setSpacing(10)

        is_video = f.suffix.lower() in (".mp4", ".mov", ".webm", ".avi")
        thumb = ThumbLabel((72, 54), "VID" if is_video else "IMG")
        if not is_video:
            thumb.set_image(f)
        l.addWidget(thumb)

        info = QVBoxLayout(); info.setSpacing(2)
        name = QLabel(f.name)
        name.setStyleSheet(f"font-size: 11px; color: {C['ink']};")
        name.setWordWrap(False)
        info.addWidget(name)
        meta = QLabel(f"{f.stat().st_size // 1024} KB · {datetime.fromtimestamp(f.stat().st_mtime).strftime('%m-%d %H:%M')}")
        meta.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 9.5px;")
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


# =========================================================================
class QuotaPanel(QFrame):
    """账号配额面板。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.accounts: List[Account] = ST.load_accounts()
        if not self.accounts:
            # 默认 3 个账号
            self.accounts = [
                Account(id=f"acc-{i}", name=f"账号 {i}", color=PALETTE[i-1])
                for i in (1, 2, 3)
            ]
            ST.save_accounts(self.accounts)

        v = QVBoxLayout(self); v.setContentsMargins(20, 12, 20, 14); v.setSpacing(8)

        head = QHBoxLayout()
        t = QLabel("账号配额"); t.setStyleSheet(f"color: {C['muted']}; font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: 1px;")
        head.addWidget(t)
        head.addStretch()
        self.total_label = QLabel(""); self.total_label.setStyleSheet(f"""
            color: {C['accent']}; font-family: 'JetBrains Mono', monospace;
            font-size: 11px; font-weight: 500;
        """)
        head.addWidget(self.total_label)
        v.addLayout(head)

        self.accounts_box = QVBoxLayout(); self.accounts_box.setSpacing(6)
        v.addLayout(self.accounts_box)

        add = QPushButton("＋ 添加账号"); add.setObjectName("Subtle")
        add.setCursor(QCursor(Qt.PointingHandCursor))
        add.clicked.connect(self._add)
        v.addWidget(add)

        hint = QLabel("豆包每账号每天 5 个视频额度;\n图片不限。点账号可手动 -1/+1 模拟消耗。")
        hint.setStyleSheet(f"color: {C['muted']}; font-size: 10px; line-height: 1.4;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._render()

    def reload(self):
        self.accounts = ST.load_accounts()
        self._render()

    def _render(self):
        while self.accounts_box.count():
            it = self.accounts_box.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        total_remaining = 0
        total_total = 0
        for acc in self.accounts:
            total_remaining += acc.remaining()
            total_total += acc.video_quota_total
            self.accounts_box.addWidget(self._make_acc_row(acc))

        self.total_label.setText(f"今日剩余 {total_remaining} / {total_total} 视频")

    def _make_acc_row(self, acc: Account) -> QFrame:
        row = QFrame(); row.setStyleSheet(f"""
            background: {C['surface_alt']};
            border-radius: 6px;
        """)
        h = QHBoxLayout(row); h.setContentsMargins(10, 8, 10, 8); h.setSpacing(8)

        # avatar
        av = QLabel(); av.setPixmap(make_avatar(acc.color, acc.name[0], 24))
        av.setFixedSize(24, 24)
        h.addWidget(av)

        # name
        name = QLabel(acc.name)
        name.setStyleSheet(f"font-size: 12px; color: {C['ink']};")
        h.addWidget(name, 1)

        # quota
        remaining = acc.remaining()
        qcolor = C['online'] if remaining >= 3 else (C['warning'] if remaining > 0 else C['danger'])
        q = QLabel(f"{remaining}/{acc.video_quota_total}")
        q.setStyleSheet(f"""
            color: {qcolor}; font-family: 'JetBrains Mono', monospace;
            font-size: 13px; font-weight: 600;
        """)
        h.addWidget(q)

        # -1 / +1
        minus = QPushButton("−"); minus.setObjectName("IconOnly")
        minus.setFixedSize(22, 22); minus.setToolTip("模拟用掉 1 个视频额度")
        minus.clicked.connect(lambda: self._adjust(acc.id, +1))
        h.addWidget(minus)
        plus = QPushButton("+"); plus.setObjectName("IconOnly")
        plus.setFixedSize(22, 22); plus.setToolTip("退还 1 个额度")
        plus.clicked.connect(lambda: self._adjust(acc.id, -1))
        h.addWidget(plus)

        # 删除
        rm = QPushButton("✕"); rm.setObjectName("IconOnly")
        rm.setFixedSize(22, 22); rm.setToolTip("删除账号")
        rm.clicked.connect(lambda: self._delete(acc.id))
        h.addWidget(rm)

        return row

    def _adjust(self, acc_id: str, delta: int):
        for acc in self.accounts:
            if acc.id == acc_id:
                acc._maybe_reset()
                acc.video_quota_used = max(0, min(acc.video_quota_total, acc.video_quota_used + delta))
                break
        ST.save_accounts(self.accounts)
        self._render()
        self.log.emit(f"配额调整: {acc_id} 余 {acc.remaining()}")

    def _add(self):
        name, ok = QInputDialog.getText(self, "添加账号", "账号名:")
        if not ok or not name.strip(): return
        new = Account(
            id=f"acc-{int(__import__('time').time()*1000)}",
            name=name.strip(),
            color=PALETTE[len(self.accounts) % len(PALETTE)],
        )
        self.accounts.append(new)
        ST.save_accounts(self.accounts)
        self._render()
        self.log.emit(f"新增账号: {name}")

    def _delete(self, acc_id: str):
        ans = QMessageBox.question(self, "删除账号",
                                   f"确定删除?\n该账号的 ~/.doubao-studio/profiles/{acc_id}/ 会保留",
                                   QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        ST.save_accounts(self.accounts)
        self._render()
