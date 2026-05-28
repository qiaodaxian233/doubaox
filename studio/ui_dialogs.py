"""共用弹窗。"""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QPlainTextEdit, QDialogButtonBox, QFormLayout,
    QFrame, QFileDialog, QMessageBox
)

from .theme import C
from .models import Project, Character, Scene, Prop, Episode, Shot


STYLE_OPTIONS = ["都市言情", "国风仙侠", "校园修仙", "古装宫廷", "悬疑推理",
                 "科幻末日", "情景喜剧", "真人写实", "童年回忆", "其他"]
ASPECT_OPTIONS = ["9:16 竖屏", "16:9 横屏", "1:1 方形", "4:5"]


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建项目")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"QDialog {{ background: {C['surface']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(14)

        title = QLabel("新建短剧项目")
        title.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C['ink']};")
        layout.addWidget(title)

        form = QFormLayout(); form.setSpacing(10); form.setContentsMargins(0, 6, 0, 6)

        self.name = QLineEdit(); self.name.setPlaceholderText("例:雨夜邂逅 / 童年回忆")
        form.addRow("项目名称", self.name)

        self.style = QComboBox(); self.style.addItems(STYLE_OPTIONS); self.style.setEditable(True)
        form.addRow("风格类型", self.style)

        self.aspect = QComboBox(); self.aspect.addItems(ASPECT_OPTIONS)
        form.addRow("画面比例", self.aspect)

        self.duration = QSpinBox()
        self.duration.setRange(10, 600); self.duration.setSingleStep(10)
        self.duration.setValue(60); self.duration.setSuffix(" 秒")
        form.addRow("目标时长", self.duration)

        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText("一句话简介(可选)")
        self.desc.setFixedHeight(70)
        form.addRow("简介", self.desc)

        layout.addLayout(form)

        btns = QDialogButtonBox()
        cancel = btns.addButton("取消", QDialogButtonBox.RejectRole)
        ok = btns.addButton("创建", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary"); ok.setCursor(QCursor(Qt.PointingHandCursor))
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def build_project(self) -> Project:
        return Project(
            name=self.name.text().strip() or "未命名项目",
            style=self.style.currentText().strip(),
            aspect_ratio=self.aspect.currentText().split()[0],  # 取 "9:16" 部分
            target_duration=self.duration.value(),
            description=self.desc.toPlainText().strip(),
        )


class NewEpisodeDialog(QDialog):
    def __init__(self, parent=None, next_number: int = 1):
        super().__init__(parent)
        self.setWindowTitle("新建集")
        self.setMinimumWidth(380)

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)
        title = QLabel("新建一集")
        title.setStyleSheet(f"font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        f = QFormLayout(); f.setSpacing(10)
        self.number = QSpinBox(); self.number.setRange(1, 999); self.number.setValue(next_number)
        f.addRow("集号", self.number)
        self.title = QLineEdit(); self.title.setPlaceholderText("第一集标题")
        f.addRow("标题", self.title)
        self.synopsis = QPlainTextEdit(); self.synopsis.setFixedHeight(60)
        self.synopsis.setPlaceholderText("剧情简介")
        f.addRow("简介", self.synopsis)
        self.arc = QLineEdit(); self.arc.setPlaceholderText("平静 → 惊愕 → 决绝")
        f.addRow("情绪曲线", self.arc)
        l.addLayout(f)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("创建", QDialogButtonBox.AcceptRole); ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def build_episode(self, project_id: str) -> Episode:
        return Episode(
            project_id=project_id,
            number=self.number.value(),
            title=self.title.text().strip() or f"第{self.number.value()}集",
            synopsis=self.synopsis.toPlainText().strip(),
            emotional_arc=self.arc.text().strip(),
        )


# ==================== M3: AI 拆分镜对话框 ====================
class AISplitDialog(QDialog):
    def __init__(self, parent=None, episode=None):
        super().__init__(parent)
        self.setWindowTitle("AI 拆分镜")
        self.setMinimumWidth(560)
        self.episode = episode

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)
        title = QLabel("把剧本扔给 GPT,自动拆分镜")
        title.setStyleSheet("font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        hint = QLabel(
            "GPT 会返回 JSON 分镜表(含 6 维度 + 衔接锚点)。"
            "应用 3-5 镜/段密度规则。"
        )
        hint.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        hint.setWordWrap(True)
        l.addWidget(hint)

        f = QFormLayout(); f.setSpacing(10)
        self.seg_count = QSpinBox(); self.seg_count.setRange(1, 20); self.seg_count.setValue(2)
        self.seg_count.setSuffix(" 段")
        f.addRow("视频段数", self.seg_count)
        self.shots_per_seg = QSpinBox(); self.shots_per_seg.setRange(2, 6); self.shots_per_seg.setValue(4)
        self.shots_per_seg.setSuffix(" 镜/段")
        f.addRow("每段分镜数", self.shots_per_seg)
        l.addLayout(f)

        l.addWidget(QLabel("剧本(中文):"))
        self.script = QPlainTextEdit()
        self.script.setPlaceholderText(
            "示例:陆渊从昏迷中醒来,发现身处废弃矿坑。\n"
            "他的左臂浮现紫金色符文,意识到自己穿越了。\n"
            "走出矿洞,发现远方洛阳城已被异种菌丝吞噬..."
        )
        if episode and episode.synopsis:
            self.script.setPlainText(episode.synopsis)
        self.script.setMinimumHeight(180)
        l.addWidget(self.script)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("发到 GPT 镜像", QDialogButtonBox.AcceptRole); ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def get_result(self):
        return self.script.toPlainText(), self.seg_count.value(), self.shots_per_seg.value()


# ==================== M4: 导出对话框 ====================
class ExportDialog(QDialog):
    def __init__(self, parent=None, project_id="", episode=None):
        super().__init__(parent)
        self.setWindowTitle("导出")
        self.setMinimumWidth(440)
        self.project_id = project_id
        self.episode = episode

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 20); l.setSpacing(14)
        title = QLabel(f"导出:第 {episode.number} 集 - {episode.title or ''}")
        title.setStyleSheet("font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        # 1. PDF 故事板
        pdf_card = QFrame(); pdf_card.setObjectName("Card")
        pl = QVBoxLayout(pdf_card); pl.setContentsMargins(14, 12, 14, 12); pl.setSpacing(4)
        pt = QLabel("📄  PDF 故事板"); pt.setStyleSheet("font-weight: 500;")
        pl.addWidget(pt)
        pd = QLabel(f"输出含每镜参考图 + 6 维度文字的 PDF。共 {len(episode.shots)} 镜。")
        pd.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        pd.setWordWrap(True)
        pl.addWidget(pd)
        pdf_btn = QPushButton("导出 PDF")
        pdf_btn.setObjectName("Primary")
        pdf_btn.clicked.connect(self._export_pdf)
        pl.addWidget(pdf_btn)
        l.addWidget(pdf_card)

        # 2. 视频拼接
        seg_count = sum(1 for s in episode.segments if s.generated_video) if episode.segments else 0
        vid_card = QFrame(); vid_card.setObjectName("Card")
        vl = QVBoxLayout(vid_card); vl.setContentsMargins(14, 12, 14, 12); vl.setSpacing(4)
        vt = QLabel("🎬  视频拼接"); vt.setStyleSheet("font-weight: 500;")
        vl.addWidget(vt)
        vd = QLabel(f"用 ffmpeg 把本集所有 10s 段拼成成片。已生成段数:{seg_count}")
        vd.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        vd.setWordWrap(True)
        vl.addWidget(vd)
        vid_btn = QPushButton("拼接视频")
        vid_btn.setObjectName("Primary")
        vid_btn.setEnabled(seg_count > 0)
        vid_btn.clicked.connect(self._export_video)
        vl.addWidget(vid_btn)
        l.addWidget(vid_card)

        # 关闭
        b = QDialogButtonBox()
        b.addButton("关闭", QDialogButtonBox.RejectRole)
        b.rejected.connect(self.reject)
        l.addWidget(b)

    def _export_pdf(self):
        from .exporter import export_storyboard_pdf, HAS_REPORTLAB
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 PDF 故事板", f"第{self.episode.number}集_故事板.pdf",
            "PDF (*.pdf);;HTML (*.html)"
        )
        if not path: return
        from pathlib import Path
        try:
            ok = export_storyboard_pdf(self.project_id, self.episode.id, Path(path))
            if ok:
                hint = "" if HAS_REPORTLAB else " (reportlab 未装,自动转为 HTML)"
                QMessageBox.information(self, "导出成功", f"已导出 → {path}{hint}")
            else:
                QMessageBox.warning(self, "导出失败", "导出过程出错,请看日志")
        except Exception as e:
            QMessageBox.critical(self, "异常", str(e))

    def _export_video(self):
        from .exporter import concat_episode, ffmpeg_available
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "缺 ffmpeg",
                "未检测到 ffmpeg。\n"
                "macOS: brew install ffmpeg\n"
                "Ubuntu: sudo apt install ffmpeg\n"
                "Windows: 下载 ffmpeg.exe 加入 PATH"
            ); return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存拼接视频", f"第{self.episode.number}集.mp4", "MP4 (*.mp4)"
        )
        if not path: return
        from pathlib import Path
        try:
            ok = concat_episode(self.project_id, self.episode.id, Path(path), crossfade_seconds=0.0)
            if ok:
                QMessageBox.information(self, "拼接完成", f"已生成 → {path}")
            else:
                QMessageBox.warning(self, "失败", "ffmpeg 拼接失败,可能是片段编码参数不一致")
        except Exception as e:
            QMessageBox.critical(self, "异常", str(e))
