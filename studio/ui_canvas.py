"""
InfiniteCanvas — 节点式工作台。

M5: 资产节点(角色/场景/道具/分镜)+ 自动布局 + 位置持久化
M6: 文本节点 + 生成器节点(画布内直接生图)+ 节点间引用连线
"""
from __future__ import annotations
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import json, math, time

from PySide6.QtCore import Qt, QPointF, QRectF, QSize, Signal, QTimer
from PySide6.QtGui import (
    QPixmap, QPainter, QPen, QBrush, QColor, QFont, QCursor, QAction,
    QPainterPath, QTransform,
)
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsItemGroup, QGraphicsRectItem,
    QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsPathItem,
    QMenu, QMessageBox, QFileDialog, QGraphicsLineItem,
    QSizePolicy, QApplication, QInputDialog,
    QDialog, QDialogButtonBox, QLineEdit, QPlainTextEdit, QComboBox,
    QFormLayout,
)

from .theme import C
from .widgets import Hline
from . import storage as ST
from .models import (
    Character, Scene, Prop, Episode, Shot, CanvasItem, GenerationTask,
    CANVAS_TEXT, CANVAS_GENERATOR, CANVAS_IMAGE, CANVAS_VIDEO,
)


# ==== 节点尺寸常量 ====
NODE_W = 200
NODE_H = 260
NODE_PADDING = 12
NODE_HEADER_H = 30
THUMB_H = 130
RADIUS = 10

# 节点类型 → 上色
KIND_COLORS = {
    "character": "#7c3aed",
    "scene":     "#0d9488",
    "prop":      "#b45309",
    "shot":      "#dc5a3a",
    "segment":   "#1e3a8a",
    "text":      "#fbbf24",
    "generator": "#0369a1",
    "image":     "#15803d",
    "video":     "#be185d",
}


def _rounded_path(x: float, y: float, w: float, h: float,
                  r: float, only_top: bool = False) -> QPainterPath:
    """工具函数 — 圆角矩形 path。"""
    path = QPainterPath()
    if only_top:
        path.moveTo(x, y + h)
        path.lineTo(x, y + r)
        path.quadTo(x, y, x + r, y)
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
        path.lineTo(x + w, y + h)
        path.closeSubpath()
    else:
        path.addRoundedRect(x, y, w, h, r, r)
    return path


# =========================================================================
class _NodeBase(QGraphicsItemGroup):
    """所有节点的基类 — 共享拖动 / 选中描边 / 位置变化通知。"""

    def __init__(self):
        super().__init__()
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self.connections: List["ConnectionLine"] = []   # 引用本节点的所有连线
        self._outline = None

    def add_connection(self, line: "ConnectionLine"):
        self.connections.append(line)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged and self._outline:
            self._outline.setVisible(bool(value))
        if change == QGraphicsItem.ItemPositionHasChanged:
            for line in self.connections:
                line.update_path()
        return super().itemChange(change, value)


# =========================================================================
class AssetNode(_NodeBase):
    """显示项目里的角色 / 场景 / 道具 / 分镜。"""

    def __init__(self, node_id: str, kind: str, title: str, subtitle: str,
                 image_path: Optional[Path], color: str = "#1e3a8a"):
        super().__init__()
        self.node_id = node_id
        self.kind = kind
        self.title = title
        self.subtitle = subtitle

        # 背景
        bg = QGraphicsPathItem(_rounded_path(0, 0, NODE_W, NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#ffffff")))
        bg.setPen(QPen(QColor(C["border_soft"]), 1))
        self.addToGroup(bg)

        # 顶部色条
        header = QGraphicsPathItem(_rounded_path(0, 0, NODE_W, NODE_HEADER_H, RADIUS, only_top=True))
        header.setBrush(QBrush(QColor(color)))
        header.setPen(QPen(Qt.NoPen))
        self.addToGroup(header)

        icon_map = {
            "character": "👤", "scene": "🏞", "prop": "📿",
            "shot": "🎬", "segment": "🎞", "video": "🎥",
        }
        icon = QGraphicsTextItem(icon_map.get(kind, "•"))
        icon.setDefaultTextColor(QColor("white"))
        icon.setFont(QFont("Inter", 13))
        icon.setPos(8, 4)
        self.addToGroup(icon)

        title_item = QGraphicsTextItem(title)
        title_item.setDefaultTextColor(QColor("white"))
        f = QFont("Inter Tight"); f.setPointSize(10); f.setWeight(QFont.DemiBold)
        title_item.setFont(f)
        title_item.setPos(34, 6)
        title_item.setTextWidth(NODE_W - 44)
        self.addToGroup(title_item)

        # 缩略图
        thumb_y = NODE_HEADER_H + NODE_PADDING
        thumb_w = NODE_W - 2 * NODE_PADDING
        if image_path and Path(image_path).exists():
            pm = QPixmap(str(image_path))
            if not pm.isNull():
                pm = pm.scaled(thumb_w, THUMB_H,
                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb = QGraphicsPixmapItem(pm)
                thumb.setPos(NODE_PADDING + max(0, (thumb_w - pm.width()) // 2),
                             thumb_y + max(0, (THUMB_H - pm.height()) // 2))
                self.addToGroup(thumb)
        else:
            ph = QGraphicsPathItem(_rounded_path(
                NODE_PADDING, thumb_y, thumb_w, THUMB_H, 6))
            ph.setBrush(QBrush(QColor(C["surface_alt"])))
            ph.setPen(QPen(QColor(C["border_soft"]), 1))
            self.addToGroup(ph)
            ph_text = QGraphicsTextItem("(无图)")
            ph_text.setDefaultTextColor(QColor(C["muted"]))
            ph_text.setFont(QFont("Inter", 9))
            tr = ph_text.boundingRect()
            ph_text.setPos(NODE_W / 2 - tr.width() / 2,
                          thumb_y + THUMB_H / 2 - tr.height() / 2)
            self.addToGroup(ph_text)

        sub_y = thumb_y + THUMB_H + 10
        sub = QGraphicsTextItem(subtitle)
        sub.setDefaultTextColor(QColor(C["ink_soft"]))
        sub.setFont(QFont("Inter", 9))
        sub.setPos(NODE_PADDING, sub_y)
        sub.setTextWidth(NODE_W - 2 * NODE_PADDING)
        self.addToGroup(sub)

        # 选中描边
        self._outline = QGraphicsPathItem(_rounded_path(-2, -2, NODE_W + 4, NODE_H + 4, RADIUS + 2))
        self._outline.setBrush(QBrush(Qt.NoBrush))
        self._outline.setPen(QPen(QColor(C["accent"]), 2))
        self._outline.setVisible(False)
        self.addToGroup(self._outline)


# =========================================================================
class TextNode(_NodeBase):
    """便利贴样式的文本节点。"""

    NODE_W = 240
    NODE_H = 130

    def __init__(self, canvas_item: CanvasItem):
        super().__init__()
        self.canvas_item = canvas_item
        self.node_id = canvas_item.id
        self.kind = "text"

        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, 8))
        bg.setBrush(QBrush(QColor("#fef3c7")))
        bg.setPen(QPen(QColor("#fbbf24"), 1))
        self.addToGroup(bg)

        ic = QGraphicsTextItem("📝")
        ic.setFont(QFont("Inter", 12))
        ic.setPos(8, 4)
        self.addToGroup(ic)

        self.text_item = QGraphicsTextItem()
        self.text_item.setPlainText(canvas_item.text or "(双击编辑文本)")
        self.text_item.setDefaultTextColor(QColor("#0a0a0a"))
        f = QFont("Inter Tight"); f.setPointSize(10)
        self.text_item.setFont(f)
        self.text_item.setTextWidth(self.NODE_W - 20)
        self.text_item.setPos(10, 28)
        self.addToGroup(self.text_item)

        self._outline = QGraphicsPathItem(_rounded_path(-2, -2, self.NODE_W + 4, self.NODE_H + 4, 10))
        self._outline.setBrush(QBrush(Qt.NoBrush))
        self._outline.setPen(QPen(QColor(C["accent"]), 2))
        self._outline.setVisible(False)
        self.addToGroup(self._outline)

    def set_text(self, text: str):
        self.text_item.setPlainText(text or "(双击编辑文本)")
        self.canvas_item.text = text

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.canvas_item.x = self.scenePos().x()
            self.canvas_item.y = self.scenePos().y()
        return super().itemChange(change, value)


# =========================================================================
class GeneratorNode(_NodeBase):
    """生成器节点。
    状态机:pending(空白)→ queued(蓝)→ running(蓝+动)→ done(绿+图)| failed(红)
    """

    NODE_W = 220
    NODE_H = 240

    def __init__(self, canvas_item: CanvasItem):
        super().__init__()
        self.canvas_item = canvas_item
        self.node_id = canvas_item.id
        self.kind = "generator"
        self._render()

    def _clear_visuals(self):
        for it in list(self.childItems()):
            self.removeFromGroup(it)
            sc = it.scene()
            if sc: sc.removeItem(it)

    def _render(self):
        self._clear_visuals()
        status = self.canvas_item.status

        if status == "done" and self.canvas_item.result_file:
            self._paint_done()
        elif status == "failed":
            self._paint_failed()
        elif status in ("queued", "running"):
            self._paint_running()
        else:
            self._paint_empty()

        self._outline = QGraphicsPathItem(_rounded_path(-2, -2, self.NODE_W + 4, self.NODE_H + 4, RADIUS + 2))
        self._outline.setBrush(QBrush(Qt.NoBrush))
        self._outline.setPen(QPen(QColor(C["accent"]), 2))
        self._outline.setVisible(self.isSelected())
        self.addToGroup(self._outline)

    def _paint_empty(self):
        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#eff6ff")))
        bg.setPen(QPen(QColor(C["info"]), 2, Qt.DashLine))
        self.addToGroup(bg)

        plus = QGraphicsTextItem("+")
        plus.setDefaultTextColor(QColor(C["info"]))
        f = QFont("Inter Tight"); f.setPointSize(48); f.setWeight(QFont.Light)
        plus.setFont(f)
        tr = plus.boundingRect()
        plus.setPos(self.NODE_W / 2 - tr.width() / 2,
                    self.NODE_H / 2 - tr.height() / 2 - 18)
        self.addToGroup(plus)

        hint = QGraphicsTextItem("双击设置 prompt")
        hint.setDefaultTextColor(QColor(C["muted"]))
        hint.setFont(QFont("Inter", 10))
        tr = hint.boundingRect()
        hint.setPos(self.NODE_W / 2 - tr.width() / 2, self.NODE_H - 36)
        self.addToGroup(hint)

    def _paint_running(self):
        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#dbeafe")))
        bg.setPen(QPen(QColor(C["info"]), 2))
        self.addToGroup(bg)

        sp = QGraphicsTextItem("⏳" if self.canvas_item.status == "queued" else "⚡")
        sp.setFont(QFont("Inter", 32))
        tr = sp.boundingRect()
        sp.setPos(self.NODE_W / 2 - tr.width() / 2, 40)
        self.addToGroup(sp)

        st = QGraphicsTextItem("排队中..." if self.canvas_item.status == "queued" else "生成中...")
        st.setDefaultTextColor(QColor(C["info"]))
        f = QFont("Inter Tight"); f.setPointSize(11); f.setWeight(QFont.DemiBold)
        st.setFont(f)
        tr = st.boundingRect()
        st.setPos(self.NODE_W / 2 - tr.width() / 2, 110)
        self.addToGroup(st)

        prev = (self.canvas_item.prompt or "")[:80]
        if len(self.canvas_item.prompt) > 80: prev += "..."
        p = QGraphicsTextItem(prev)
        p.setDefaultTextColor(QColor(C["ink_soft"]))
        p.setFont(QFont("Inter", 9))
        p.setTextWidth(self.NODE_W - 24)
        p.setPos(12, 145)
        self.addToGroup(p)

    def _paint_done(self):
        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#ffffff")))
        bg.setPen(QPen(QColor(C["online"]), 1))
        self.addToGroup(bg)

        header = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, NODE_HEADER_H, RADIUS, only_top=True))
        header.setBrush(QBrush(QColor(C["online"])))
        header.setPen(QPen(Qt.NoPen))
        self.addToGroup(header)

        ic = QGraphicsTextItem("✅" if self.canvas_item.task_type == "image" else "🎬")
        ic.setDefaultTextColor(QColor("white"))
        ic.setFont(QFont("Inter", 12))
        ic.setPos(8, 4)
        self.addToGroup(ic)

        title = QGraphicsTextItem(self.canvas_item.title or "已生成")
        title.setDefaultTextColor(QColor("white"))
        f = QFont("Inter Tight"); f.setPointSize(10); f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setPos(34, 6)
        title.setTextWidth(self.NODE_W - 44)
        self.addToGroup(title)

        img_path = ST.asset_full_path(self.canvas_item.project_id, self.canvas_item.result_file)
        if img_path.exists():
            pm = QPixmap(str(img_path))
            if not pm.isNull():
                tw = self.NODE_W - 24
                th = self.NODE_H - NODE_HEADER_H - 16
                pm = pm.scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb = QGraphicsPixmapItem(pm)
                thumb.setPos(12 + max(0, (tw - pm.width()) // 2),
                            NODE_HEADER_H + 8 + max(0, (th - pm.height()) // 2))
                self.addToGroup(thumb)
                return
        ph = QGraphicsTextItem("(图加载失败)")
        ph.setDefaultTextColor(QColor(C["muted"]))
        ph.setPos(12, NODE_HEADER_H + 30)
        self.addToGroup(ph)

    def _paint_failed(self):
        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#fef2f2")))
        bg.setPen(QPen(QColor(C["danger"]), 2))
        self.addToGroup(bg)
        x = QGraphicsTextItem("❌")
        x.setFont(QFont("Inter", 32))
        tr = x.boundingRect()
        x.setPos(self.NODE_W / 2 - tr.width() / 2, 40)
        self.addToGroup(x)
        msg = QGraphicsTextItem(self.canvas_item.error or "失败")
        msg.setDefaultTextColor(QColor(C["danger"]))
        msg.setFont(QFont("Inter", 10))
        msg.setTextWidth(self.NODE_W - 24)
        msg.setPos(12, 100)
        self.addToGroup(msg)

    def update_status(self, status: str, result_file: str = "", error: str = ""):
        self.canvas_item.status = status
        if result_file: self.canvas_item.result_file = result_file
        if error: self.canvas_item.error = error
        self._render()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.canvas_item.x = self.scenePos().x()
            self.canvas_item.y = self.scenePos().y()
        return super().itemChange(change, value)


# =========================================================================
class ConnectionLine(QGraphicsPathItem):
    """节点间引用连线 — 跟随源/终点节点位置自动重画。"""

    def __init__(self, src_node, dst_node, kind: str = "ref"):
        super().__init__()
        self.src = src_node
        self.dst = dst_node
        self.kind = kind
        pen = QPen(QColor("#c4c4c4"), 1.2)
        self.setPen(pen)
        self.setZValue(-10)
        self.update_path()

    def update_path(self):
        if not self.src or not self.dst: return
        try:
            src_rect = self.src.sceneBoundingRect()
            dst_rect = self.dst.sceneBoundingRect()
        except RuntimeError:
            return
        sx = src_rect.right()
        sy = src_rect.center().y()
        ex = dst_rect.left()
        ey = dst_rect.center().y()
        path = QPainterPath()
        path.moveTo(sx, sy)
        offset = max(40, abs(ex - sx) / 2)
        path.cubicTo(sx + offset, sy, ex - offset, ey, ex, ey)
        self.setPath(path)


# =========================================================================
# M7: 视频节点 — 显示首帧 + 时长 + 双击外部播放
class VideoNode(_NodeBase):
    """显示已生成视频。首帧用 ffmpeg 抽,点节点系统播放器打开。"""

    NODE_W = 220
    NODE_H = 200

    def __init__(self, node_id: str, video_path: Path,
                 title: str = "视频", duration_s: float = 0.0):
        super().__init__()
        self.node_id = node_id
        self.kind = "video"
        self.title = title
        self.video_path = Path(video_path)
        self.duration_s = duration_s
        self._build()

    def _build(self):
        bg = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, self.NODE_H, RADIUS))
        bg.setBrush(QBrush(QColor("#ffffff")))
        bg.setPen(QPen(QColor(C["border_soft"]), 1))
        self.addToGroup(bg)

        # 视频粉色 header
        header = QGraphicsPathItem(_rounded_path(0, 0, self.NODE_W, NODE_HEADER_H, RADIUS, only_top=True))
        header.setBrush(QBrush(QColor(KIND_COLORS["video"])))
        header.setPen(QPen(Qt.NoPen))
        self.addToGroup(header)

        ic = QGraphicsTextItem("🎥")
        ic.setDefaultTextColor(QColor("white"))
        ic.setFont(QFont("Inter", 12))
        ic.setPos(8, 4)
        self.addToGroup(ic)

        title_item = QGraphicsTextItem(self.title)
        title_item.setDefaultTextColor(QColor("white"))
        f = QFont("Inter Tight"); f.setPointSize(10); f.setWeight(QFont.DemiBold)
        title_item.setFont(f)
        title_item.setPos(34, 6)
        title_item.setTextWidth(self.NODE_W - 80)
        self.addToGroup(title_item)

        # 时长徽章
        if self.duration_s > 0:
            dur_label = QGraphicsTextItem(f"{self.duration_s:.1f}s")
            dur_label.setDefaultTextColor(QColor("white"))
            dur_label.setFont(QFont("JetBrains Mono", 9))
            tr = dur_label.boundingRect()
            dur_label.setPos(self.NODE_W - tr.width() - 8, 7)
            self.addToGroup(dur_label)

        # 黑底首帧
        thumb_y = NODE_HEADER_H + 8
        thumb_w = self.NODE_W - 16
        thumb_h = self.NODE_H - NODE_HEADER_H - 36
        ph = QGraphicsPathItem(_rounded_path(8, thumb_y, thumb_w, thumb_h, 6))
        ph.setBrush(QBrush(QColor("#1a1a1a")))
        ph.setPen(QPen(QColor(C["border_soft"]), 1))
        self.addToGroup(ph)

        frame_path = self._ensure_frame_thumbnail()
        if frame_path and frame_path.exists():
            pm = QPixmap(str(frame_path))
            if not pm.isNull():
                pm = pm.scaled(thumb_w, thumb_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                thumb = QGraphicsPixmapItem(pm)
                tx = 8 + max(0, (thumb_w - pm.width()) // 2)
                ty = thumb_y + max(0, (thumb_h - pm.height()) // 2)
                thumb.setPos(tx, ty)
                self.addToGroup(thumb)

        # 播放图标 overlay
        play = QGraphicsTextItem("▶")
        play.setDefaultTextColor(QColor(255, 255, 255, 220))
        f2 = QFont("Inter Tight"); f2.setPointSize(20); f2.setWeight(QFont.Bold)
        play.setFont(f2)
        tr = play.boundingRect()
        play.setPos(self.NODE_W / 2 - tr.width() / 2,
                    thumb_y + thumb_h / 2 - tr.height() / 2)
        self.addToGroup(play)

        # 文件名
        fn = QGraphicsTextItem(self.video_path.name)
        fn.setDefaultTextColor(QColor(C["muted"]))
        fn.setFont(QFont("Inter", 8))
        fn.setTextWidth(self.NODE_W - 16)
        fn.setPos(8, self.NODE_H - 22)
        self.addToGroup(fn)

        self._outline = QGraphicsPathItem(_rounded_path(-2, -2, self.NODE_W + 4, self.NODE_H + 4, RADIUS + 2))
        self._outline.setBrush(QBrush(Qt.NoBrush))
        self._outline.setPen(QPen(QColor(C["accent"]), 2))
        self._outline.setVisible(False)
        self.addToGroup(self._outline)

    def _ensure_frame_thumbnail(self) -> Optional[Path]:
        """用 ffmpeg 抽 0.5s 处首帧,缓存到 同目录/<stem>.frame.jpg"""
        import subprocess, shutil
        if not self.video_path.exists(): return None
        thumb = self.video_path.parent / (self.video_path.stem + ".frame.jpg")
        if thumb.exists(): return thumb
        if not shutil.which("ffmpeg"): return None
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "0.5", "-i", str(self.video_path),
                 "-vframes", "1", "-q:v", "3", str(thumb)],
                capture_output=True, timeout=10
            )
            return thumb if thumb.exists() else None
        except Exception:
            return None

    def open_external(self):
        """系统默认播放器打开。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.video_path.absolute())))


# =========================================================================
class GeneratorDialog(QDialog):
    """新建/编辑生成器节点的对话框。"""

    def __init__(self, parent=None, canvas_item: CanvasItem = None):
        super().__init__(parent)
        self.canvas_item = canvas_item or CanvasItem(kind=CANVAS_GENERATOR)
        self.setWindowTitle("生成器节点 — 画布内直接生图")
        self.setMinimumWidth(560)

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)
        t = QLabel("画布内生成图 / 视频")
        t.setStyleSheet("font-size: 16px; font-weight: 500;")
        l.addWidget(t)

        f = QFormLayout(); f.setSpacing(10)

        self.title_input = QLineEdit()
        self.title_input.setText(self.canvas_item.title or "")
        self.title_input.setPlaceholderText("可选,显示在节点头部")
        f.addRow("标题", self.title_input)

        self.type_combo = QComboBox()
        self.type_combo.addItem("生成图片 (image)", "image")
        self.type_combo.addItem("生成视频 (video)", "video")
        # 默认 image
        if self.canvas_item.task_type == "video":
            self.type_combo.setCurrentIndex(1)
        f.addRow("类型", self.type_combo)

        self.backend_combo = QComboBox()
        backends = ST.load_backends()
        for b in backends:
            if not b.enabled: continue
            self.backend_combo.addItem(f"{b.icon} {b.name}", b.id)
        # 选中现有
        for i in range(self.backend_combo.count()):
            if self.backend_combo.itemData(i) == self.canvas_item.backend_id:
                self.backend_combo.setCurrentIndex(i); break
        # 联动:类型改变时,backend 默认调整
        self.type_combo.currentIndexChanged.connect(self._on_type_change)
        f.addRow("Backend", self.backend_combo)

        l.addLayout(f)

        # Prompt label + 模板按钮 同一行
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("Prompt:"))
        prompt_row.addStretch()
        tpl_btn = QPushButton("📋 套模板")
        tpl_btn.setObjectName("Subtle")
        tpl_btn.setToolTip("从内置模板库填一份现成 prompt(角色三视图 / 场景固定 / 分镜板 等)")
        tpl_btn.clicked.connect(self._pick_template)
        prompt_row.addWidget(tpl_btn)
        l.addLayout(prompt_row)
        self.prompt_box = QPlainTextEdit()
        self.prompt_box.setPlainText(self.canvas_item.prompt or "")
        self.prompt_box.setPlaceholderText(
            "示例:陆渊在矿坑里发现紫金符文,光线从地面渗出,8K 电影感。\n\n"
            "或者点右上的 📋 套模板 快速生成结构化 prompt。"
        )
        self.prompt_box.setMinimumHeight(180)
        l.addWidget(self.prompt_box)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("发起生成", QDialogButtonBox.AcceptRole); ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def _pick_template(self):
        """打开模板挑选器:列出 prompts.DEFAULT_PROMPT_TEMPLATES,
        选中后弹一个简单表单收占位符的值,然后渲染填进 prompt 框。"""
        from .prompts import DEFAULT_PROMPT_TEMPLATES, render_template
        # 1. 选模板
        names = [f"[{t.category}] {t.title}" for t in DEFAULT_PROMPT_TEMPLATES]
        if not names:
            QMessageBox.information(self, "无模板", "模板库为空。")
            return
        choice, ok = QInputDialog.getItem(
            self, "选模板", "选一个模板填到 Prompt 框:", names, 0, False
        )
        if not ok: return
        idx = names.index(choice)
        tpl = DEFAULT_PROMPT_TEMPLATES[idx]
        # 2. 若有占位符,弹个表单收值
        values = {}
        if tpl.placeholders:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"填模板占位符 — {tpl.title}")
            dlg.setMinimumWidth(520)
            dl = QVBoxLayout(dlg); dl.setSpacing(10)
            dl.addWidget(QLabel(f"模板:{tpl.title}"))
            fm = QFormLayout(); fm.setSpacing(8)
            editors = {}
            # 给一些常见占位符预填默认值
            DEFAULTS = {
                "style": "2D 写实国漫,东方玄幻",
                "gender": "男",
                "age": "成年",
                "name": "",
                "appearance": "",
                "aspect_ratio": "16:9",
                "asset_description": "",
            }
            for ph in tpl.placeholders:
                ed = QPlainTextEdit()
                ed.setMaximumHeight(70 if ph in ("appearance", "asset_description") else 32)
                ed.setPlainText(DEFAULTS.get(ph, ""))
                fm.addRow(ph, ed)
                editors[ph] = ed
            dl.addLayout(fm)
            bb = QDialogButtonBox()
            bb.addButton("取消", QDialogButtonBox.RejectRole)
            bb.addButton("套用", QDialogButtonBox.AcceptRole)
            bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
            dl.addWidget(bb)
            if dlg.exec() != QDialog.Accepted:
                return
            for ph, ed in editors.items():
                values[ph] = ed.toPlainText().strip() or "(未指定)"
        # 3. 渲染并塞进 prompt box
        try:
            rendered = render_template(tpl, **values) if values else tpl.content
        except Exception as e:
            QMessageBox.warning(self, "模板渲染失败", str(e))
            return
        # 已有内容时让用户选合并方式
        if self.prompt_box.toPlainText().strip():
            ans = QMessageBox.question(
                self, "已有 Prompt", "Prompt 框已有内容,要怎么处理?",
                QMessageBox.StandardButton.Yes |  # 覆盖
                QMessageBox.StandardButton.No |   # 追加到末尾
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Cancel: return
            if ans == QMessageBox.StandardButton.No:
                rendered = self.prompt_box.toPlainText() + "\n\n" + rendered
        self.prompt_box.setPlainText(rendered)

    def _on_type_change(self):
        # 类型切换时,如果当前 backend 不匹配,自动切到合适的
        kind = self.type_combo.currentData()
        if kind == "video":
            for i in range(self.backend_combo.count()):
                if self.backend_combo.itemData(i) == "doubao":
                    self.backend_combo.setCurrentIndex(i); return
        else:
            for i in range(self.backend_combo.count()):
                if self.backend_combo.itemData(i) == "gpt-mirror":
                    self.backend_combo.setCurrentIndex(i); return

    def commit(self) -> CanvasItem:
        self.canvas_item.title = self.title_input.text().strip()
        self.canvas_item.task_type = self.type_combo.currentData()
        self.canvas_item.backend_id = self.backend_combo.currentData()
        self.canvas_item.prompt = self.prompt_box.toPlainText().strip()
        return self.canvas_item


# =========================================================================
class ImagePreviewDialog(QDialog):
    """节点大图预览对话框 — 全屏看图,左右键浏览同画布上所有 done 图节点。

    传入:
      paths:  按显示顺序的 (title, abs_path_to_image) 列表
      start:  初始打开第几张(index)
    交互:
      ← / →:  上一张/下一张
      ESC:     关闭
      鼠标滚轮: 缩放(适配窗口的相对比例)
    """

    def __init__(self, parent, items, start_idx: int = 0):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        # 启用最大化
        try:
            from PySide6.QtCore import Qt as _Qt
            self.setWindowFlags(self.windowFlags() | _Qt.WindowMaximizeButtonHint)
        except Exception: pass
        self.resize(1280, 800)
        self._items = items  # list of (title, abs_path)
        self._idx = max(0, min(start_idx, len(items) - 1))
        self._scale_factor = 1.0  # 用户滚轮缩放(在 fit 的基础上再乘)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # 标题栏
        title_row = QHBoxLayout()
        self._title_label = QLabel("")
        self._title_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        title_row.addWidget(self._title_label, 1)
        self._counter_label = QLabel("")
        self._counter_label.setStyleSheet("color: #888; font-size: 12px;")
        title_row.addWidget(self._counter_label)
        root.addLayout(title_row)

        # 图片区
        self._image_label = QLabel("(加载中…)")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("background: #1a1a1a; color: #ccc; border-radius: 8px;")
        self._image_label.setMinimumSize(800, 500)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._image_label, 1)

        # 底部工具栏
        bottom = QHBoxLayout()
        self._prev_btn = QPushButton("← 上一张")
        self._prev_btn.clicked.connect(self._prev)
        bottom.addWidget(self._prev_btn)
        self._next_btn = QPushButton("下一张 →")
        self._next_btn.clicked.connect(self._next)
        bottom.addWidget(self._next_btn)
        bottom.addStretch()
        zoom_out = QPushButton("－"); zoom_out.setMaximumWidth(40)
        zoom_out.clicked.connect(lambda: self._zoom(0.8))
        bottom.addWidget(zoom_out)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setMinimumWidth(50)
        self._zoom_label.setAlignment(Qt.AlignCenter)
        bottom.addWidget(self._zoom_label)
        zoom_in = QPushButton("＋"); zoom_in.setMaximumWidth(40)
        zoom_in.clicked.connect(lambda: self._zoom(1.25))
        bottom.addWidget(zoom_in)
        fit_btn = QPushButton("适配窗口")
        fit_btn.clicked.connect(self._reset_zoom)
        bottom.addWidget(fit_btn)
        bottom.addStretch()
        open_btn = QPushButton("🗂 在文件夹中显示")
        open_btn.clicked.connect(self._reveal_in_folder)
        bottom.addWidget(open_btn)
        close_btn = QPushButton("关闭 (Esc)")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        # 当前图缓存
        self._current_pixmap: Optional[QPixmap] = None
        self._load_current()

    def _load_current(self):
        if not self._items: return
        title, path = self._items[self._idx]
        self._title_label.setText(title or Path(path).name)
        self._counter_label.setText(f"{self._idx + 1} / {len(self._items)}")
        pix = QPixmap(str(path))
        if pix.isNull():
            self._current_pixmap = None
            self._image_label.setText(f"(无法加载: {path})")
        else:
            self._current_pixmap = pix
            self._scale_factor = 1.0
            self._redraw()
        # prev/next 禁用边界
        self._prev_btn.setEnabled(self._idx > 0)
        self._next_btn.setEnabled(self._idx < len(self._items) - 1)

    def _redraw(self):
        if not self._current_pixmap: return
        avail = self._image_label.size()
        # 先 fit 到容器,再乘用户的缩放
        fitted = self._current_pixmap.scaled(
            avail, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if abs(self._scale_factor - 1.0) > 0.001:
            target = fitted.size() * self._scale_factor
            fitted = self._current_pixmap.scaled(
                target, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        self._image_label.setPixmap(fitted)
        self._zoom_label.setText(f"{int(self._scale_factor * 100)}%")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._redraw()

    def _prev(self):
        if self._idx > 0:
            self._idx -= 1
            self._load_current()

    def _next(self):
        if self._idx < len(self._items) - 1:
            self._idx += 1
            self._load_current()

    def _zoom(self, factor: float):
        self._scale_factor = max(0.1, min(8.0, self._scale_factor * factor))
        self._redraw()

    def _reset_zoom(self):
        self._scale_factor = 1.0
        self._redraw()

    def _reveal_in_folder(self):
        if not self._items: return
        path = Path(self._items[self._idx][1])
        if not path.exists(): return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Left:
            self._prev(); return
        if e.key() == Qt.Key_Right:
            self._next(); return
        if e.key() == Qt.Key_Escape:
            self.accept(); return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        # ctrl+滚轮 = 缩放;普通滚轮 = 翻页
        if e.modifiers() & Qt.ControlModifier:
            delta = e.angleDelta().y()
            self._zoom(1.2 if delta > 0 else 0.8333)
        else:
            delta = e.angleDelta().y()
            if delta > 0:
                self._prev()
            elif delta < 0:
                self._next()
        e.accept()


# =========================================================================
class CanvasView(QGraphicsView):
    """画布视图本体。"""

    node_double_clicked = Signal(str, str)
    node_action         = Signal(str, str, str)
    blank_action        = Signal(str, QPointF)   # action, scene pos
    log                 = Signal(str)
    manual_connection   = Signal(str, str)       # src_id, dst_id
    # 任何脏操作(添加/删除/移动/连线/拖动)发出本信号 → 父级 debounce 保存
    dirty_changed       = Signal()
    # 用户从 OS 拖文件到画布:list[str] 文件路径, QPointF scene pos
    files_dropped       = Signal(list, QPointF)

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(C["bg"])))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 接收 OS 拖入的文件
        self.setAcceptDrops(True)

        self.scene_ = QGraphicsScene(-5000, -5000, 10000, 10000)
        self.setScene(self.scene_)

        self._panning = False
        self._pan_start: QPointF = QPointF()
        self._zoom = 1.0
        self._nodes_by_id: Dict[str, _NodeBase] = {}
        self._connections: List[ConnectionLine] = []

        # 手动连线状态
        self._connect_mode = False
        self._connect_src: Optional[_NodeBase] = None
        self._temp_line: Optional[QGraphicsPathItem] = None

    # ---- OS 文件拖入 ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        if not md.hasUrls():
            super().dropEvent(e); return
        paths = []
        for u in md.urls():
            if u.isLocalFile():
                paths.append(u.toLocalFile())
        if paths:
            scene_pos = self.mapToScene(e.position().toPoint())
            self.files_dropped.emit(paths, scene_pos)
            e.acceptProposedAction()
        else:
            super().dropEvent(e)

    def set_connect_mode(self, on: bool):
        self._connect_mode = on
        if on:
            self.setCursor(QCursor(Qt.CrossCursor))
            self.setDragMode(QGraphicsView.NoDrag)
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self._connect_src = None
            if self._temp_line:
                self.scene_.removeItem(self._temp_line); self._temp_line = None

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        pen_light = QPen(QColor("#eeeeee"), 0)
        painter.setPen(pen_light)
        step = 40
        left = int(rect.left()) - (int(rect.left()) % step)
        top  = int(rect.top())  - (int(rect.top())  % step)
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom())); x += step
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y)); y += step
        pen_strong = QPen(QColor("#e0e0e0"), 0)
        painter.setPen(pen_strong)
        step_b = 200
        left_b = int(rect.left()) - (int(rect.left()) % step_b)
        top_b  = int(rect.top())  - (int(rect.top())  % step_b)
        x = left_b
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom())); x += step_b
        y = top_b
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y)); y += step_b

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or \
           (e.button() == Qt.LeftButton and (e.modifiers() & Qt.ControlModifier)):
            self._panning = True
            self._pan_start = e.position()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        # 连线模式 + 左键点中节点 → 开始连线
        if self._connect_mode and e.button() == Qt.LeftButton:
            node = self._find_node(self.itemAt(e.position().toPoint()))
            if node:
                self._connect_src = node
                self._temp_line = QGraphicsPathItem()
                pen = QPen(QColor(C["accent"]), 2, Qt.DashLine)
                self._temp_line.setPen(pen)
                self._temp_line.setZValue(10)
                self.scene_.addItem(self._temp_line)
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panning:
            delta = e.position() - self._pan_start
            self._pan_start = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        # 连线进行中:跟随鼠标
        if self._connect_mode and self._connect_src and self._temp_line:
            src_rect = self._connect_src.sceneBoundingRect()
            sx = src_rect.right(); sy = src_rect.center().y()
            cur = self.mapToScene(e.position().toPoint())
            ex, ey = cur.x(), cur.y()
            path = QPainterPath()
            path.moveTo(sx, sy)
            offset = max(40, abs(ex - sx) / 2)
            path.cubicTo(sx + offset, sy, ex - offset, ey, ex, ey)
            self._temp_line.setPath(path)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            if self._connect_mode:
                self.setCursor(QCursor(Qt.CrossCursor))
            else:
                self.setCursor(QCursor(Qt.ArrowCursor))
            return
        # 连线完成
        if self._connect_mode and self._connect_src and e.button() == Qt.LeftButton:
            dst = self._find_node(self.itemAt(e.position().toPoint()))
            if dst and dst is not self._connect_src:
                self.manual_connection.emit(self._connect_src.node_id, dst.node_id)
            if self._temp_line:
                self.scene_.removeItem(self._temp_line)
                self._temp_line = None
            self._connect_src = None
            return
        # 普通 release — 可能是刚拖完一个节点。无脑发 dirty,父级 debounce 处理冗余
        if e.button() == Qt.LeftButton:
            self.dirty_changed.emit()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        node = self._find_node(item)
        if node:
            if isinstance(node, TextNode):
                self.node_action.emit("edit_text", node.kind, node.node_id)
            elif isinstance(node, GeneratorNode):
                # 已完成的图片 → 看大图浏览;否则 → 编辑/重生
                ci = node.canvas_item
                if (ci.status == "done" and ci.result_file
                        and ci.kind in (CANVAS_IMAGE, CANVAS_GENERATOR)
                        and ci.task_type != "video"):
                    self.node_action.emit("preview_image", node.kind, node.node_id)
                else:
                    self.node_action.emit("edit_generator", node.kind, node.node_id)
            elif isinstance(node, VideoNode):
                node.open_external()
            else:
                self.node_double_clicked.emit(node.kind, node.node_id)
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        item = self.itemAt(e.pos())
        node = self._find_node(item)
        scene_pos = self.mapToScene(e.pos())

        if not node:
            # 空白处右键
            menu = QMenu(self)
            menu.addAction("🤖 在此生成图...",
                          lambda: self.blank_action.emit("new_generator", scene_pos))
            menu.addAction("📝 在此放文本",
                          lambda: self.blank_action.emit("new_text", scene_pos))
            menu.addAction("🖼 上传图片/视频到此...",
                          lambda: self.blank_action.emit("upload_media", scene_pos))
            menu.addSeparator()
            menu.addAction("🎯 适配所有节点", self.fit_all)
            menu.addAction("🔍 重置缩放 (100%)", self.reset_zoom)
            menu.exec(e.globalPos())
            return

        menu = QMenu(self)
        if isinstance(node, VideoNode):
            menu.addAction("▶ 播放 (外部播放器)", lambda: node.open_external())
            menu.addAction("📋 复制文件路径",
                          lambda: self.node_action.emit("copy_path", node.kind, node.node_id))
            menu.addSeparator()
            menu.addAction("🗑 隐藏此视频节点",
                          lambda: self.node_action.emit("delete", node.kind, node.node_id))
        elif isinstance(node, GeneratorNode):
            # 已完成的图片节点:加'看大图'入口(双击也走这条)
            ci = node.canvas_item
            if (ci.status == "done" and ci.result_file
                    and ci.task_type != "video"):
                menu.addAction("🔍 看大图 (双击同效)",
                              lambda: self.node_action.emit("preview_image", node.kind, node.node_id))
            menu.addAction("✎ 编辑 / 重新生成",
                          lambda: self.node_action.emit("edit_generator", node.kind, node.node_id))
            menu.addSeparator()
            menu.addAction("🗑 删除",
                          lambda: self.node_action.emit("delete", node.kind, node.node_id))
        elif isinstance(node, TextNode):
            menu.addAction("✎ 编辑文本",
                          lambda: self.node_action.emit("edit_text", node.kind, node.node_id))
            menu.addSeparator()
            menu.addAction("🗑 删除",
                          lambda: self.node_action.emit("delete", node.kind, node.node_id))
        else:
            # AssetNode (角色/场景/道具/分镜)
            title = getattr(node, "title", "节点")
            menu.addAction(f"📋 复制 {title} 的 prompt",
                          lambda: self.node_action.emit("copy_prompt", node.kind, node.node_id))
            if node.kind in ("character", "scene", "prop"):
                menu.addAction("🤖 用 GPT 生成",
                              lambda: self.node_action.emit("gen_gpt", node.kind, node.node_id))
            if node.kind == "shot":
                menu.addAction("🎨 拼故事板大图",
                              lambda: self.node_action.emit("gen_storyboard", node.kind, node.node_id))
                menu.addAction("🎬 用豆包生视频",
                              lambda: self.node_action.emit("gen_video", node.kind, node.node_id))
            menu.addSeparator()
            menu.addAction("✎ 打开编辑",
                          lambda: self.node_double_clicked.emit(node.kind, node.node_id))
        menu.exec(e.globalPos())

    def _find_node(self, item) -> Optional[_NodeBase]:
        while item:
            if isinstance(item, _NodeBase): return item
            item = item.parentItem()
        return None

    def wheelEvent(self, e):
        zoom_factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self._zoom * zoom_factor
        if 0.1 < new_zoom < 5.0:
            self.scale(zoom_factor, zoom_factor)
            self._zoom = new_zoom

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0

    def fit_all(self):
        if not self._nodes_by_id: return
        rect = None
        for node in self._nodes_by_id.values():
            try:
                r = node.sceneBoundingRect()
            except RuntimeError:
                continue
            rect = r if rect is None else rect.united(r)
        if rect:
            rect = rect.adjusted(-50, -50, 50, 50)
            self.fitInView(rect, Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

    # ---- 节点管理 ----
    def add_node(self, node: _NodeBase, pos: QPointF):
        self.scene_.addItem(node)
        node.setPos(pos)
        self._nodes_by_id[node.node_id] = node
        self.dirty_changed.emit()

    def remove_node(self, node_id: str):
        node = self._nodes_by_id.get(node_id)
        if not node: return
        # 先删与本节点相关的连线
        to_remove = [ln for ln in self._connections
                     if ln.src is node or ln.dst is node]
        for ln in to_remove:
            self.scene_.removeItem(ln)
            self._connections.remove(ln)
        self.scene_.removeItem(node)
        del self._nodes_by_id[node_id]
        self.dirty_changed.emit()

    def add_connection(self, src_id: str, dst_id: str):
        src = self._nodes_by_id.get(src_id)
        dst = self._nodes_by_id.get(dst_id)
        if not src or not dst: return
        # 重复检测
        for ln in self._connections:
            if ln.src is src and ln.dst is dst: return
        ln = ConnectionLine(src, dst)
        self.scene_.addItem(ln)
        self._connections.append(ln)
        src.add_connection(ln); dst.add_connection(ln)
        self.dirty_changed.emit()

    def clear_all(self):
        for ln in self._connections:
            self.scene_.removeItem(ln)
        self._connections.clear()
        for node in list(self._nodes_by_id.values()):
            self.scene_.removeItem(node)
        self._nodes_by_id.clear()

    def get_asset_positions(self) -> Dict[str, Tuple[float, float]]:
        return {nid: (n.scenePos().x(), n.scenePos().y())
                for nid, n in self._nodes_by_id.items()
                if isinstance(n, AssetNode)}


# =========================================================================
class InfiniteCanvasView(QFrame):
    """画布 tab 的容器:工具栏 + CanvasView + worker hookup。"""

    log = Signal(str)

    def __init__(self, owner=None):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.owner = owner
        self.pid: Optional[str] = None
        self._canvas_items: List[CanvasItem] = []

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        tb = QFrame(); tb.setObjectName("Panel")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(28, 16, 28, 14); tbl.setSpacing(8)
        title = QLabel("无限画布"); title.setObjectName("H2")
        tbl.addWidget(title)
        sub = QLabel("空白处右键 = 在此生成 · 双击节点 = 编辑 · 滚轮缩放 · 中键平移")
        sub.setStyleSheet(f"color: {C['muted']}; font-size: 10.5px; margin-left: 8px;")
        tbl.addWidget(sub)
        tbl.addStretch()

        add_gen_btn = QPushButton("🤖 新增生成器")
        add_gen_btn.setObjectName("Accent")
        add_gen_btn.setCursor(QCursor(Qt.PointingHandCursor))
        add_gen_btn.setToolTip("在画布中央放一个生成器节点")
        add_gen_btn.clicked.connect(lambda: self._add_generator_at(QPointF(0, 0)))
        tbl.addWidget(add_gen_btn)

        add_text_btn = QPushButton("📝 新增文本")
        add_text_btn.setObjectName("Subtle")
        add_text_btn.clicked.connect(lambda: self._add_text_at(QPointF(0, 0)))
        tbl.addWidget(add_text_btn)

        upload_btn = QPushButton("🖼 上传")
        upload_btn.setObjectName("Subtle")
        upload_btn.setToolTip("从本地导入图片/视频到画布(可多选)")
        upload_btn.clicked.connect(lambda: self._upload_media_at(None))
        tbl.addWidget(upload_btn)

        self.connect_mode_btn = QPushButton("🔗 连线")
        self.connect_mode_btn.setObjectName("Subtle")
        self.connect_mode_btn.setCheckable(True)
        self.connect_mode_btn.setToolTip("打开后,点节点 A 拖到节点 B 创建引用连线;再次点关闭")
        self.connect_mode_btn.toggled.connect(self._toggle_connect_mode)
        tbl.addWidget(self.connect_mode_btn)

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setObjectName("Subtle")
        refresh_btn.clicked.connect(self._refresh)
        tbl.addWidget(refresh_btn)

        fit_btn = QPushButton("🎯 全览"); fit_btn.setObjectName("Subtle")
        fit_btn.clicked.connect(lambda: self.canvas.fit_all())
        tbl.addWidget(fit_btn)

        reset_btn = QPushButton("🔍 100%"); reset_btn.setObjectName("Subtle")
        reset_btn.clicked.connect(lambda: self.canvas.reset_zoom())
        tbl.addWidget(reset_btn)

        auto_btn = QPushButton("📐 自动布局"); auto_btn.setObjectName("Subtle")
        auto_btn.clicked.connect(self._auto_layout)
        tbl.addWidget(auto_btn)

        # 保存状态指示器(autosave 用)— 让用户看得见自动保存确实在跑
        self._save_status_label = QLabel("💾 已保存")
        self._save_status_label.setStyleSheet(
            "color: #888; font-size: 12px; padding: 0 8px;"
        )
        self._save_status_label.setToolTip("画布会在你改动后 2 秒内自动保存")
        tbl.addWidget(self._save_status_label)

        save_btn = QPushButton("💾 立即保存"); save_btn.setObjectName("Subtle")
        save_btn.setToolTip("强制立刻保存(平时不点也会 2s 内自动保存)")
        save_btn.clicked.connect(self._save_all_immediate)
        tbl.addWidget(save_btn)

        root.addWidget(tb); root.addWidget(Hline())

        self.canvas = CanvasView()
        self.canvas.node_double_clicked.connect(self._on_node_dclick)
        self.canvas.node_action.connect(self._on_node_action)
        self.canvas.blank_action.connect(self._on_blank_action)
        self.canvas.log.connect(self.log)
        self.canvas.manual_connection.connect(self._on_manual_connection)
        self.canvas.files_dropped.connect(
            lambda paths, pos: self._upload_media_at(pos, paths=paths)
        )
        root.addWidget(self.canvas, 1)

        # 连接 Worker 完成信号
        try:
            from .playwright_worker import get_worker
            w = get_worker()
            w.task_done.connect(self._on_task_done)
            w.task_failed.connect(self._on_task_failed)
        except Exception as e:
            print(f"无法挂接 worker 信号: {e}")

        # 自动保存:2 秒 debounce
        # 任何 dirty 信号(节点添加/删除/拖动/连线)重启计时器 → 用户停手 2s 后才存,
        # 比老版的 8s 周期 polling 既快又省。手动按"立即保存"绕过 debounce。
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._do_autosave)
        self.canvas.dirty_changed.connect(self._mark_dirty)
        # _loading=True 时屏蔽 dirty(否则 _refresh 一次性 add_node 几十个节点会一直触发)
        self._loading = False
        # 还保留 worker 完成回写的兜底定时(60s 一次,catch 漏掉的 dirty)
        self._safety_timer = QTimer(self)
        self._safety_timer.setInterval(60000)
        self._safety_timer.timeout.connect(self._do_autosave)
        self._safety_timer.start()

    def load(self, pid: str):
        self.pid = pid
        self._refresh()

    def _refresh(self):
        if not self.pid:
            self.canvas.clear_all(); return
        self._loading = True  # 屏蔽 add_node 触发的 dirty
        self.canvas.clear_all()

        positions = self._load_positions()
        nodes_to_add: List[_NodeBase] = []

        # 1. 资产节点(角色/场景/道具/分镜)
        chars = ST.load_characters(self.pid)
        scenes = ST.load_scenes(self.pid)
        props = ST.load_props(self.pid)
        eps = ST.list_episodes(self.pid)

        for c in chars:
            img = ST.asset_full_path(self.pid, c.reference_image) if c.reference_image else None
            sub = f"{c.role or ''}  {c.placeholder or ''}".strip()
            nodes_to_add.append(AssetNode(c.id, "character", c.name, sub, img,
                                          color=KIND_COLORS["character"]))
        for s in scenes:
            img = ST.asset_full_path(self.pid, s.reference_image) if s.reference_image else None
            sub = s.placeholder or s.visual_style or ""
            nodes_to_add.append(AssetNode(s.id, "scene", s.name, sub, img,
                                          color=KIND_COLORS["scene"]))
        for p in props:
            img = ST.asset_full_path(self.pid, p.reference_image) if p.reference_image else None
            sub = p.placeholder or (p.description[:40] if p.description else "")
            nodes_to_add.append(AssetNode(p.id, "prop", p.name, sub, img,
                                          color=KIND_COLORS["prop"]))

        shots_index = {}   # shot_id → shot 对象(用于建连线)
        video_node_ids = {}   # shot_id → video_node_id
        for ep in eps:
            for shot in ep.shots:
                shots_index[shot.id] = shot
                img = ST.asset_full_path(self.pid, shot.generated_image) if shot.generated_image else None
                title = f"分镜 #{shot.number}"
                parts = [shot.shot_size or "", shot.camera_movement or "", f"{shot.duration}s"]
                if shot.action: parts.append(shot.action[:25])
                sub = "  ".join(filter(None, parts))
                nodes_to_add.append(AssetNode(shot.id, "shot", title, sub, img,
                                              color=KIND_COLORS["shot"]))
                # M7: 若有生成视频,额外加 VideoNode
                if shot.generated_video:
                    vp = ST.asset_full_path(self.pid, shot.generated_video)
                    if vp.exists():
                        vnode_id = f"video::{shot.id}"
                        nodes_to_add.append(VideoNode(
                            vnode_id, vp,
                            title=f"视频 #{shot.number}",
                            duration_s=shot.duration,
                        ))
                        video_node_ids[shot.id] = vnode_id

        # 2. 画布自定义节点
        self._canvas_items = ST.load_canvas_items(self.pid)
        for item in self._canvas_items:
            if item.kind == CANVAS_TEXT:
                nodes_to_add.append(TextNode(item))
            elif item.kind in (CANVAS_GENERATOR, CANVAS_IMAGE, CANVAS_VIDEO):
                nodes_to_add.append(GeneratorNode(item))

        if not nodes_to_add:
            self.log.emit("画布为空 — 在角色/场景/分镜表里建对象,或空白处右键「在此生成图」")
            return

        # 3. 摆放 — 有保存位置用保存,否则自动布局
        unplaced: List[_NodeBase] = []
        for node in nodes_to_add:
            if isinstance(node, (TextNode, GeneratorNode)):
                pos = QPointF(node.canvas_item.x, node.canvas_item.y)
                self.canvas.add_node(node, pos)
            elif node.node_id in positions:
                x, y = positions[node.node_id]
                self.canvas.add_node(node, QPointF(x, y))
            else:
                self.canvas.add_node(node, QPointF(0, 0))
                unplaced.append(node)

        if unplaced:
            self._auto_layout(target_nodes=unplaced)

        # 4. 建引用连线(角色/场景/道具 → 分镜 → 视频)
        for shot_id, shot in shots_index.items():
            for cid in shot.character_ids:
                self.canvas.add_connection(cid, shot_id)
            for pid in shot.prop_ids:
                self.canvas.add_connection(pid, shot_id)
            if shot.scene_id:
                self.canvas.add_connection(shot.scene_id, shot_id)
            # shot → video 节点
            if shot_id in video_node_ids:
                self.canvas.add_connection(shot_id, video_node_ids[shot_id])

        # 4b. 手动连线(用户拖出来的)
        manual_f = ST.project_dir(self.pid) / "manual_links.json"
        if manual_f.exists():
            try:
                links = json.loads(manual_f.read_text(encoding="utf-8"))
                for link in links:
                    self.canvas.add_connection(link.get("src", ""), link.get("dst", ""))
            except Exception:
                pass

        self.canvas.fit_all()
        n_canvas = sum(1 for it in self._canvas_items)
        self.log.emit(f"画布加载 {len(nodes_to_add)} 节点 ({len(self.canvas._connections)} 连线,自定义 {n_canvas})")
        self._loading = False  # 加载完毕,后续 add_node 才会被 _mark_dirty 当真

    def _auto_layout(self, target_nodes: List[_NodeBase] = None):
        if not self.pid: return
        nodes = target_nodes or list(self.canvas._nodes_by_id.values())
        if not nodes: return

        cols = 4
        x_step = NODE_W + 30
        y_step = NODE_H + 40

        by_kind = {"character": [], "scene": [], "prop": [], "shot": [],
                   "text": [], "generator": [], "image": [], "video": []}
        for n in nodes:
            by_kind.setdefault(n.kind, []).append(n)

        kind_order = ["character", "scene", "prop", "shot", "generator", "image", "video", "text"]
        cur_y = 0
        for kind in kind_order:
            group = by_kind.get(kind, [])
            if not group: continue
            for i, node in enumerate(group):
                col = i % cols
                row = i // cols
                node.setPos(col * x_step, cur_y + row * y_step)
            rows = math.ceil(len(group) / cols)
            cur_y += rows * y_step + 60

        self.canvas.fit_all()
        self.log.emit("自动布局已应用")

    # ---- 持久化 ----
    def _positions_file(self) -> Path:
        return ST.project_dir(self.pid) / "canvas.json"

    def _load_positions(self) -> Dict[str, Tuple[float, float]]:
        if not self.pid: return {}
        f = self._positions_file()
        if not f.exists(): return {}
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return {k: tuple(v) for k, v in data.items()
                    if isinstance(v, (list, tuple)) and len(v) == 2}
        except Exception:
            return {}

    def _save_all(self):
        if not self.pid: return
        # 资产节点位置 → canvas.json
        positions = self.canvas.get_asset_positions()
        if positions:
            try:
                self._positions_file().write_text(
                    json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                self.log.emit(f"位置保存失败: {e}")
        # 画布自定义节点 → canvas_items.json
        # 同步当前画布上的 TextNode/GeneratorNode 的 canvas_item 到列表
        active_items = []
        for node in self.canvas._nodes_by_id.values():
            if isinstance(node, (TextNode, GeneratorNode)):
                active_items.append(node.canvas_item)
        if active_items or self._canvas_items:
            try:
                ST.save_canvas_items(self.pid, active_items)
                self._canvas_items = active_items
            except Exception as e:
                self.log.emit(f"画布项保存失败: {e}")

    # ---- autosave ----
    def _mark_dirty(self):
        """收到 canvas.dirty_changed → 重启 2s debounce 定时器,
        同时刷新状态指示器为'未保存…'。_refresh 期间 _loading=True 直接忽略。"""
        if not getattr(self, "pid", None): return
        if getattr(self, "_loading", False): return  # 加载阶段 add_node 触发的不算用户操作
        if hasattr(self, "_save_status_label"):
            self._save_status_label.setText("✏ 未保存…")
            self._save_status_label.setStyleSheet(
                "color: #d97706; font-size: 12px; padding: 0 8px;"
            )
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.start()  # restart → debounce

    def _do_autosave(self):
        """定时器回调:真正落盘 + 刷新指示器。"""
        if not getattr(self, "pid", None): return
        self._save_all()
        if hasattr(self, "_save_status_label"):
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            self._save_status_label.setText(f"💾 已保存 {ts}")
            self._save_status_label.setStyleSheet(
                "color: #16a34a; font-size: 12px; padding: 0 8px;"
            )

    def _save_all_immediate(self):
        """用户点'立即保存'按钮 → 取消 debounce 直接存。"""
        if hasattr(self, "_autosave_timer"):
            self._autosave_timer.stop()
        self._do_autosave()

    # ---- 上传图片/视频到画布 ----
    def _upload_media_at(self, scene_pos, paths=None):
        """把本地图片/视频导入到项目资产并放到画布上。
        - paths=None:打开文件对话框让用户选
        - paths=[...]:直接用给定的文件列表(从 OS 拖入时用)
        scene_pos 为 None 时,放到当前视口中央。"""
        if not self.pid:
            self.log.emit("请先选项目再上传"); return
        if paths is None:
            files, _ = QFileDialog.getOpenFileNames(
                self, "选图片或视频(支持多选)", "",
                "媒体 (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.mp4 *.mov *.webm *.avi *.mkv);;"
                "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp);;"
                "视频 (*.mp4 *.mov *.webm *.avi *.mkv);;"
                "所有 (*)",
            )
        else:
            # 过滤掉非媒体文件(用户可能拖一堆乱七八糟进来)
            VALID_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                         ".mp4", ".mov", ".webm", ".avi", ".mkv"}
            from pathlib import Path
            files = [p for p in paths if Path(p).suffix.lower() in VALID_EXT]
            ignored = len(paths) - len(files)
            if ignored:
                self.log.emit(f"忽略 {ignored} 个非图片/视频文件")
        if not files: return
        # 起点:scene_pos 或视口中央
        if scene_pos is None:
            try:
                center = self.canvas.viewport().rect().center()
                scene_pos = self.canvas.mapToScene(center)
            except Exception:
                scene_pos = QPointF(0, 0)
        from pathlib import Path
        ok_count = 0
        for i, fp in enumerate(files):
            try:
                p = Path(fp)
                if not p.exists():
                    self.log.emit(f"⚠ 文件不存在: {fp}"); continue
                # 导入到项目 assets/
                rel = ST.import_asset(self.pid, p)
                ext = p.suffix.lower()
                is_video = ext in (".mp4", ".mov", ".webm", ".avi", ".mkv")
                # 简单网格排布:每行 4 个,横向 280px,纵向 200px
                x = scene_pos.x() + (i % 4) * 280
                y = scene_pos.y() + (i // 4) * 200
                item = CanvasItem(
                    kind=CANVAS_VIDEO if is_video else CANVAS_IMAGE,
                    project_id=self.pid,
                    title=p.stem[:30],
                    x=x, y=y,
                    status="done",
                    result_file=rel,
                    prompt="(本地上传)",
                    task_type="video" if is_video else "image",
                    backend_id="",
                )
                # canvas 上 image/video 都用 GeneratorNode 渲染(reload 路径也是这样,
                # 见 _refresh 里 item.kind in (CANVAS_GENERATOR, CANVAS_IMAGE, CANVAS_VIDEO))。
                # VideoNode 是资源库节点,签名跟这边不匹配,别用。
                node = GeneratorNode(item)
                self.canvas.add_node(node, QPointF(x, y))
                ok_count += 1
            except Exception as e:
                self.log.emit(f"上传 {fp} 失败: {e}")
        if ok_count:
            self.log.emit(f"已上传 {ok_count}/{len(files)} 个文件到画布")
            self._save_all_immediate()  # 上传是显式操作,立刻存

    # ---- 新增节点 ----
    def _add_generator_at(self, scene_pos: QPointF):
        """空白处放新生成器节点 — 弹对话框设置 prompt。"""
        item = CanvasItem(
            kind=CANVAS_GENERATOR, project_id=self.pid,
            x=scene_pos.x(), y=scene_pos.y(),
        )
        dlg = GeneratorDialog(self, item)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        item = dlg.commit()
        if not item.prompt.strip():
            self.log.emit("prompt 为空,已取消"); return

        # 入队
        item.status = "queued"
        node = GeneratorNode(item)
        self.canvas.add_node(node, scene_pos)

        from .task_queue import get_queue
        from .playwright_worker import get_worker
        # 自动识别参考图:看有没有连线指向此节点(角色卡 / 上传图 / 已生成图)
        refs = self._resolve_incoming_references(item.id)
        if refs:
            self.log.emit(
                f"自动识别到 {len(refs)} 张参考图(连线传入): "
                f"{[Path(p).name for p in refs]}"
            )
        task = GenerationTask(
            project_id=self.pid,
            task_type=item.task_type,
            backend_id=item.backend_id,
            title=item.title or "画布生成",
            prompt=item.prompt,
            reference_images=refs,
            target_kind="canvas_item",
            target_id=item.id,
        )
        item.task_id = task.id
        get_queue().enqueue(task)
        worker = get_worker()
        if worker.is_available() and not worker._running:
            worker.start()
        self._save_all()
        self.log.emit(f"画布生成已入队: {item.title or '(无标题)'}")

    def _add_text_at(self, scene_pos: QPointF):
        text, ok = QInputDialog.getText(self, "新增文本节点", "文本内容:")
        if not ok or not text.strip(): return
        item = CanvasItem(
            kind=CANVAS_TEXT, project_id=self.pid,
            x=scene_pos.x(), y=scene_pos.y(),
            text=text.strip(),
        )
        node = TextNode(item)
        self.canvas.add_node(node, scene_pos)
        self._save_all()

    # ---- 交互回调 ----
    def _on_node_dclick(self, kind: str, node_id: str):
        if self.owner and hasattr(self.owner, "open_asset"):
            self.owner.open_asset(kind, node_id)

    def _on_node_action(self, action: str, kind: str, node_id: str):
        if action == "copy_path":
            node = self.canvas._nodes_by_id.get(node_id)
            if isinstance(node, VideoNode):
                QApplication.clipboard().setText(str(node.video_path.absolute()))
                self.log.emit(f"已复制路径: {node.video_path.name}")
            return
        if action == "preview_image":
            # 收集画布上所有已完成图片节点,做成 (title, abs_path) 列表
            items = []
            target_idx = 0
            for n in self.canvas._nodes_by_id.values():
                if not isinstance(n, GeneratorNode): continue
                ci = n.canvas_item
                if not (ci.status == "done" and ci.result_file
                        and ci.task_type != "video"):
                    continue
                p = ST.asset_full_path(self.pid, ci.result_file)
                if not p.exists(): continue
                title = ci.title or Path(ci.result_file).name
                if n.node_id == node_id:
                    target_idx = len(items)
                items.append((title, str(p)))
            if not items:
                self.log.emit("没有可预览的图片"); return
            dlg = ImagePreviewDialog(self, items, start_idx=target_idx)
            dlg.exec()
            return
        if action == "edit_text":
            node = self.canvas._nodes_by_id.get(node_id)
            if isinstance(node, TextNode):
                cur = node.canvas_item.text
                text, ok = QInputDialog.getMultiLineText(
                    self, "编辑文本", "文本内容:", cur)
                if ok:
                    node.set_text(text.strip())
                    self._save_all()
            return
        if action == "edit_generator":
            node = self.canvas._nodes_by_id.get(node_id)
            if isinstance(node, GeneratorNode):
                if node.canvas_item.status in ("queued", "running"):
                    self.log.emit("正在生成中,稍候")
                    return
                dlg = GeneratorDialog(self, node.canvas_item)
                if dlg.exec() != QDialog.DialogCode.Accepted: return
                item = dlg.commit()
                # 重新入队
                from .task_queue import get_queue
                from .playwright_worker import get_worker
                item.status = "queued"
                item.result_file = ""
                item.error = ""
                # 重新跑也要识别一遍参考图(用户中间可能新连了线)
                refs = self._resolve_incoming_references(item.id)
                if refs:
                    self.log.emit(
                        f"重生成时识别到 {len(refs)} 张参考图: "
                        f"{[Path(p).name for p in refs]}"
                    )
                task = GenerationTask(
                    project_id=self.pid,
                    task_type=item.task_type,
                    backend_id=item.backend_id,
                    title=item.title or "画布生成",
                    prompt=item.prompt,
                    reference_images=refs,
                    target_kind="canvas_item",
                    target_id=item.id,
                )
                item.task_id = task.id
                node._render()  # 刷新节点显示
                get_queue().enqueue(task)
                w = get_worker()
                if w.is_available() and not w._running: w.start()
                self._save_all()
                self.log.emit(f"重新生成已入队: {item.title or '(无标题)'}")
            return
        if action == "delete":
            self.canvas.remove_node(node_id)
            self._save_all()
            return
        # 资产节点动作 → 委托 owner
        if self.owner and hasattr(self.owner, "node_action"):
            self.owner.node_action(action, kind, node_id)

    def _on_blank_action(self, action: str, scene_pos: QPointF):
        if action == "new_generator":
            self._add_generator_at(scene_pos)
        elif action == "new_text":
            self._add_text_at(scene_pos)
        elif action == "upload_media":
            self._upload_media_at(scene_pos)

    # ---- 参考图自动识别 ----
    def _resolve_incoming_references(self, node_id: str) -> List[str]:
        """读 manual_links.json,把所有指向 node_id 的入边解析成本地图片绝对路径。

        支持三种来源:
          - AssetNode (character/scene/prop) → asset.reference_image
          - 画布上 status=done 的 CanvasItem(image kind)→ result_file
            (这包括用户上传的图、之前生成完的图)
          - text/video/未完成的生成节点 → 跳过
        返回字符串路径列表(直接喂给 GenerationTask.reference_images)。
        """
        from pathlib import Path
        out: List[str] = []
        seen: set = set()
        f = ST.project_dir(self.pid) / "manual_links.json"
        if not f.exists(): return out
        try:
            links = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return out

        # 预加载资产 / canvas items,避免每条边都重读
        chars = {c.id: c for c in ST.load_characters(self.pid)}
        scenes = {s.id: s for s in ST.load_scenes(self.pid)}
        props  = {p.id: p for p in ST.load_props(self.pid)}
        items  = {it.id: it for it in (ST.load_canvas_items(self.pid) or [])}

        for link in links:
            if link.get("dst") != node_id: continue
            src_id = link.get("src", "")
            if not src_id or src_id in seen: continue
            seen.add(src_id)
            rel = None
            if src_id in chars:
                rel = chars[src_id].reference_image
            elif src_id in scenes:
                rel = scenes[src_id].reference_image
            elif src_id in props:
                rel = props[src_id].reference_image
            elif src_id in items:
                it = items[src_id]
                # 只接已完成的图片;视频不能当参考图;还在跑的也不算数
                if it.status == "done" and it.result_file:
                    if it.kind == CANVAS_IMAGE or it.task_type == "image":
                        rel = it.result_file
            if not rel: continue
            try:
                full = ST.asset_full_path(self.pid, rel)
                if full and Path(full).exists():
                    out.append(str(full))
            except Exception:
                continue
        return out

    # ---- 手动连线 ----
    def _toggle_connect_mode(self, on: bool):
        self.canvas.set_connect_mode(on)
        if on:
            self.log.emit("连线模式开 — 点节点 A 拖到节点 B 建立引用,再次点按钮关闭")
        else:
            self.log.emit("连线模式关")

    def _on_manual_connection(self, src_id: str, dst_id: str):
        """用户手动连接节点 → 持久化到 manual_links.json"""
        if not self.pid: return
        self.canvas.add_connection(src_id, dst_id)
        f = ST.project_dir(self.pid) / "manual_links.json"
        try:
            existing = []
            if f.exists():
                existing = json.loads(f.read_text(encoding="utf-8"))
            pair = {"src": src_id, "dst": dst_id}
            if pair not in existing:
                existing.append(pair)
                f.write_text(json.dumps(existing, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            self.log.emit(f"已建立手动连线: {src_id[:12]}... → {dst_id[:12]}...")
        except Exception as e:
            self.log.emit(f"手动连线保存失败: {e}")

    # ---- Worker 信号回调 ----
    def _on_task_done(self, task_id: str):
        """worker 完成一个 task → 找到画布上对应的生成器节点更新。"""
        # 通过 task_id 反查 canvas_item
        for node in self.canvas._nodes_by_id.values():
            if not isinstance(node, GeneratorNode): continue
            if node.canvas_item.task_id == task_id:
                # 重新读 canvas_items.json 拿到 result_file
                items = ST.load_canvas_items(self.pid)
                for it in items:
                    if it.id == node.canvas_item.id:
                        node.canvas_item.status = it.status
                        node.canvas_item.result_file = it.result_file
                        node.canvas_item.kind = it.kind
                        node._render()
                        self.log.emit(f"画布节点已更新: {it.title or it.id}")
                        return

    def _on_task_failed(self, task_id: str, error: str):
        for node in self.canvas._nodes_by_id.values():
            if not isinstance(node, GeneratorNode): continue
            if node.canvas_item.task_id == task_id:
                node.update_status("failed", error=error)
                # 持久化
                items = ST.load_canvas_items(self.pid) or []
                found = False
                for it in items:
                    if it.id == node.canvas_item.id:
                        it.status = "failed"
                        it.error = error
                        found = True; break
                if not found:
                    items.append(node.canvas_item)
                ST.save_canvas_items(self.pid, items)
                return
