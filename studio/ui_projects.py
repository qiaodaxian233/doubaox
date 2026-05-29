"""
左栏:项目导航
顶部:项目列表(增删切换),底部:选中项目后展开角色/场景/道具/集 子导航。
"""
from __future__ import annotations
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QScrollArea, QWidget, QInputDialog, QMessageBox, QSizePolicy
)

from .theme import C
from .widgets import Hline, make_avatar, ThumbLabel
from .models import Project
from . import storage as ST


# Tab 标识
TAB_OVERVIEW   = "overview"
TAB_BIBLE      = "bible"
TAB_CHARACTERS = "characters"
TAB_SCENES     = "scenes"
TAB_PROPS      = "props"
TAB_EPISODES   = "episodes"
TAB_CANVAS     = "canvas"

TAB_LABELS = [
    (TAB_OVERVIEW,   "概览",     "📋"),
    (TAB_BIBLE,      "世界圣经", "🌐"),
    (TAB_CHARACTERS, "角色库",   "👤"),
    (TAB_SCENES,     "场景库",   "🏞"),
    (TAB_PROPS,      "道具库",   "📿"),
    (TAB_EPISODES,   "分镜表",   "🎬"),
    (TAB_CANVAS,     "画布",     "🎨"),
]


class ProjectCard(QFrame):
    selected         = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, p: Project):
        super().__init__()
        self.project = p
        self._selected = False
        self.setObjectName("Card")
        self.setCursor(QCursor(Qt.PointingHandCursor))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10); outer.setSpacing(6)

        top = QHBoxLayout(); top.setSpacing(8)
        icon = QLabel("🎬"); icon.setStyleSheet("font-size: 18px;")
        top.addWidget(icon)
        self.name_label = QLabel(p.name)
        self.name_label.setStyleSheet(f"color: {C['ink']}; font-weight: 500; font-size: 13px;")
        top.addWidget(self.name_label, 1)
        outer.addLayout(top)

        meta = QHBoxLayout(); meta.setSpacing(6)
        style_lbl = QLabel(p.style or "未分类")
        style_lbl.setStyleSheet(f"""
            background: {C['accent_soft']}; color: {C['accent']};
            font-size: 9.5px; padding: 1px 6px; border-radius: 3px;
        """)
        meta.addWidget(style_lbl)
        ar_lbl = QLabel(p.aspect_ratio)
        ar_lbl.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-family: "JetBrains Mono", monospace;
            font-size: 9.5px; padding: 1px 6px; border-radius: 3px;
        """)
        meta.addWidget(ar_lbl)
        dur_lbl = QLabel(f"{p.target_duration}s")
        dur_lbl.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-family: "JetBrains Mono", monospace;
            font-size: 9.5px; padding: 1px 6px; border-radius: 3px;
        """)
        meta.addWidget(dur_lbl)
        meta.addStretch()
        outer.addLayout(meta)

    def mousePressEvent(self, e):
        self.selected.emit(self.project.id)
        super().mousePressEvent(e)

    def set_selected(self, v: bool):
        self._selected = v
        self.setObjectName("CardSelected" if v else "Card")
        self.style().unpolish(self); self.style().polish(self)

    def update_name(self, n: str):
        self.name_label.setText(n)


class ProjectNavigator(QFrame):
    """
    左栏。两种状态:
      - 没选中项目:显示项目列表 + 新建按钮
      - 选中项目后:顶部项目名+返回按钮,中部 5 个 tab
    """
    project_selected = Signal(str)         # 选中某项目(回到 main)
    project_changed  = Signal()            # 列表改动(增/删/改)
    tab_changed      = Signal(str, str)    # (project_id, tab_id)

    def __init__(self):
        super().__init__()
        self.setObjectName("Panel")
        self.setFixedWidth(280)

        self.projects: List[Project] = []
        self.selected_pid: Optional[str] = None
        self.selected_tab: str = TAB_OVERVIEW
        self.cards = {}

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        # 两种视图,通过 _rebuild 切换
        self._rebuild()
        self.reload_projects()

    def reload_projects(self):
        self.projects = ST.list_projects()
        self._rebuild()
        # 自动选中第一项(如果有)
        if self.projects and self.selected_pid is None:
            self.select_project(self.projects[0].id)

    def select_project(self, pid: str):
        self.selected_pid = pid
        self.selected_tab = TAB_OVERVIEW
        self._rebuild()
        self.project_selected.emit(pid)

    def go_back(self):
        self.selected_pid = None
        self._rebuild()
        self.project_selected.emit("")

    def select_tab(self, tab_id: str):
        self.selected_tab = tab_id
        self._rebuild_tabs()
        if self.selected_pid:
            self.tab_changed.emit(self.selected_pid, tab_id)

    def _rebuild(self):
        # 清空
        while self.root_layout.count():
            item = self.root_layout.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget(): sub.widget().deleteLater()

        if self.selected_pid is None:
            self._build_project_list()
        else:
            self._build_project_detail()

    def _build_project_list(self):
        # Header
        hdr_box = QVBoxLayout()
        hdr_box.setContentsMargins(20, 20, 20, 16)
        hdr_box.setSpacing(6)
        title = QLabel("项目库"); title.setObjectName("H1")
        sub = QLabel("SHORT DRAMA · 短剧工厂"); sub.setObjectName("Mono")
        hdr_box.addWidget(title); hdr_box.addWidget(sub)
        self.root_layout.addLayout(hdr_box)

        # 新建按钮
        btn_box = QVBoxLayout(); btn_box.setContentsMargins(16, 0, 16, 16)
        add_btn = QPushButton("＋  新建项目"); add_btn.setObjectName("Primary")
        add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_btn.clicked.connect(self._on_add_project)
        btn_box.addWidget(add_btn)
        self.root_layout.addLayout(btn_box)

        # 列表头
        lh = QHBoxLayout(); lh.setContentsMargins(20, 0, 20, 6)
        l1 = QLabel("项目列表"); l1.setObjectName("Mono")
        cnt = QLabel(f"{len(self.projects)} 个"); cnt.setObjectName("Mono")
        lh.addWidget(l1); lh.addStretch(); lh.addWidget(cnt)
        self.root_layout.addLayout(lh)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        wrap = QWidget(); wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 4, 12, 16); wl.setSpacing(8)

        self.cards = {}
        for p in self.projects:
            c = ProjectCard(p)
            c.selected.connect(self.select_project)
            wl.addWidget(c)
            self.cards[p.id] = c
        wl.addStretch()
        if not self.projects:
            empty = QLabel("还没有项目\n点上面「新建项目」开始")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {C['muted']}; font-size: 12px; padding: 40px 0;")
            wl.addWidget(empty)

        scroll.setWidget(wrap)
        self.root_layout.addWidget(scroll, 1)

    def _build_project_detail(self):
        p = next((x for x in self.projects if x.id == self.selected_pid), None)
        if not p:
            self.selected_pid = None
            self._build_project_list()
            return

        # Header (项目名 + 返回)
        hdr = QFrame(); hdr.setObjectName("Panel")
        hl = QVBoxLayout(hdr); hl.setContentsMargins(20, 18, 16, 14); hl.setSpacing(8)

        back_row = QHBoxLayout()
        back_btn = QPushButton("← 项目列表"); back_btn.setObjectName("IconOnly")
        back_btn.setStyleSheet(f"color: {C['muted']}; font-size: 11px; padding: 2px 4px;")
        back_btn.setCursor(QCursor(Qt.PointingHandCursor))
        back_btn.clicked.connect(self.go_back)
        back_row.addWidget(back_btn); back_row.addStretch()
        edit_btn = QPushButton("✎"); edit_btn.setObjectName("IconOnly")
        edit_btn.setToolTip("重命名"); edit_btn.clicked.connect(self._on_rename)
        back_row.addWidget(edit_btn)
        del_btn = QPushButton("🗑"); del_btn.setObjectName("IconOnly")
        del_btn.setToolTip("删除项目"); del_btn.clicked.connect(self._on_delete)
        back_row.addWidget(del_btn)
        hl.addLayout(back_row)

        name = QLabel(p.name); name.setObjectName("H2")
        name.setWordWrap(True)
        hl.addWidget(name)

        meta = QHBoxLayout(); meta.setSpacing(6)
        for text, color in [
            (p.style or "未分类", "accent"),
            (p.aspect_ratio, "muted"),
            (f"{p.target_duration}s", "muted"),
        ]:
            lbl = QLabel(text)
            if color == "accent":
                lbl.setStyleSheet(f"""
                    background: {C['accent_soft']}; color: {C['accent']};
                    font-size: 10px; padding: 2px 7px; border-radius: 3px;
                """)
            else:
                lbl.setStyleSheet(f"""
                    background: {C['surface_alt']}; color: {C['muted']};
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px; padding: 2px 7px; border-radius: 3px;
                """)
            meta.addWidget(lbl)
        meta.addStretch()
        hl.addLayout(meta)

        self.root_layout.addWidget(hdr)
        self.root_layout.addWidget(Hline())

        # Tabs
        self._tabs_container = QVBoxLayout()
        self._tabs_container.setContentsMargins(0, 0, 0, 0)
        self._tabs_container.setSpacing(0)
        self.root_layout.addLayout(self._tabs_container)
        self._rebuild_tabs()

        self.root_layout.addStretch()

        # Footer: 项目目录
        footer = QFrame(); footer.setStyleSheet(f"background: {C['surface_alt']};")
        fl = QVBoxLayout(footer); fl.setContentsMargins(16, 10, 16, 12); fl.setSpacing(2)
        path_lbl = QLabel(f"~/.doubao-studio/projects/{p.id}/")
        path_lbl.setStyleSheet(f"""
            color: {C['muted']}; font-family: 'JetBrains Mono', monospace;
            font-size: 9.5px;
        """)
        path_lbl.setWordWrap(True)
        fl.addWidget(path_lbl)
        self.root_layout.addWidget(footer)

    def _rebuild_tabs(self):
        # 清空
        while self._tabs_container.count():
            it = self._tabs_container.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

        for tab_id, label, icon in TAB_LABELS:
            active = tab_id == self.selected_tab
            btn = QPushButton(f"  {icon}   {label}")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left; padding: 12px 18px;
                    background: {C['surface_alt'] if active else 'transparent'};
                    border: none;
                    border-left: 3px solid {C['accent'] if active else 'transparent'};
                    color: {C['ink'] if active else C['ink_soft']};
                    font-weight: {'500' if active else '400'};
                }}
                QPushButton:hover {{ background: {C['border_soft']}; }}
            """)
            btn.clicked.connect(lambda _, t=tab_id: self.select_tab(t))
            self._tabs_container.addWidget(btn)

    # ---- 增删改 ----
    def _on_add_project(self):
        from .ui_dialogs import NewProjectDialog
        dlg = NewProjectDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            p = dlg.build_project()
            ST.save_project(p)
            self.projects.append(p)
            self.project_changed.emit()
            self.select_project(p.id)

    def _on_rename(self):
        p = next((x for x in self.projects if x.id == self.selected_pid), None)
        if not p: return
        new_name, ok = QInputDialog.getText(self, "重命名项目", "新名称:",
                                            text=p.name)
        if ok and new_name.strip():
            p.name = new_name.strip()
            ST.save_project(p)
            self.project_changed.emit()
            self._build_project_detail()

    def _on_delete(self):
        p = next((x for x in self.projects if x.id == self.selected_pid), None)
        if not p: return
        ans = QMessageBox.question(
            self, "删除项目",
            f"删除项目「{p.name}」?\n"
            f"会同步删除本地目录 ~/.doubao-studio/projects/{p.id}/\n"
            "(角色、场景、分镜、生成的图片视频全部丢失)\n\n"
            "此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No
        )
        if ans != QMessageBox.Yes: return
        ST.delete_project(p.id)
        self.projects = [x for x in self.projects if x.id != p.id]
        self.selected_pid = None
        self.project_changed.emit()
        self._rebuild()
