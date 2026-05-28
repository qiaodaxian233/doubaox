"""
InfiniteCanvas — 节点式工作台。

把项目里的角色 / 场景 / 道具 / 分镜全部抽成节点扔到 QGraphicsScene 上,
导演把它们摆成自己的故事板布局。节点间(暂时手动连)的引用关系可视化。

技术:
- QGraphicsView + QGraphicsScene (无限尺寸,内置缩放平移)
- 节点是 QGraphicsItemGroup 子类
- 滚轮缩放,中键/空格 + 拖拽平移,左键拖节点
- 节点位置持久化 → ~/.doubao-studio/projects/<pid>/canvas.json
"""
from __future__ import annotations
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import json, math

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
    QSizePolicy, QApplication,
)

from .theme import C
from .widgets import Hline
from . import storage as ST
from .models import Character, Scene, Prop, Episode, Shot


# 节点尺寸
NODE_W = 200
NODE_H = 260
NODE_PADDING = 12
NODE_HEADER_H = 30
THUMB_H = 130
RADIUS = 10


# =========================================================================
class AssetNode(QGraphicsItemGroup):
    """单个资产节点(角色/场景/道具/分镜)。"""

    def __init__(self, node_id: str, kind: str, title: str, subtitle: str,
                 image_path: Optional[Path], color: str = "#1e3a8a"):
        super().__init__()
        self.node_id = node_id
        self.kind = kind       # character / scene / prop / shot / segment / video
        self.title = title
        self.subtitle = subtitle

        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(QCursor(Qt.OpenHandCursor))

        # 背景卡
        self.bg = QGraphicsPathItem(self._rounded_rect_path(0, 0, NODE_W, NODE_H, RADIUS))
        self.bg.setBrush(QBrush(QColor("#ffffff")))
        self.bg.setPen(QPen(QColor(C["border_soft"]), 1))
        self.addToGroup(self.bg)

        # 顶部色条
        self.header = QGraphicsPathItem(
            self._rounded_rect_path(0, 0, NODE_W, NODE_HEADER_H, RADIUS, only_top=True)
        )
        self.header.setBrush(QBrush(QColor(color)))
        self.header.setPen(QPen(Qt.NoPen))
        self.addToGroup(self.header)

        # kind icon (左上)
        icon_map = {
            "character": "👤", "scene": "🏞", "prop": "📿",
            "shot": "🎬", "segment": "🎞", "video": "🎥",
        }
        icon = QGraphicsTextItem(icon_map.get(kind, "•"))
        icon.setDefaultTextColor(QColor("white"))
        icon.setFont(QFont("Inter", 13))
        icon.setPos(8, 4)
        self.addToGroup(icon)

        # title
        self.title_item = QGraphicsTextItem(title)
        self.title_item.setDefaultTextColor(QColor("white"))
        f = QFont("Inter Tight"); f.setPointSize(10); f.setWeight(QFont.DemiBold)
        self.title_item.setFont(f)
        self.title_item.setPos(34, 6)
        self.title_item.setTextWidth(NODE_W - 44)
        self.addToGroup(self.title_item)

        # thumbnail
        thumb_y = NODE_HEADER_H + NODE_PADDING
        if image_path and Path(image_path).exists():
            pm = QPixmap(str(image_path))
            if not pm.isNull():
                pm = pm.scaled(NODE_W - 2 * NODE_PADDING, THUMB_H,
                               Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.thumb = QGraphicsPixmapItem(pm)
                # 居中并裁剪显示区域(用 path 蒙版)
                clip_w = NODE_W - 2 * NODE_PADDING
                clip_h = THUMB_H
                self.thumb.setPos(NODE_PADDING - max(0, (pm.width() - clip_w)) // 2,
                                   thumb_y - max(0, (pm.height() - clip_h)) // 2)
                # 用 clip 做圆角
                clip = QGraphicsPathItem(self._rounded_rect_path(
                    NODE_PADDING, thumb_y, clip_w, clip_h, 6))
                clip.setBrush(QBrush(QColor("#ffffff")))
                clip.setPen(QPen(QColor(C["border_soft"]), 1))
                self.addToGroup(clip)
                self.addToGroup(self.thumb)
        else:
            # 占位
            placeholder = QGraphicsPathItem(self._rounded_rect_path(
                NODE_PADDING, thumb_y, NODE_W - 2 * NODE_PADDING, THUMB_H, 6))
            placeholder.setBrush(QBrush(QColor(C["surface_alt"])))
            placeholder.setPen(QPen(QColor(C["border_soft"]), 1))
            self.addToGroup(placeholder)
            ph_text = QGraphicsTextItem("(无图)")
            ph_text.setDefaultTextColor(QColor(C["muted"]))
            ph_text.setFont(QFont("Inter", 9))
            tr = ph_text.boundingRect()
            ph_text.setPos(NODE_W / 2 - tr.width() / 2,
                           thumb_y + THUMB_H / 2 - tr.height() / 2)
            self.addToGroup(ph_text)

        # subtitle
        sub_y = thumb_y + THUMB_H + 10
        sub = QGraphicsTextItem(subtitle)
        sub.setDefaultTextColor(QColor(C["ink_soft"]))
        sub.setFont(QFont("Inter", 9))
        sub.setPos(NODE_PADDING, sub_y)
        sub.setTextWidth(NODE_W - 2 * NODE_PADDING)
        self.addToGroup(sub)

        # 选中描边
        self._selected_outline = QGraphicsPathItem(
            self._rounded_rect_path(-2, -2, NODE_W + 4, NODE_H + 4, RADIUS + 2))
        self._selected_outline.setBrush(QBrush(Qt.NoBrush))
        self._selected_outline.setPen(QPen(QColor(C["accent"]), 2))
        self._selected_outline.setVisible(False)
        self.addToGroup(self._selected_outline)

    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, NODE_W + 4, NODE_H + 4)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._selected_outline.setVisible(bool(value))
        return super().itemChange(change, value)

    @staticmethod
    def _rounded_rect_path(x: float, y: float, w: float, h: float,
                           r: float, only_top: bool = False) -> QPainterPath:
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
class CanvasView(QGraphicsView):
    """无限画布视图。"""

    node_double_clicked = Signal(str, str)   # (kind, node_id)
    node_action         = Signal(str, str, str)   # (action_name, kind, node_id)
    log                 = Signal(str)

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

        # 巨大 scene(虚拟无限)
        self.scene_ = QGraphicsScene(-5000, -5000, 10000, 10000)
        self.setScene(self.scene_)

        self._panning = False
        self._pan_start: QPointF = QPointF()
        self._zoom = 1.0
        self._nodes_by_id: Dict[str, AssetNode] = {}

        # 绘制网格背景
        self._draw_grid()

    def _draw_grid(self):
        """背景网格(40px 一格淡线,200px 一格深线)"""
        # 用 background scene draw 而不是 item — 性能更好
        pass  # 实现在 drawBackground 里

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        # 细网格
        pen_light = QPen(QColor("#eeeeee"), 0)
        painter.setPen(pen_light)
        step = 40
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += step
        # 粗网格
        pen_strong = QPen(QColor("#e0e0e0"), 0)
        painter.setPen(pen_strong)
        step_b = 200
        left_b = int(rect.left()) - (int(rect.left()) % step_b)
        top_b = int(rect.top()) - (int(rect.top()) % step_b)
        x = left_b
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += step_b
        y = top_b
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += step_b

    # ---- 平移:中键拖 / 空格拖 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or \
           (e.button() == Qt.LeftButton and (e.modifiers() & Qt.ControlModifier)):
            self._panning = True
            self._pan_start = e.position()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panning:
            delta = e.position() - self._pan_start
            self._pan_start = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta.y()))
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.setCursor(QCursor(Qt.ArrowCursor))
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        item = self.itemAt(e.position().toPoint())
        # 找到顶层 AssetNode
        node = self._find_node(item)
        if node:
            self.node_double_clicked.emit(node.kind, node.node_id)
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        item = self.itemAt(e.pos())
        node = self._find_node(item)
        if not node:
            # 空白处右键 → 整体菜单
            menu = QMenu(self)
            menu.addAction("🎯 适配所有节点", self.fit_all)
            menu.addAction("🔍 重置缩放 (100%)", self.reset_zoom)
            menu.exec(e.globalPos())
            return
        # 节点右键
        menu = QMenu(self)
        menu.addAction(f"📋 复制 {node.title} 的 prompt",
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

    def _find_node(self, item) -> Optional[AssetNode]:
        while item:
            if isinstance(item, AssetNode): return item
            item = item.parentItem()
        return None

    # ---- 滚轮缩放 ----
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
        if not self._nodes_by_id:
            return
        rect = None
        for node in self._nodes_by_id.values():
            r = node.sceneBoundingRect()
            rect = r if rect is None else rect.united(r)
        if rect:
            rect = rect.adjusted(-50, -50, 50, 50)
            self.fitInView(rect, Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

    # ---- 节点管理 ----
    def add_node(self, node: AssetNode, pos: QPointF):
        self.scene_.addItem(node)
        node.setPos(pos)
        self._nodes_by_id[node.node_id] = node

    def clear_nodes(self):
        for node in list(self._nodes_by_id.values()):
            self.scene_.removeItem(node)
        self._nodes_by_id.clear()

    def get_positions(self) -> Dict[str, Tuple[float, float]]:
        return {nid: (n.scenePos().x(), n.scenePos().y())
                for nid, n in self._nodes_by_id.items()}


# =========================================================================
class InfiniteCanvasView(QFrame):
    """画布 tab 的容器:工具栏 + CanvasView。"""

    log = Signal(str)

    def __init__(self, owner=None):
        super().__init__()
        self.setObjectName("PanelAlt")
        self.owner = owner
        self.pid: Optional[str] = None

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # 工具栏
        tb = QFrame(); tb.setObjectName("Panel")
        tbl = QHBoxLayout(tb); tbl.setContentsMargins(28, 16, 28, 14); tbl.setSpacing(8)
        title = QLabel("无限画布"); title.setObjectName("H2")
        tbl.addWidget(title)
        sub = QLabel("拖动节点 · 滚轮缩放 · 中键 / Ctrl+左键 平移 · 右键节点出菜单")
        sub.setStyleSheet(f"color: {C['muted']}; font-size: 10.5px; margin-left: 8px;")
        tbl.addWidget(sub)
        tbl.addStretch()

        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setObjectName("Subtle")
        refresh_btn.setCursor(QCursor(Qt.PointingHandCursor))
        refresh_btn.clicked.connect(self._refresh)
        tbl.addWidget(refresh_btn)

        fit_btn = QPushButton("🎯 全览")
        fit_btn.setObjectName("Subtle")
        fit_btn.clicked.connect(lambda: self.canvas.fit_all())
        tbl.addWidget(fit_btn)

        reset_btn = QPushButton("🔍 100%")
        reset_btn.setObjectName("Subtle")
        reset_btn.clicked.connect(lambda: self.canvas.reset_zoom())
        tbl.addWidget(reset_btn)

        auto_btn = QPushButton("📐 自动布局")
        auto_btn.setObjectName("Subtle")
        auto_btn.setToolTip("按类型分区自动摆放节点")
        auto_btn.clicked.connect(self._auto_layout)
        tbl.addWidget(auto_btn)

        save_btn = QPushButton("💾 保存位置")
        save_btn.setObjectName("Subtle")
        save_btn.setToolTip("把当前节点位置存到项目")
        save_btn.clicked.connect(self._save_positions)
        tbl.addWidget(save_btn)

        root.addWidget(tb); root.addWidget(Hline())

        # 画布
        self.canvas = CanvasView()
        self.canvas.node_double_clicked.connect(self._on_node_dclick)
        self.canvas.node_action.connect(self._on_node_action)
        self.canvas.log.connect(self.log)
        root.addWidget(self.canvas, 1)

        # 自动保存定时器(每 8 秒保存一次位置)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(8000)
        self._autosave_timer.timeout.connect(self._save_positions)
        self._autosave_timer.start()

    def load(self, pid: str):
        self.pid = pid
        self._refresh()

    def _refresh(self):
        if not self.pid:
            self.canvas.clear_nodes(); return
        self.canvas.clear_nodes()

        positions = self._load_positions()
        nodes_to_add = []   # (node_id, AssetNode)

        # 颜色按类型分
        kind_colors = {
            "character": "#7c3aed",   # 紫
            "scene":     "#0d9488",   # 青
            "prop":      "#b45309",   # 棕
            "shot":      "#dc5a3a",   # 珊瑚
            "segment":   "#1e3a8a",   # 深蓝
        }

        # 角色
        for c in ST.load_characters(self.pid):
            img = ST.asset_full_path(self.pid, c.reference_image) if c.reference_image else None
            sub = f"{c.role or ''}  {c.placeholder or ''}".strip()
            node = AssetNode(c.id, "character", c.name, sub, img,
                             color=kind_colors["character"])
            nodes_to_add.append(node)

        # 场景
        for s in ST.load_scenes(self.pid):
            img = ST.asset_full_path(self.pid, s.reference_image) if s.reference_image else None
            sub = s.placeholder or s.visual_style or ""
            node = AssetNode(s.id, "scene", s.name, sub, img,
                             color=kind_colors["scene"])
            nodes_to_add.append(node)

        # 道具
        for p in ST.load_props(self.pid):
            img = ST.asset_full_path(self.pid, p.reference_image) if p.reference_image else None
            sub = p.placeholder or (p.description[:40] if p.description else "")
            node = AssetNode(p.id, "prop", p.name, sub, img,
                             color=kind_colors["prop"])
            nodes_to_add.append(node)

        # 分镜(每个 episode 的每个 shot)
        for ep in ST.list_episodes(self.pid):
            for shot in ep.shots:
                img = ST.asset_full_path(self.pid, shot.generated_image) if shot.generated_image else None
                title = f"分镜 #{shot.number}"
                sub_parts = [shot.shot_size or "", shot.camera_movement or "",
                             f"{shot.duration}s"]
                if shot.action: sub_parts.append(shot.action[:25])
                sub = "  ".join(filter(None, sub_parts))
                node = AssetNode(shot.id, "shot", title, sub, img,
                                 color=kind_colors["shot"])
                nodes_to_add.append(node)

        if not nodes_to_add:
            self.log.emit("画布为空 — 先在角色/场景/分镜表里建几个对象")
            return

        # 摆放节点:有保存位置的用保存位置,否则用自动布局
        for node in nodes_to_add:
            if node.node_id in positions:
                x, y = positions[node.node_id]
                self.canvas.add_node(node, QPointF(x, y))
            else:
                # 暂存,稍后自动布局
                self.canvas.add_node(node, QPointF(0, 0))

        # 没存过位置的,触发一次自动布局把没安置的散开
        unplaced = [n for n in nodes_to_add if n.node_id not in positions]
        if unplaced:
            self._auto_layout(target_nodes=unplaced)

        self.canvas.fit_all()
        self.log.emit(f"画布加载 {len(nodes_to_add)} 个节点")

    def _auto_layout(self, target_nodes: List[AssetNode] = None):
        """按 kind 分区:
        角色横排上 / 场景下一行 / 道具再下一行 / 分镜按集分行
        """
        if not self.pid: return
        nodes = target_nodes or list(self.canvas._nodes_by_id.values())
        if not nodes: return

        cols = 4
        x_step = NODE_W + 30
        y_step = NODE_H + 40

        by_kind = {"character": [], "scene": [], "prop": [], "shot": [], "segment": []}
        for n in nodes:
            if n.kind in by_kind: by_kind[n.kind].append(n)

        kind_order = ["character", "scene", "prop", "shot", "segment"]
        cur_y = 0
        for kind in kind_order:
            group = by_kind[kind]
            if not group: continue
            for i, node in enumerate(group):
                col = i % cols
                row = i // cols
                node.setPos(col * x_step, cur_y + row * y_step)
            rows = math.ceil(len(group) / cols)
            cur_y += rows * y_step + 80   # 分组间距

        self.canvas.fit_all()
        self.log.emit("自动布局已应用")

    # ---- 位置持久化 ----
    def _positions_file(self) -> Path:
        return ST.project_dir(self.pid) / "canvas.json"

    def _load_positions(self) -> Dict[str, Tuple[float, float]]:
        if not self.pid: return {}
        f = self._positions_file()
        if not f.exists(): return {}
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return {k: tuple(v) for k, v in data.items() if isinstance(v, (list, tuple)) and len(v) == 2}
        except Exception:
            return {}

    def _save_positions(self):
        if not self.pid: return
        positions = self.canvas.get_positions()
        if not positions: return
        try:
            self._positions_file().write_text(
                json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.log.emit(f"画布位置保存失败: {e}")

    # ---- 节点交互 ----
    def _on_node_dclick(self, kind: str, node_id: str):
        """双击节点 → 跳到对应资产编辑器(通过 owner 信号通知 ProjectNavigator)"""
        if self.owner and hasattr(self.owner, "open_asset"):
            self.owner.open_asset(kind, node_id)

    def _on_node_action(self, action: str, kind: str, node_id: str):
        """右键菜单动作。"""
        if self.owner and hasattr(self.owner, "node_action"):
            self.owner.node_action(action, kind, node_id)
        else:
            self.log.emit(f"动作 {action} 触发于 {kind} {node_id}")
