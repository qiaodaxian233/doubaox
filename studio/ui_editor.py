"""
中栏:5 种视图,根据左栏选中的 tab 切换。
- 概览
- 角色库 (grid)
- 场景库 (grid)
- 道具库 (grid)
- 分镜表 (集列表 + 表格编辑器)
"""
from __future__ import annotations
from typing import List, Optional, Dict
from pathlib import Path
import webbrowser

from PySide6.QtCore import Qt, Signal, QSize, QUrl
from PySide6.QtGui import QCursor, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QStackedWidget, QLineEdit, QPlainTextEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QFileDialog, QListWidget,
    QListWidgetItem, QMessageBox, QInputDialog, QSizePolicy, QSplitter,
    QApplication
)

from .theme import C
from .widgets import Hline, ThumbLabel, ToolbarButton, field_label, section_header
from .models import (
    Project, Character, Scene, Prop, Episode, Shot,
    dict_to_dataclass,
)
from . import storage as ST
from .ui_dialogs import NewEpisodeDialog


SHOT_SIZE_OPTIONS = ["远景", "全景", "中景", "近景", "特写", "大特写", "过肩", "反打"]
CAMERA_MOVE_OPTIONS = ["固定", "推", "拉", "摇", "移", "跟", "旋转", "俯仰", "升降", "手持"]


def _open_url(url: str):
    """系统浏览器打开 URL。"""
    try: QDesktopServices.openUrl(QUrl(url))
    except Exception:
        try: webbrowser.open(url)
        except Exception: pass


def _copy_and_open(text: str, backend_id: str) -> str:
    """复制 prompt + 打开对应 backend URL。返回 backend 名(用于日志)。"""
    QApplication.clipboard().setText(text)
    b = ST.get_backend(backend_id)
    if b and b.url:
        _open_url(b.url)
        return b.name
    return backend_id


class EditorPanel(QFrame):
    """中栏容器。"""
    log = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.current_pid: Optional[str] = None
        self.current_tab: str = "overview"

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.empty   = EmptyView()
        self.over    = OverviewView(self)
        self.chars   = CharactersView(self)
        self.scenes  = ScenesView(self)
        self.props   = PropsView(self)
        self.eps     = EpisodesView(self)

        for w in (self.empty, self.over, self.chars, self.scenes, self.props, self.eps):
            self.stack.addWidget(w)
            if hasattr(w, "log"):
                try: w.log.connect(self.log)
                except Exception: pass

        self.stack.setCurrentWidget(self.empty)

    def set_context(self, pid: Optional[str], tab: str):
        self.current_pid = pid
        self.current_tab = tab
        if not pid:
            self.stack.setCurrentWidget(self.empty)
            return
        mapping = {
            "overview":   self.over,
            "characters": self.chars,
            "scenes":     self.scenes,
            "props":      self.props,
            "episodes":   self.eps,
        }
        target = mapping.get(tab, self.over)
        target.load(pid)
        self.stack.setCurrentWidget(target)


# =========================================================================
class EmptyView(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("PanelAlt")
        l = QVBoxLayout(self); l.setAlignment(Qt.AlignCenter)
        icon = QLabel("🎬"); icon.setStyleSheet("font-size: 64px;"); icon.setAlignment(Qt.AlignCenter)
        t = QLabel("没有选中项目")
        t.setStyleSheet(f"color: {C['ink']}; font-size: 18px; font-weight: 500; margin-top: 12px;")
        t.setAlignment(Qt.AlignCenter)
        d = QLabel("在左侧选一个项目,或点「＋ 新建项目」开始")
        d.setStyleSheet(f"color: {C['muted']}; font-size: 13px; margin-top: 4px;")
        d.setAlignment(Qt.AlignCenter)
        l.addWidget(icon); l.addWidget(t); l.addWidget(d)


# =========================================================================
class OverviewView(QFrame):
    log = Signal(str)

    def __init__(self, owner):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.owner = owner
        self.pid: Optional[str] = None

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        wrap = QWidget(); self.body = QVBoxLayout(wrap)
        self.body.setContentsMargins(36, 28, 36, 28); self.body.setSpacing(20)
        scroll.setWidget(wrap)
        ll = QVBoxLayout(self); ll.setContentsMargins(0,0,0,0); ll.addWidget(scroll)

    def load(self, pid: str):
        self.pid = pid
        while self.body.count():
            it = self.body.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        p = next((x for x in ST.list_projects() if x.id == pid), None)
        if not p: return

        self.body.addWidget(section_header(p.name, f"{p.style or '未分类'} · {p.aspect_ratio} · {p.target_duration}s · {p.description or ''}"))

        # 统计
        chars = ST.load_characters(pid)
        scenes = ST.load_scenes(pid)
        props = ST.load_props(pid)
        eps = ST.list_episodes(pid)
        total_shots = sum(len(e.shots) for e in eps)
        total_segs = sum(len(e.segments) for e in eps)
        gen_videos = sum(1 for e in eps for s in e.segments if s.generated_video)

        stats_grid = QGridLayout(); stats_grid.setSpacing(12)
        items = [
            ("角色", len(chars), "👤"),
            ("场景", len(scenes), "🏞"),
            ("道具", len(props), "📿"),
            ("集数", len(eps), "🎞"),
            ("分镜总数", total_shots, "🎬"),
            ("视频片段", f"{gen_videos}/{total_segs}", "🎥"),
        ]
        for i, (label, value, icon) in enumerate(items):
            card = QFrame(); card.setObjectName("Card")
            cl = QVBoxLayout(card); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(2)
            top = QHBoxLayout()
            ic = QLabel(icon); ic.setStyleSheet("font-size: 18px;")
            top.addWidget(ic); top.addStretch()
            lb = QLabel(label); lb.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
            top.addWidget(lb)
            cl.addLayout(top)
            v = QLabel(str(value))
            v.setStyleSheet(f"font-family: 'Fraunces', serif; font-size: 28px; font-weight: 500; color: {C['ink']};")
            cl.addWidget(v)
            stats_grid.addWidget(card, i // 3, i % 3)
        self.body.addLayout(stats_grid)

        # 简介区
        if p.description:
            sec = QLabel("简介"); sec.setObjectName("FieldLabel")
            self.body.addWidget(sec)
            desc = QLabel(p.description); desc.setWordWrap(True)
            desc.setStyleSheet(f"color: {C['ink_soft']}; font-size: 13px; line-height: 1.6;")
            self.body.addWidget(desc)

        # 建议
        tip_card = QFrame(); tip_card.setObjectName("CardAccent")
        tl = QVBoxLayout(tip_card); tl.setContentsMargins(16, 14, 16, 14); tl.setSpacing(4)
        tt = QLabel("💡 建议下一步")
        tt.setStyleSheet(f"color: {C['accent']}; font-weight: 500; font-size: 13px;")
        tl.addWidget(tt)
        suggestions = []
        if not chars: suggestions.append("1. 在「角色库」建立主角形象(用即梦生三视图)")
        elif not scenes: suggestions.append("2. 在「场景库」录入主要场景的固定描述")
        elif not eps: suggestions.append("3. 在「分镜表」新建第一集,开始写分镜")
        elif total_shots == 0: suggestions.append("3. 给第一集添加分镜(每镜 6 维度 + 衔接锚点)")
        else: suggestions.append("4. 把分镜组装成 10s 视频片段,准备生成")
        for s in suggestions:
            l = QLabel(s); l.setStyleSheet(f"color: {C['ink_soft']}; font-size: 12px;")
            tl.addWidget(l)
        self.body.addWidget(tip_card)

        self.body.addStretch()


# =========================================================================
class _AssetGridView(QFrame):
    """通用的"角色/场景/道具卡片网格"基类。"""
    log = Signal(str)

    NAME = "asset"
    ICON = "📁"
    PLACEHOLDER = "无参考图"

    def __init__(self, owner):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.owner = owner
        self.pid: Optional[str] = None
        self.items: list = []
        self.selected_id: Optional[str] = None

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Toolbar
        tb = QFrame(); tb.setObjectName("Panel")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(28, 16, 28, 14); tbl.setSpacing(10)
        self.title_lbl = QLabel(self.NAME); self.title_lbl.setObjectName("H2")
        tbl.addWidget(self.title_lbl)
        tbl.addStretch()
        self.add_btn = QPushButton(f"＋ 新建{self.NAME}"); self.add_btn.setObjectName("Primary")
        self.add_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.add_btn.clicked.connect(self._on_add)
        tbl.addWidget(self.add_btn)
        root.addWidget(tb); root.addWidget(Hline())

        # 主体:左网格 + 右详情(可折叠)
        self.splitter = QSplitter(Qt.Horizontal)
        # 左
        self.grid_scroll = QScrollArea(); self.grid_scroll.setWidgetResizable(True); self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_holder = QWidget()
        self.grid_layout = QGridLayout(self.grid_holder)
        self.grid_layout.setContentsMargins(28, 18, 28, 28); self.grid_layout.setSpacing(14)
        self.grid_holder.setStyleSheet(f"background: {C['surface_alt']};")
        self.grid_scroll.setWidget(self.grid_holder)
        self.splitter.addWidget(self.grid_scroll)

        # 右 - 详情
        self.detail = QFrame(); self.detail.setObjectName("Panel")
        self.detail.setMinimumWidth(360)
        self.detail_layout = QVBoxLayout(self.detail)
        self.detail_layout.setContentsMargins(24, 20, 24, 20); self.detail_layout.setSpacing(10)
        self.splitter.addWidget(self.detail)
        self.splitter.setSizes([700, 400])

        root.addWidget(self.splitter, 1)
        self._render_detail(None)

    def load(self, pid: str):
        self.pid = pid
        self.items = self._fetch()
        self._render_grid()
        self._render_detail(None)

    # subclass override
    def _fetch(self) -> list: return []
    def _save(self): pass
    def _new_item(self): pass
    def _render_detail(self, item): pass
    def _card_subtitle(self, item) -> str: return ""

    def _render_grid(self):
        while self.grid_layout.count():
            it = self.grid_layout.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        if not self.items:
            empty = QLabel(f"还没有{self.NAME}\n点右上「＋ 新建{self.NAME}」开始")
            empty.setStyleSheet(f"color: {C['muted']}; font-size: 13px; padding: 60px 0;")
            empty.setAlignment(Qt.AlignCenter)
            self.grid_layout.addWidget(empty, 0, 0, 1, 3)
            return

        cols = 3
        for i, item in enumerate(self.items):
            card = self._make_card(item)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        # filler to push to top
        self.grid_layout.setRowStretch((len(self.items) // cols) + 1, 1)

    def _make_card(self, item) -> QFrame:
        card = QFrame()
        selected = item.id == self.selected_id
        card.setObjectName("CardSelected" if selected else "Card")
        card.setCursor(QCursor(Qt.PointingHandCursor))
        card.setFixedHeight(220)

        l = QVBoxLayout(card); l.setContentsMargins(10, 10, 10, 10); l.setSpacing(8)

        thumb = ThumbLabel(size=(220, 130), placeholder_text=self.PLACEHOLDER)
        if item.reference_image:
            p = ST.asset_full_path(self.pid, item.reference_image)
            thumb.set_image(p)
        l.addWidget(thumb, 0, Qt.AlignCenter)

        name = QLabel(getattr(item, "name", "") or "未命名")
        name.setStyleSheet(f"color: {C['ink']}; font-weight: 500; font-size: 13px;")
        l.addWidget(name)

        sub = self._card_subtitle(item)
        if sub:
            s = QLabel(sub); s.setStyleSheet(f"color: {C['muted']}; font-size: 10.5px;")
            l.addWidget(s)
        l.addStretch()

        card.mousePressEvent = lambda e, i=item: self._select(i.id)
        return card

    def _select(self, item_id: str):
        self.selected_id = item_id
        self._render_grid()
        item = next((x for x in self.items if x.id == item_id), None)
        self._render_detail(item)

    def _on_add(self):
        if not self.pid: return
        new = self._new_item()
        if new:
            self.items.append(new)
            self._save()
            self._select(new.id)
            self.log.emit(f"新增{self.NAME}")

    def _on_delete(self, item_id: str):
        ans = QMessageBox.question(self, "删除", f"确定删除此{self.NAME}?",
                                   QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.items = [x for x in self.items if x.id != item_id]
        self.selected_id = None
        self._save(); self._render_grid(); self._render_detail(None)
        self.log.emit(f"删除{self.NAME}")

    def _import_image_for(self, item):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择参考图", "",
            "图片 (*.png *.jpg *.jpeg *.webp);;所有 (*.*)"
        )
        if not path: return
        rel = ST.import_asset(self.pid, Path(path))
        item.reference_image = rel
        self._save()
        self._render_grid()
        self._render_detail(item)
        self.log.emit(f"导入参考图: {rel}")

    def _clear_detail(self):
        while self.detail_layout.count():
            it = self.detail_layout.takeAt(0); w = it.widget()
            if w: w.deleteLater()


# =========================================================================
class CharactersView(_AssetGridView):
    NAME = "角色"
    ICON = "👤"
    PLACEHOLDER = "暂无角色图"

    def _fetch(self): return ST.load_characters(self.pid)
    def _save(self): ST.save_characters(self.pid, self.items)
    def _new_item(self):
        name, ok = QInputDialog.getText(self, "新建角色", "角色名:")
        if not ok or not name.strip(): return None
        placeholder = f"{{{{Image {len(self.items) + 1}}}}}"
        return Character(project_id=self.pid, name=name.strip(), placeholder=placeholder)
    def _card_subtitle(self, c: Character) -> str:
        parts = [c.role]
        if c.age: parts.append(c.age)
        if c.placeholder: parts.append(c.placeholder)
        return " · ".join(filter(None, parts))

    def _render_detail(self, c: Optional[Character]):
        self._clear_detail()
        if not c:
            tip = QLabel("点左侧角色卡查看详情")
            tip.setStyleSheet(f"color: {C['muted']};"); tip.setAlignment(Qt.AlignCenter)
            self.detail_layout.addWidget(tip); self.detail_layout.addStretch()
            return

        # 顶部:头像 + 名字 + 操作
        top = QHBoxLayout()
        thumb = ThumbLabel((100, 100), "无图")
        if c.reference_image:
            thumb.set_image(ST.asset_full_path(self.pid, c.reference_image))
        thumb.clicked.connect(lambda: self._import_image_for(c))
        top.addWidget(thumb)

        name_box = QVBoxLayout(); name_box.setSpacing(4)
        name_lbl = QLabel(c.name); name_lbl.setStyleSheet(f"font-size: 16px; font-weight: 500;")
        name_box.addWidget(name_lbl)
        ph = QLabel(c.placeholder or "(无 placeholder)")
        ph.setStyleSheet(f"color: {C['accent']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        name_box.addWidget(ph)
        upload = QLabel("点击头像更换 ↑")
        upload.setStyleSheet(f"color: {C['muted']}; font-size: 10px;")
        name_box.addWidget(upload)
        name_box.addStretch()
        top.addLayout(name_box, 1)

        del_btn = QPushButton("🗑"); del_btn.setObjectName("IconOnly")
        del_btn.clicked.connect(lambda: self._on_delete(c.id))
        top.addWidget(del_btn, 0, Qt.AlignTop)
        self.detail_layout.addLayout(top)
        self.detail_layout.addWidget(Hline(soft=True))

        # Form
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        form_wrap = QWidget(); form = QVBoxLayout(form_wrap)
        form.setContentsMargins(0, 4, 0, 4); form.setSpacing(8)

        def add_field(label, value, attr, multiline=False, placeholder=""):
            form.addWidget(field_label(label))
            if multiline:
                w = QPlainTextEdit(); w.setPlainText(value or ""); w.setFixedHeight(60)
            else:
                w = QLineEdit(); w.setText(value or "")
            if placeholder: w.setPlaceholderText(placeholder)
            def _on_change():
                txt = w.toPlainText() if multiline else w.text()
                setattr(c, attr, txt)
                self._save()
            if multiline:
                w.textChanged.connect(_on_change)
            else:
                w.editingFinished.connect(_on_change)
            form.addWidget(w)

        # 基本
        add_field("姓名", c.name, "name")
        # role / gender / age 在一行
        row = QHBoxLayout(); row.setSpacing(8)
        for label, attr, vals in [
            ("角色定位", "role", ["主角", "配角", "反派", "群演"]),
            ("性别", "gender", ["男", "女", "其他"]),
        ]:
            box = QVBoxLayout(); box.setSpacing(2)
            box.addWidget(field_label(label))
            cb = QComboBox(); cb.addItems(vals); cb.setEditable(True)
            current = getattr(c, attr) or ""
            if current and current not in vals:
                cb.addItem(current)
            cb.setCurrentText(current)
            cb.currentTextChanged.connect(lambda v, a=attr: (setattr(c, a, v), self._save()))
            box.addWidget(cb)
            row.addLayout(box, 1)
        age_box = QVBoxLayout(); age_box.setSpacing(2)
        age_box.addWidget(field_label("年龄"))
        age_w = QLineEdit(); age_w.setText(c.age); age_w.setPlaceholderText("例:25岁")
        age_w.editingFinished.connect(lambda: (setattr(c, "age", age_w.text()), self._save()))
        age_box.addWidget(age_w)
        row.addLayout(age_box, 1)
        form.addLayout(row)

        # 风格
        add_field("视觉风格", c.visual_style, "visual_style",
                  placeholder="2D动画风格 / 超写实仿真人风格 / 3D超写实风格")

        # 结构化五官
        form.addSpacing(8)
        sub = QLabel("【结构化五官】(锁定一致性)")
        sub.setStyleSheet(f"color: {C['muted']}; font-size: 11px; font-weight: 500;")
        form.addWidget(sub)
        for lbl, attr in [
            ("脸型 face_shape", "face_shape"),
            ("眼睛 eye_details", "eye_details"),
            ("鼻子 nose_shape", "nose_shape"),
            ("嘴型 lip_shape", "lip_shape"),
            ("眉形 eyebrow_style", "eyebrow_style"),
            ("下颌 jawline", "jawline"),
            ("皮肤 skin_details", "skin_details"),
            ("头发 hair", "hair"),
            ("体态 body", "body"),
        ]:
            add_field(lbl, getattr(c, attr), attr)

        # 备注
        form.addSpacing(8)
        add_field("备注", c.notes, "notes", multiline=True)

        # 复制 JSON / 用 GPT 生成
        actions_row = QHBoxLayout(); actions_row.setSpacing(6)
        copy_btn = QPushButton("📋 复制 JSON")
        copy_btn.setCursor(QCursor(Qt.PointingHandCursor))
        copy_btn.setToolTip("复制结构化 JSON 到剪贴板")
        copy_btn.clicked.connect(lambda: self._copy_json(c))
        actions_row.addWidget(copy_btn)

        gen_btn = QPushButton("🤖 用 GPT 生成三视图")
        gen_btn.setObjectName("Accent")
        gen_btn.setCursor(QCursor(Qt.PointingHandCursor))
        gen_btn.setToolTip("复制三视图 prompt → 打开 GPT 镜像站(粘贴即可生成)")
        gen_btn.clicked.connect(lambda: self._gen_triview(c))
        actions_row.addWidget(gen_btn)
        form.addLayout(actions_row)

        form.addStretch()
        scroll.setWidget(form_wrap)
        self.detail_layout.addWidget(scroll, 1)

    def _copy_json(self, c: Character):
        import json
        data = {
            "face_shape": c.face_shape, "eye_details": c.eye_details,
            "nose_shape": c.nose_shape, "lip_shape": c.lip_shape,
            "eyebrow_style": c.eyebrow_style, "jawline": c.jawline,
            "skin_details": c.skin_details, "style_lock": c.style_lock,
        }
        QApplication.clipboard().setText(json.dumps(data, ensure_ascii=False, indent=2))
        self.log.emit(f"已复制 {c.name} 的结构化 JSON 到剪贴板")

    def _gen_triview(self, c: Character):
        """生成角色三视图卡 - 拼完整 prompt 并打开 GPT 镜像站。"""
        from .prompts import get_template, render_template
        import json
        struct = json.dumps({
            "face_shape": c.face_shape, "eye_details": c.eye_details,
            "nose_shape": c.nose_shape, "lip_shape": c.lip_shape,
            "eyebrow_style": c.eyebrow_style, "jawline": c.jawline,
            "skin_details": c.skin_details, "style_lock": c.style_lock,
            "hair": c.hair, "body": c.body,
        }, ensure_ascii=False, indent=2)
        tpl = get_template("tpl-char-001")
        if tpl:
            header = render_template(
                tpl,
                style=c.visual_style or "2D动画风格",
                name=c.name,
                gender=c.gender or "未指定",
                age=c.age or "成年",
            )
        else:
            header = f"{c.visual_style or '2D动画风格'}。生成角色 {c.name} 的三视图。"
        full = f"{header}\n\n**结构化面部数据:**\n\n```json\n{struct}\n```"
        if c.notes:
            full += f"\n\n**备注:** {c.notes}"
        backend = _copy_and_open(full, "gpt-mirror")
        self.log.emit(f"已复制三视图 prompt ({len(full)} 字) + 打开 {backend} → 粘贴生成")


# =========================================================================
class ScenesView(_AssetGridView):
    NAME = "场景"
    ICON = "🏞"
    PLACEHOLDER = "暂无场景图"

    def _fetch(self): return ST.load_scenes(self.pid)
    def _save(self): ST.save_scenes(self.pid, self.items)
    def _new_item(self):
        name, ok = QInputDialog.getText(self, "新建场景", "场景名:")
        if not ok or not name.strip(): return None
        ph = f"{{{{Scene {len(self.items) + 1}}}}}"
        return Scene(project_id=self.pid, name=name.strip(), placeholder=ph)
    def _card_subtitle(self, s: Scene) -> str:
        return s.placeholder or "无 placeholder"

    def _render_detail(self, s: Optional[Scene]):
        self._clear_detail()
        if not s:
            tip = QLabel("点左侧场景卡查看详情")
            tip.setStyleSheet(f"color: {C['muted']};"); tip.setAlignment(Qt.AlignCenter)
            self.detail_layout.addWidget(tip); self.detail_layout.addStretch(); return

        top = QHBoxLayout()
        thumb = ThumbLabel((100, 80), "无图")
        if s.reference_image:
            thumb.set_image(ST.asset_full_path(self.pid, s.reference_image))
        thumb.clicked.connect(lambda: self._import_image_for(s))
        top.addWidget(thumb)
        nb = QVBoxLayout(); nb.setSpacing(4)
        nl = QLabel(s.name); nl.setStyleSheet(f"font-size: 16px; font-weight: 500;")
        nb.addWidget(nl)
        ph = QLabel(s.placeholder)
        ph.setStyleSheet(f"color: {C['accent']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        nb.addWidget(ph)
        nb.addStretch()
        top.addLayout(nb, 1)
        del_btn = QPushButton("🗑"); del_btn.setObjectName("IconOnly")
        del_btn.clicked.connect(lambda: self._on_delete(s.id))
        top.addWidget(del_btn, 0, Qt.AlignTop)
        self.detail_layout.addLayout(top)
        self.detail_layout.addWidget(Hline(soft=True))

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        fw = QWidget(); form = QVBoxLayout(fw); form.setContentsMargins(0, 4, 0, 4); form.setSpacing(8)

        def add(lbl, val, attr, multiline=False, ph=""):
            form.addWidget(field_label(lbl))
            if multiline:
                w = QPlainTextEdit(); w.setPlainText(val or ""); w.setFixedHeight(70)
            else:
                w = QLineEdit(); w.setText(val or "")
            if ph: w.setPlaceholderText(ph)
            def _ch():
                t = w.toPlainText() if multiline else w.text()
                setattr(s, attr, t); self._save()
            if multiline: w.textChanged.connect(_ch)
            else: w.editingFinished.connect(_ch)
            form.addWidget(w)

        add("场景名", s.name, "name")
        add("画面比例", s.aspect_ratio, "aspect_ratio", ph="16:9 / 9:16")
        add("视觉风格", s.visual_style, "visual_style", ph="3D超写实风格")

        sub = QLabel("【固定描述】(用于跨镜一致性)")
        sub.setStyleSheet(f"color: {C['muted']}; font-size: 11px; font-weight: 500; margin-top: 6px;")
        form.addWidget(sub)

        add("整体描述 asset_description", s.asset_description, "asset_description", multiline=True,
            ph="3D超写实风格。废弃矿坑内部,岩壁粗糙呈灰黑色...")
        add("固定环境 fixed_environment", s.fixed_environment, "fixed_environment", multiline=True,
            ph="左侧岩壁有一处塌陷碎石堆,右侧岩壁固定三根朽木支撑柱...")
        add("固定光照 fixed_lighting", s.fixed_lighting, "fixed_lighting", multiline=True,
            ph="主光源来自岩壁蓝色荧光矿物,冷色调,低照度...")
        add("固定背景 fixed_background", s.fixed_background, "fixed_background", multiline=True,
            ph="矿道呈弯曲延伸状,尽头处有微弱洞口透光...")

        actions_row = QHBoxLayout(); actions_row.setSpacing(6)
        copy_btn = QPushButton("📋 复制 JSON")
        copy_btn.clicked.connect(lambda: self._copy_json(s))
        actions_row.addWidget(copy_btn)

        gen_btn = QPushButton("🤖 用 GPT 生成场景图")
        gen_btn.setObjectName("Accent")
        gen_btn.setCursor(QCursor(Qt.PointingHandCursor))
        gen_btn.setToolTip("复制场景 prompt → 打开 GPT 镜像站")
        gen_btn.clicked.connect(lambda: self._gen_scene(s))
        actions_row.addWidget(gen_btn)
        form.addLayout(actions_row)

        form.addStretch()
        scroll.setWidget(fw)
        self.detail_layout.addWidget(scroll, 1)

    def _copy_json(self, s: Scene):
        import json
        data = {
            "Aspect_Ratio": s.aspect_ratio,
            "Asset_Description": s.asset_description,
            "Scene_Fixed_Environment": s.fixed_environment,
            "Scene_Fixed_Lighting": s.fixed_lighting,
            "Scene_Fixed_Background": s.fixed_background,
        }
        QApplication.clipboard().setText(json.dumps(data, ensure_ascii=False, indent=2))
        self.log.emit(f"已复制场景「{s.name}」JSON")

    def _gen_scene(self, s: Scene):
        from .prompts import get_template, render_template
        tpl = get_template("tpl-scene-001")
        if tpl:
            body = render_template(
                tpl,
                aspect_ratio=s.aspect_ratio or "16:9",
                asset_description=s.asset_description,
                fixed_environment=s.fixed_environment,
                fixed_lighting=s.fixed_lighting,
                fixed_background=s.fixed_background,
            )
        else:
            body = s.asset_description
        full = (
            f"{s.visual_style or '3D超写实风格'}。生成场景「{s.name}」的环境概念图,"
            f"无人物,纯环境,比例 {s.aspect_ratio}。\n\n"
            f"场景参数:\n```json\n{body}\n```\n\n"
            f"画质要求:8K 超高清,电影级光影,材质细节清晰。"
        )
        backend = _copy_and_open(full, "gpt-mirror")
        self.log.emit(f"已复制场景 prompt + 打开 {backend}")


# =========================================================================
class PropsView(_AssetGridView):
    NAME = "道具"
    ICON = "📿"
    PLACEHOLDER = "暂无道具图"

    def _fetch(self): return ST.load_props(self.pid)
    def _save(self): ST.save_props(self.pid, self.items)
    def _new_item(self):
        name, ok = QInputDialog.getText(self, "新建道具", "道具名:")
        if not ok or not name.strip(): return None
        ph = f"{{{{Prop {len(self.items) + 1}}}}}"
        return Prop(project_id=self.pid, name=name.strip(), placeholder=ph)
    def _card_subtitle(self, p: Prop) -> str:
        return p.placeholder

    def _render_detail(self, p: Optional[Prop]):
        self._clear_detail()
        if not p:
            tip = QLabel("点左侧道具卡查看详情")
            tip.setStyleSheet(f"color: {C['muted']};"); tip.setAlignment(Qt.AlignCenter)
            self.detail_layout.addWidget(tip); self.detail_layout.addStretch(); return

        top = QHBoxLayout()
        thumb = ThumbLabel((100, 80), "无图")
        if p.reference_image:
            thumb.set_image(ST.asset_full_path(self.pid, p.reference_image))
        thumb.clicked.connect(lambda: self._import_image_for(p))
        top.addWidget(thumb)
        nb = QVBoxLayout(); nb.setSpacing(4)
        nl = QLabel(p.name); nl.setStyleSheet(f"font-size: 16px; font-weight: 500;")
        nb.addWidget(nl)
        ph = QLabel(p.placeholder)
        ph.setStyleSheet(f"color: {C['accent']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        nb.addWidget(ph)
        nb.addStretch()
        top.addLayout(nb, 1)
        del_btn = QPushButton("🗑"); del_btn.setObjectName("IconOnly")
        del_btn.clicked.connect(lambda: self._on_delete(p.id))
        top.addWidget(del_btn, 0, Qt.AlignTop)
        self.detail_layout.addLayout(top)
        self.detail_layout.addWidget(Hline(soft=True))

        form = QVBoxLayout(); form.setSpacing(8)
        form.addWidget(field_label("道具名"))
        nw = QLineEdit(); nw.setText(p.name)
        nw.editingFinished.connect(lambda: (setattr(p, "name", nw.text()), self._save()))
        form.addWidget(nw)

        form.addWidget(field_label("描述"))
        dw = QPlainTextEdit(); dw.setPlainText(p.description); dw.setFixedHeight(80)
        dw.setPlaceholderText("透明蓝色塑料打火机,塑料质感,有使用痕迹...")
        dw.textChanged.connect(lambda: (setattr(p, "description", dw.toPlainText()), self._save()))
        form.addWidget(dw)

        form.addWidget(field_label("Placeholder (引用名)"))
        phw = QLineEdit(); phw.setText(p.placeholder)
        phw.editingFinished.connect(lambda: (setattr(p, "placeholder", phw.text()), self._save()))
        form.addWidget(phw)

        gen_btn = QPushButton("🤖 用 GPT 生成道具图")
        gen_btn.setObjectName("Accent")
        gen_btn.setCursor(QCursor(Qt.PointingHandCursor))
        gen_btn.setToolTip("复制道具 prompt → 打开 GPT 镜像站")
        gen_btn.clicked.connect(lambda: self._gen_prop(p))
        form.addWidget(gen_btn)

        form.addStretch()
        self.detail_layout.addLayout(form)

    def _gen_prop(self, p: Prop):
        full = (
            f"生成道具「{p.name}」的纯白背景参考图,4K 超清,无人物,无背景元素,"
            f"产品级摄影质感。\n\n"
            f"道具描述:{p.description or p.name}\n\n"
            f"要求:细节锐利,材质清晰,无水印,正面 + 透视两个角度并排展示。"
        )
        backend = _copy_and_open(full, "gpt-mirror")
        self.log.emit(f"已复制道具 prompt + 打开 {backend}")


# =========================================================================
class EpisodesView(QFrame):
    """分镜表视图 - 左侧集列表,右侧分镜表。这是中栏的核心。"""
    log = Signal(str)

    def __init__(self, owner):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.owner = owner
        self.pid: Optional[str] = None
        self.episodes: List[Episode] = []
        self.current_ep: Optional[Episode] = None
        self.selected_shot_id: Optional[str] = None

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Toolbar
        tb = QFrame(); tb.setObjectName("Panel")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(28, 16, 28, 14); tbl.setSpacing(10)
        title = QLabel("分镜表"); title.setObjectName("H2")
        tbl.addWidget(title)
        tbl.addStretch()
        new_ep = QPushButton("＋ 新建集"); new_ep.setObjectName("Primary")
        new_ep.setCursor(QCursor(Qt.PointingHandCursor))
        new_ep.clicked.connect(self._on_new_episode)
        tbl.addWidget(new_ep)
        self.add_shot_btn = QPushButton("＋ 新建分镜")
        self.add_shot_btn.setObjectName("Accent")
        self.add_shot_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.add_shot_btn.clicked.connect(self._on_new_shot)
        self.add_shot_btn.setEnabled(False)
        tbl.addWidget(self.add_shot_btn)
        root.addWidget(tb); root.addWidget(Hline())

        # Split: 左集列表 | 中分镜列表 | 右分镜详情
        self.splitter = QSplitter(Qt.Horizontal)

        # 左:集列表
        self.ep_list = QListWidget()
        self.ep_list.setFixedWidth(180)
        self.ep_list.setStyleSheet(f"background: {C['surface_alt']}; border: none; padding: 8px;")
        self.ep_list.currentItemChanged.connect(self._on_ep_changed)
        self.splitter.addWidget(self.ep_list)

        # 中:分镜列表(每行一镜的紧凑展示)
        self.shot_scroll = QScrollArea(); self.shot_scroll.setWidgetResizable(True); self.shot_scroll.setFrameShape(QFrame.NoFrame)
        self.shot_holder = QWidget()
        self.shot_layout = QVBoxLayout(self.shot_holder)
        self.shot_layout.setContentsMargins(16, 14, 16, 14); self.shot_layout.setSpacing(8)
        self.shot_holder.setStyleSheet(f"background: {C['surface_alt']};")
        self.shot_scroll.setWidget(self.shot_holder)
        self.splitter.addWidget(self.shot_scroll)

        # 右:分镜详情编辑器
        self.shot_detail = QFrame(); self.shot_detail.setObjectName("Panel")
        self.shot_detail_layout = QVBoxLayout(self.shot_detail)
        self.shot_detail_layout.setContentsMargins(24, 20, 24, 20); self.shot_detail_layout.setSpacing(0)
        self.splitter.addWidget(self.shot_detail)

        self.splitter.setSizes([180, 380, 440])
        root.addWidget(self.splitter, 1)

        self._render_shot_detail(None)

    def load(self, pid: str):
        self.pid = pid
        self.episodes = ST.list_episodes(pid)
        self.ep_list.blockSignals(True)
        self.ep_list.clear()
        for e in self.episodes:
            it = QListWidgetItem(f"第 {e.number} 集 · {e.title or '未命名'}")
            it.setData(Qt.UserRole, e.id)
            self.ep_list.addItem(it)
        self.ep_list.blockSignals(False)
        if self.episodes:
            self.ep_list.setCurrentRow(0)
        else:
            self.current_ep = None
            self.add_shot_btn.setEnabled(False)
            self._render_shots()

    def _on_ep_changed(self, current, previous):
        if not current:
            self.current_ep = None
            self.add_shot_btn.setEnabled(False)
            self._render_shots(); return
        eid = current.data(Qt.UserRole)
        self.current_ep = next((e for e in self.episodes if e.id == eid), None)
        self.add_shot_btn.setEnabled(self.current_ep is not None)
        self.selected_shot_id = None
        self._render_shots()
        self._render_shot_detail(None)

    def _on_new_episode(self):
        if not self.pid: return
        next_n = max([e.number for e in self.episodes], default=0) + 1
        dlg = NewEpisodeDialog(self, next_n)
        if dlg.exec() == dlg.DialogCode.Accepted:
            ep = dlg.build_episode(self.pid)
            ST.save_episode(self.pid, ep)
            self.episodes.append(ep)
            self.load(self.pid)  # reload
            # 选中新建那条
            for i in range(self.ep_list.count()):
                if self.ep_list.item(i).data(Qt.UserRole) == ep.id:
                    self.ep_list.setCurrentRow(i); break

    def _on_new_shot(self):
        if not self.current_ep: return
        next_n = max([s.number for s in self.current_ep.shots], default=0) + 1
        # 自动继承上一镜的衔接锚点作为本镜起始描述
        prev = self.current_ep.shots[-1] if self.current_ep.shots else None
        start_t = 0.0
        if prev:
            start_t = prev.start_time + prev.duration
        shot = Shot(episode_id=self.current_ep.id, number=next_n,
                    start_time=start_t, duration=2.0)
        if prev and prev.transition_anchor:
            shot.action = f"承接上镜:{prev.transition_anchor}"
        self.current_ep.shots.append(shot)
        ST.save_episode(self.pid, self.current_ep)
        self.selected_shot_id = shot.id
        self._render_shots()
        self._render_shot_detail(shot)
        self.log.emit(f"新增分镜 #{shot.number}")

    def _render_shots(self):
        while self.shot_layout.count():
            it = self.shot_layout.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        if not self.current_ep:
            empty = QLabel("先在左侧选/新建一集")
            empty.setStyleSheet(f"color: {C['muted']}; padding: 40px 0;")
            empty.setAlignment(Qt.AlignCenter)
            self.shot_layout.addWidget(empty); return

        # 密度统计条
        n = len(self.current_ep.shots)
        total_dur = sum(s.duration for s in self.current_ep.shots)
        segments_needed = int(-(-total_dur // 10))   # ceil
        avg_per_seg = (n / segments_needed) if segments_needed else 0

        stats = QFrame(); stats.setObjectName("Card")
        sl = QHBoxLayout(stats); sl.setContentsMargins(12, 8, 12, 8); sl.setSpacing(10)

        n_lbl = QLabel(f"<b>{n}</b> 镜")
        n_lbl.setStyleSheet(f"color: {C['ink']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        sl.addWidget(n_lbl)

        sl.addWidget(QLabel("·"))
        dur_lbl = QLabel(f"<b>{total_dur:.1f}</b>s")
        dur_lbl.setStyleSheet(f"color: {C['ink']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        sl.addWidget(dur_lbl)

        sl.addWidget(QLabel("·"))
        seg_lbl = QLabel(f"<b>{segments_needed}</b> 个 10s 段")
        seg_lbl.setStyleSheet(f"color: {C['ink']}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        sl.addWidget(seg_lbl)

        sl.addStretch()

        # 密度警告(基于平均 镜/段)
        if n == 0:
            badge_txt, badge_color = "空集", C['muted']
        elif avg_per_seg <= 5:
            badge_txt, badge_color = f"🟢 {avg_per_seg:.1f} 镜/段 节奏 OK", C['online']
        elif avg_per_seg == 6:
            badge_txt, badge_color = f"🟡 {avg_per_seg:.1f} 镜/段 紧凑", C['warning']
        else:
            badge_txt, badge_color = f"🔴 {avg_per_seg:.1f} 镜/段 太赶,建议拆", C['danger']
        badge = QLabel(badge_txt)
        badge.setStyleSheet(f"""
            color: {badge_color}; font-family: 'JetBrains Mono', monospace;
            font-size: 10px; font-weight: 500;
        """)
        sl.addWidget(badge)

        self.shot_layout.addWidget(stats)

        if not self.current_ep.shots:
            empty = QLabel(f"第{self.current_ep.number}集还没有分镜\n点上面「＋ 新建分镜」")
            empty.setStyleSheet(f"color: {C['muted']}; padding: 60px 0;")
            empty.setAlignment(Qt.AlignCenter)
            self.shot_layout.addWidget(empty); return

        for s in self.current_ep.shots:
            card = self._make_shot_card(s)
            self.shot_layout.addWidget(card)
        self.shot_layout.addStretch()

    def _make_shot_card(self, s: Shot) -> QFrame:
        selected = s.id == self.selected_shot_id
        card = QFrame()
        card.setObjectName("CardSelected" if selected else "Card")
        card.setCursor(QCursor(Qt.PointingHandCursor))

        l = QHBoxLayout(card); l.setContentsMargins(12, 10, 12, 10); l.setSpacing(10)

        # 时间码
        time_lbl = QLabel(f"#{s.number}")
        time_lbl.setStyleSheet(f"""
            background: {C['ink']}; color: white;
            font-family: 'JetBrains Mono', monospace; font-size: 11px;
            padding: 2px 8px; border-radius: 4px; min-width: 26px;
        """)
        time_lbl.setAlignment(Qt.AlignCenter)
        l.addWidget(time_lbl)

        body = QVBoxLayout(); body.setSpacing(2)
        # 头行: 景别 · 运镜 · 时长
        meta = QHBoxLayout(); meta.setSpacing(4)
        for txt, fg in [
            (s.shot_size or "—", C["accent"]),
            (s.camera_movement or "—", C["info"]),
            (f"{s.duration}s", C["muted"]),
            (f"{s.start_time:.1f}s →", C["muted"]),
        ]:
            t = QLabel(txt)
            t.setStyleSheet(f"""
                color: {fg}; font-size: 10.5px;
                background: {C['surface_alt']};
                padding: 1px 6px; border-radius: 3px;
                font-family: 'JetBrains Mono', monospace;
            """)
            meta.addWidget(t)
        meta.addStretch()
        body.addLayout(meta)

        # 第二行:动作摘要
        action_text = s.action[:60] + ("…" if len(s.action) > 60 else "")
        if not action_text: action_text = "(待填动作)"
        ac = QLabel(action_text)
        ac.setStyleSheet(f"color: {C['ink']}; font-size: 12px;")
        ac.setWordWrap(True)
        body.addWidget(ac)

        # 第三行:台词(有的话)
        if s.dialogue:
            d = QLabel(f"💬 {s.dialogue[:40]}")
            d.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
            body.addWidget(d)

        l.addLayout(body, 1)

        # 状态/工具
        right = QVBoxLayout(); right.setSpacing(4); right.setAlignment(Qt.AlignTop)
        if s.generated_image:
            mark = QLabel("🖼"); mark.setToolTip("已有参考图")
            right.addWidget(mark)
        if s.generated_video:
            mark = QLabel("🎬"); mark.setToolTip("已有视频")
            right.addWidget(mark)
        l.addLayout(right)

        card.mousePressEvent = lambda e, sh=s: self._select_shot(sh.id)
        return card

    def _select_shot(self, shot_id: str):
        self.selected_shot_id = shot_id
        shot = next((s for s in self.current_ep.shots if s.id == shot_id), None)
        self._render_shots()
        self._render_shot_detail(shot)

    def _render_shot_detail(self, shot: Optional[Shot]):
        # clear
        while self.shot_detail_layout.count():
            it = self.shot_detail_layout.takeAt(0); w = it.widget()
            if w: w.deleteLater()

        if not shot:
            tip = QLabel("选中左侧某镜查看/编辑")
            tip.setStyleSheet(f"color: {C['muted']};")
            tip.setAlignment(Qt.AlignCenter)
            self.shot_detail_layout.addWidget(tip)
            self.shot_detail_layout.addStretch()
            return

        # 头部
        hdr = QHBoxLayout()
        h = QLabel(f"分镜 #{shot.number}")
        h.setStyleSheet(f"font-size: 18px; font-weight: 500;")
        hdr.addWidget(h); hdr.addStretch()
        del_btn = QPushButton("🗑"); del_btn.setObjectName("IconOnly")
        del_btn.setToolTip("删除此镜")
        del_btn.clicked.connect(lambda: self._delete_shot(shot.id))
        hdr.addWidget(del_btn)
        self.shot_detail_layout.addLayout(hdr)
        self.shot_detail_layout.addWidget(Hline(soft=True))

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        body_w = QWidget(); body = QVBoxLayout(body_w)
        body.setContentsMargins(0, 10, 0, 4); body.setSpacing(10)

        def commit():
            if self.current_ep:
                ST.save_episode(self.pid, self.current_ep)

        def add_line_field(label, attr, ph=""):
            body.addWidget(field_label(label))
            w = QLineEdit(); w.setText(getattr(shot, attr) or "")
            if ph: w.setPlaceholderText(ph)
            w.editingFinished.connect(lambda: (setattr(shot, attr, w.text()), commit(), self._render_shots()))
            body.addWidget(w)
            return w

        def add_text_field(label, attr, ph="", h=70):
            body.addWidget(field_label(label))
            w = QPlainTextEdit(); w.setPlainText(getattr(shot, attr) or ""); w.setFixedHeight(h)
            if ph: w.setPlaceholderText(ph)
            w.textChanged.connect(lambda: (setattr(shot, attr, w.toPlainText()), commit(), self._render_shots()))
            body.addWidget(w)
            return w

        # 时间 / 景别 / 运镜 (一行)
        row1 = QHBoxLayout(); row1.setSpacing(8)
        # start
        c1 = QVBoxLayout(); c1.setSpacing(2)
        c1.addWidget(field_label("起始秒"))
        st = QDoubleSpinBox(); st.setRange(0, 600); st.setSingleStep(0.5); st.setValue(shot.start_time)
        st.valueChanged.connect(lambda v: (setattr(shot, "start_time", v), commit(), self._render_shots()))
        c1.addWidget(st); row1.addLayout(c1)
        # dur
        c2 = QVBoxLayout(); c2.setSpacing(2)
        c2.addWidget(field_label("时长秒"))
        du = QDoubleSpinBox(); du.setRange(0.5, 10); du.setSingleStep(0.5); du.setValue(shot.duration)
        du.valueChanged.connect(lambda v: (setattr(shot, "duration", v), commit(), self._render_shots()))
        c2.addWidget(du); row1.addLayout(c2)
        # size
        c3 = QVBoxLayout(); c3.setSpacing(2)
        c3.addWidget(field_label("景别"))
        sz = QComboBox(); sz.addItems(SHOT_SIZE_OPTIONS); sz.setEditable(True)
        if shot.shot_size and shot.shot_size not in SHOT_SIZE_OPTIONS:
            sz.addItem(shot.shot_size)
        sz.setCurrentText(shot.shot_size or "中景")
        sz.currentTextChanged.connect(lambda v: (setattr(shot, "shot_size", v), commit(), self._render_shots()))
        c3.addWidget(sz); row1.addLayout(c3)
        # move
        c4 = QVBoxLayout(); c4.setSpacing(2)
        c4.addWidget(field_label("运镜"))
        mv = QComboBox(); mv.addItems(CAMERA_MOVE_OPTIONS); mv.setEditable(True)
        if shot.camera_movement and shot.camera_movement not in CAMERA_MOVE_OPTIONS:
            mv.addItem(shot.camera_movement)
        mv.setCurrentText(shot.camera_movement or "固定")
        mv.currentTextChanged.connect(lambda v: (setattr(shot, "camera_movement", v), commit(), self._render_shots()))
        c4.addWidget(mv); row1.addLayout(c4)
        body.addLayout(row1)

        # 6 维度
        body.addWidget(Hline(soft=True))
        sec = QLabel("【6 维度 · 蒙哥模板】")
        sec.setStyleSheet(f"color: {C['accent']}; font-weight: 500; font-size: 12px; margin-top: 6px;")
        body.addWidget(sec)

        add_line_field("视觉风格", "visual_style_note", "深色主调,金色烛光重点照亮")
        add_line_field("摄影参数", "camera_params", "50mm f/2.8 ISO 400")
        add_text_field("动作设计", "action", "男性缓慢翻动卷轴,眼神微蹙")
        add_text_field("光影设计", "lighting", "卷轴反光,面部侧光形成阴影")
        add_text_field("音效设计", "sound", "卷轴纸张摩擦声,低沉环境声")

        # 衔接锚点
        body.addWidget(Hline(soft=True))
        body.addWidget(field_label("【衔接锚点】本镜结束姿态(必填!作为下镜起始)"))
        add_text_field("", "transition_anchor", "本镜结束时陆渊低头看左手+紫光最亮", h=50)

        # 台词
        add_text_field("台词 / 对白", "dialogue", "示例:\"两百九十九。\"", h=50)

        # prompts 区
        body.addWidget(Hline(soft=True))
        sec2 = QLabel("【手动 Prompt 覆盖】(留空走自动模板)")
        sec2.setStyleSheet(f"color: {C['muted']}; font-weight: 500; font-size: 11px; margin-top: 4px;")
        body.addWidget(sec2)

        add_text_field("图片 prompt 自定义", "image_prompt_custom", "", h=80)
        add_text_field("视频 prompt 自定义", "video_prompt_custom", "", h=80)

        # 操作按钮
        body.addWidget(Hline(soft=True))
        sec3 = QLabel("【生成】")
        sec3.setStyleSheet(f"color: {C['accent']}; font-weight: 500; font-size: 12px; margin-top: 4px;")
        body.addWidget(sec3)

        # 图片 prompt 行
        img_row = QHBoxLayout(); img_row.setSpacing(6)
        copy_img = QPushButton("📋 复制图 Prompt")
        copy_img.clicked.connect(lambda: self._copy_image_prompt(shot))
        img_row.addWidget(copy_img)
        gen_img = QPushButton("🤖 用 GPT 生图")
        gen_img.setObjectName("Accent")
        gen_img.setToolTip("复制 + 打开 GPT 镜像站")
        gen_img.clicked.connect(lambda: self._gen_shot_image(shot))
        img_row.addWidget(gen_img)
        body.addLayout(img_row)

        # 视频 prompt 行
        vid_row = QHBoxLayout(); vid_row.setSpacing(6)
        copy_vid = QPushButton("📋 复制视频 Prompt")
        copy_vid.clicked.connect(lambda: self._copy_video_prompt(shot))
        vid_row.addWidget(copy_vid)
        gen_vid = QPushButton("🎬 用豆包生视频")
        gen_vid.setObjectName("Accent")
        gen_vid.setToolTip("复制 + 打开豆包(此镜单独生成 ≤10s 视频片段)")
        gen_vid.clicked.connect(lambda: self._gen_shot_video(shot))
        vid_row.addWidget(gen_vid)
        body.addLayout(vid_row)

        # 导入生成结果
        import_row = QHBoxLayout(); import_row.setSpacing(6)
        imp_img = QPushButton("⬇ 导入参考图")
        imp_img.clicked.connect(lambda: self._import_shot_image(shot))
        import_row.addWidget(imp_img)
        imp_vid = QPushButton("⬇ 导入视频")
        imp_vid.clicked.connect(lambda: self._import_shot_video(shot))
        import_row.addWidget(imp_vid)
        body.addLayout(import_row)

        body.addStretch()
        scroll.setWidget(body_w)
        self.shot_detail_layout.addWidget(scroll, 1)

    def _delete_shot(self, sid: str):
        if not self.current_ep: return
        ans = QMessageBox.question(self, "删除分镜", "确定删除此镜?",
                                   QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes: return
        self.current_ep.shots = [s for s in self.current_ep.shots if s.id != sid]
        # 重新编号
        for i, s in enumerate(self.current_ep.shots, start=1):
            s.number = i
        ST.save_episode(self.pid, self.current_ep)
        self.selected_shot_id = None
        self._render_shots(); self._render_shot_detail(None)
        self.log.emit(f"删除分镜")

    def _build_image_prompt(self, shot: Shot) -> str:
        if shot.image_prompt_custom.strip():
            return shot.image_prompt_custom
        chars = ST.load_characters(self.pid)
        scenes = ST.load_scenes(self.pid)
        scene = next((s for s in scenes if s.id == shot.scene_id), None)

        parts = []
        if scene:
            parts.append(scene.visual_style or "3D超写实风格")
            parts.append("。")
        parts.append(f'"主体描述":')
        if shot.character_ids:
            for cid in shot.character_ids:
                c = next((x for x in chars if x.id == cid), None)
                if c and c.placeholder: parts.append(f" {c.placeholder} {c.name}")
        if shot.action: parts.append(f" {shot.action}。")
        parts.append(f' "镜头语言":{shot.shot_size}{shot.camera_movement}。')
        if shot.visual_style_note: parts.append(f' "视觉风格":{shot.visual_style_note}。')
        if shot.camera_params: parts.append(f' "摄影参数":{shot.camera_params}。')
        if shot.lighting: parts.append(f' "环境光影":{shot.lighting}。')
        parts.append(' "画质修饰":8K超高清,电影级质感,无噪点。')
        return "".join(parts)

    # 视频 prompt 末尾固定追加的防御词,排除故事板里的元数据图形混入视频
    NEGATIVE_VIDEO_TAIL = (
        "\n\n【画面排除项】"
        "镜头中不出现摄像机设备、不出现机位标注、不出现红色圆点或编号、"
        "不出现箭头或图示标记、不出现俯视示意图、不出现文字标签;"
        "只生成纯影视画面,故事板里的标注/箭头/编号/机位图视为元数据,不进入画面。"
    )

    def _build_video_prompt(self, shot: Shot) -> str:
        if shot.video_prompt_custom.strip():
            base = shot.video_prompt_custom
        else:
            parts = [self._build_image_prompt(shot), "\n\n"]
            parts.append(f"【动态时间轴动作流】0~{shot.duration}秒:{shot.action}\n")
            if shot.sound:
                parts.append(f"音效参考:{shot.sound}\n")
            if shot.transition_anchor:
                parts.append(f"【衔接说明】:本分镜结束姿态({shot.transition_anchor})"
                             f"为下一分镜的起始姿态,转场叠化{shot.transition_duration}秒。")
            base = "".join(parts)
        return base + self.NEGATIVE_VIDEO_TAIL

    def _copy_image_prompt(self, shot: Shot):
        text = self._build_image_prompt(shot)
        QApplication.clipboard().setText(text)
        self.log.emit(f"已复制分镜 #{shot.number} 的图片 prompt ({len(text)} 字)")

    def _copy_video_prompt(self, shot: Shot):
        text = self._build_video_prompt(shot)
        QApplication.clipboard().setText(text)
        self.log.emit(f"已复制分镜 #{shot.number} 的视频 prompt ({len(text)} 字)")

    def _gen_shot_image(self, shot: Shot):
        text = self._build_image_prompt(shot)
        backend = _copy_and_open(text, "gpt-mirror")
        self.log.emit(f"已复制图 prompt + 打开 {backend} → 粘贴生成参考图")

    def _gen_shot_video(self, shot: Shot):
        text = self._build_video_prompt(shot)
        backend = _copy_and_open(text, "doubao")
        self.log.emit(f"已复制视频 prompt + 打开 {backend} → 粘贴 + 上传参考图生成")

    def _import_shot_image(self, shot: Shot):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择本镜参考图", "",
            "图片 (*.png *.jpg *.jpeg *.webp);;所有 (*.*)"
        )
        if not path: return
        rel = ST.import_asset(self.pid, Path(path), target_name=f"shot-{shot.id}.jpg")
        shot.generated_image = rel
        ST.save_episode(self.pid, self.current_ep)
        self._render_shots(); self._render_shot_detail(shot)
        self.log.emit(f"导入分镜 #{shot.number} 参考图")

    def _import_shot_video(self, shot: Shot):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择本镜视频", "",
            "视频 (*.mp4 *.mov *.webm *.avi);;所有 (*.*)"
        )
        if not path: return
        rel = ST.import_asset(self.pid, Path(path), target_name=f"shot-{shot.id}.mp4")
        shot.generated_video = rel
        ST.save_episode(self.pid, self.current_ep)
        self._render_shots(); self._render_shot_detail(shot)
        self.log.emit(f"导入分镜 #{shot.number} 视频")
