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
        self.setMinimumWidth(640)
        self.episode = episode

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)
        title = QLabel("把剧本扔给 GPT,自动拆分镜")
        title.setStyleSheet("font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        # 醒目的硬约束提示 — 豆包 10s/段 + 3-5 镜/段 + 5 段/账号/天
        hint = QLabel(
            "<b>豆包硬约束:</b><br>"
            "• 每段视频 <b>10 秒</b>(seedance 硬上限)<br>"
            "• 每段 <b>3-5 镜</b>(超 5 镜豆包会赶工、漏镜)<br>"
            "• 每账号每天 <b>5 段额度 = 50 秒成片</b>(超了下一天再来,或开多账号)<br>"
            "<span style='color:#888;'>"
            "若剧本内容过密,优先<b>多分几段</b>(每段 10s),<b>不要</b>往单段塞镜。"
            "</span>"
        )
        hint.setStyleSheet(
            "background: #fef3c7; border: 1px solid #fbbf24; border-radius: 6px; "
            "padding: 10px 12px; font-size: 12px;"
        )
        hint.setWordWrap(True)
        l.addWidget(hint)

        # 取当前豆包账号剩余额度,实时算"还能拍几段"
        from . import storage as ST
        try:
            accs = [a for a in ST.load_accounts()
                    if a.backend_id == "doubao" and getattr(a, "enabled", True)]
            total_left = sum(
                (a.daily_quota_total - (a.daily_quota_used or 0))
                if not a.is_unlimited() else 999
                for a in accs
            )
            n_unl = sum(1 for a in accs if a.is_unlimited())
            quota_txt = (
                f"📊 当前 {len(accs)} 个豆包账号" +
                (f"(含 {n_unl} 个无限)" if n_unl else "") +
                f",今日剩余总额度 <b>{total_left}</b> 段 ≈ "
                f"<b>{total_left * 10}s</b> 成片"
            )
        except Exception:
            quota_txt = "📊 (无法读取账号额度)"
        quota_label = QLabel(quota_txt)
        quota_label.setStyleSheet("color: #16a34a; font-size: 12px; padding: 0 4px;")
        l.addWidget(quota_label)

        f = QFormLayout(); f.setSpacing(10)
        # 默认 5 段(对齐 1 账号上限);用户可改少不可超总剩余(setRange 软提示用)
        self.seg_count = QSpinBox(); self.seg_count.setRange(1, 30); self.seg_count.setValue(5)
        self.seg_count.setSuffix(" 段")
        self.seg_count.setToolTip("视频段数 — 每段 10s。1 账号 5 段 = 50s 成片;多账号可串联更长")
        f.addRow("视频段数", self.seg_count)
        self.shots_per_seg = QSpinBox(); self.shots_per_seg.setRange(3, 5); self.shots_per_seg.setValue(4)
        self.shots_per_seg.setSuffix(" 镜/段")
        self.shots_per_seg.setToolTip("每段 3-5 镜,超过 5 豆包会赶工漏镜")
        f.addRow("每段分镜数", self.shots_per_seg)

        # 实时总长预览 + 配额对比
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #374151; font-size: 12px; padding: 4px 0;")
        f.addRow("📐 预计", self.summary_label)
        l.addLayout(f)

        def _update_summary():
            segs = self.seg_count.value()
            shots = self.shots_per_seg.value()
            total_shots = segs * shots
            total_sec = segs * 10
            warn = ""
            try:
                if total_left < segs and total_left < 999:
                    warn = (f" <span style='color:#dc2626;'>"
                            f"⚠ 超今日剩余({total_left} 段),会有 {segs - total_left} 段排队等明天或新账号"
                            f"</span>")
            except Exception: pass
            self.summary_label.setText(
                f"{segs} 段 × 10s = <b>{total_sec}s</b> 成片,共 <b>{total_shots}</b> 镜{warn}"
            )
        self.seg_count.valueChanged.connect(_update_summary)
        self.shots_per_seg.valueChanged.connect(_update_summary)
        _update_summary()

        l.addWidget(QLabel("剧本(中文):"))
        self.script = QPlainTextEdit()
        self.script.setPlaceholderText(
            "示例:陆渊从昏迷中醒来,发现身处废弃矿坑。\n"
            "他的左臂浮现紫金色符文,意识到自己穿越了。\n"
            "走出矿洞,发现远方洛阳城已被异种菌丝吞噬..."
        )
        # 优先用 episode.script(导入剧本文档写入的);为空再退到 synopsis
        if episode:
            if episode.script:
                self.script.setPlainText(episode.script)
            elif episode.synopsis:
                self.script.setPlainText(episode.synopsis)
        self.script.setMinimumHeight(200)
        l.addWidget(self.script)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("发到 GPT 镜像", QDialogButtonBox.AcceptRole); ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def get_result(self):
        return self.script.toPlainText(), self.seg_count.value(), self.shots_per_seg.value()


class ContinueEpisodeDialog(QDialog):
    """续写下一集 — 收集用户对本集的方向意图和'不能揭露什么'。"""

    def __init__(self, parent=None, pid: str = ""):
        super().__init__(parent)
        self.setWindowTitle("📖 续写下一集")
        self.setMinimumWidth(640)
        self.pid = pid

        l = QVBoxLayout(self); l.setContentsMargins(24, 22, 24, 18); l.setSpacing(12)

        title = QLabel("续写下一集 — 电影级连续剧模式")
        title.setStyleSheet("font-size: 16px; font-weight: 500;")
        l.addWidget(title)

        # 已完成集 + 配额预览
        from . import storage as ST
        eps = ST.list_episodes(pid) if pid else []
        next_num = (max([e.number for e in eps], default=0)) + 1

        try:
            accs = [a for a in ST.load_accounts()
                    if a.backend_id == "doubao" and getattr(a, "enabled", True)]
            total_left = sum(
                (a.daily_quota_total - (a.daily_quota_used or 0))
                if not a.is_unlimited() else 999
                for a in accs
            )
        except Exception:
            total_left = 999

        info = QLabel(
            f"<b>项目已有 {len(eps)} 集</b>。即将生成第 <b>{next_num}</b> 集。<br>"
            f"豆包账号今日剩余 <b>{total_left}</b> 段 ≈ "
            f"<b>{total_left * 10}s</b> 视频额度。"
        )
        info.setStyleSheet(
            "background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; "
            "padding: 8px 12px; font-size: 12px;"
        )
        info.setWordWrap(True)
        l.addWidget(info)

        f = QFormLayout(); f.setSpacing(10)
        # 时长目标 — 电影级 2-5 分钟,默认 120s
        self.duration = QSpinBox()
        self.duration.setRange(20, 600); self.duration.setValue(120); self.duration.setSingleStep(10)
        self.duration.setSuffix(" 秒成片")
        self.duration.setToolTip(
            "电影级单集建议 60-300 秒。20s 是最短(约 2 段视频),"
            "GPT 会按此目标确定本集应有多少 10s 段"
        )
        f.addRow("本集时长目标", self.duration)
        l.addLayout(f)

        l.addWidget(QLabel("🎯 本集走向意图(可空,空就让 GPT 顺着弧线推):"))
        self.brief = QPlainTextEdit()
        self.brief.setPlaceholderText(
            "例如:\n"
            "- 主角觉醒第二种法则,但代价是失去某段记忆\n"
            "- 引入新势力 X,首脑出场,与主角发生冲突\n"
            "- 节奏放缓,本集主要做角色 A 的回忆铺垫"
        )
        self.brief.setMinimumHeight(110)
        l.addWidget(self.brief)

        l.addWidget(QLabel("🚫 本集禁止揭露的悬念(可空,但建议明确写):"))
        self.forbidden = QPlainTextEdit()
        self.forbidden.setPlaceholderText(
            "例如(每行一条):\n"
            "- 主角真实身份(铺到第 8 集才揭)\n"
            "- 反派 X 真正动机(第 5 集前装普通配角)\n"
            "- 神器的最终力量(只在大结局展示)"
        )
        # 预填:从世界圣经里找 ⏳ 行
        try:
            wb = ST.load_world_bible(pid) if pid else ""
            hints = [ln.strip() for ln in wb.split("\n")
                     if ln.strip().startswith("- ⏳")]
            if hints:
                self.forbidden.setPlainText("\n".join(hints))
        except Exception: pass
        self.forbidden.setMinimumHeight(90)
        l.addWidget(self.forbidden)

        b = QDialogButtonBox()
        b.addButton("取消", QDialogButtonBox.RejectRole)
        ok = b.addButton("📖 派给 GPT 续写", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        b.accepted.connect(self.accept); b.rejected.connect(self.reject)
        l.addWidget(b)

    def get_result(self):
        return (
            self.brief.toPlainText().strip(),
            self.forbidden.toPlainText().strip(),
            self.duration.value(),
        )


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

        # 2. 视频拼接 — segment 优先,fallback 到 shot.generated_video
        seg_count = sum(1 for s in episode.segments if s.generated_video) if episode.segments else 0
        if seg_count == 0:
            seg_count = sum(1 for s in episode.shots if s.generated_video)
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

        # 3. 剪映工程导出
        jy_card = QFrame(); jy_card.setObjectName("Card")
        jl = QVBoxLayout(jy_card); jl.setContentsMargins(14, 12, 14, 12); jl.setSpacing(4)
        jt = QLabel("🎞  剪映工程"); jt.setStyleSheet("font-weight: 500;")
        jl.addWidget(jt)
        jd = QLabel(
            f"生成剪映 draft 草稿目录。每个 segment 上视频轨道,共 {seg_count} 段。\n"
            f"⚠ 剪映 6+ 加密 draft 文件;推荐剪映 5.9 及以下打开"
        )
        jd.setStyleSheet(f"color: {C['muted']}; font-size: 11px;")
        jd.setWordWrap(True)
        jl.addWidget(jd)
        jy_btn = QPushButton("导出剪映工程")
        jy_btn.setObjectName("Primary")
        jy_btn.setEnabled(seg_count > 0)
        jy_btn.clicked.connect(self._export_jianying)
        jl.addWidget(jy_btn)
        l.addWidget(jy_card)

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

    def _export_jianying(self):
        from .exporter import export_jianying_draft, jianying_draft_folder, HAS_PYJYDRAFT
        from pathlib import Path

        # 默认目录:剪映草稿位置(若存在)否则桌面
        default_parent = jianying_draft_folder()
        if not default_parent:
            default_parent = Path.home() / "Desktop"
        default_name = f"doubaox-第{self.episode.number}集-{int(__import__('time').time())}"
        suggested = str(default_parent / default_name)

        path = QFileDialog.getExistingDirectory(
            self, "选择剪映「草稿」目录的父目录(里面会建一个新草稿目录)",
            str(default_parent),
        )
        if not path: return
        output_dir = Path(path) / default_name

        try:
            ok = export_jianying_draft(
                self.project_id, self.episode.id, output_dir,
                width=1920, height=1080,
            )
            if not ok:
                QMessageBox.warning(
                    self, "失败",
                    "没找到任何已生成视频可导出。\n请先生成 segment 视频或 shot 视频"
                ); return
            # 提示
            backend = "pyJianYingDraft" if HAS_PYJYDRAFT else "手写 JSON"
            jy_path = jianying_draft_folder()
            tip = ""
            if jy_path:
                tip = f"\n\n剪映草稿目录:\n  {jy_path}\n复制 {output_dir.name} 整个目录进去,启动剪映即可看到"
            else:
                tip = "\n\n未自动检测到剪映草稿目录。\n请手动复制到:\n  macOS: ~/Movies/JianyingPro/User Data/Projects/com.lveditor.draft/\n  Windows: %APPDATA%/JianyingPro/User Data/Projects/com.lveditor.draft/"
            QMessageBox.information(
                self, "剪映工程导出成功",
                f"已生成({backend}):\n{output_dir}{tip}"
            )
        except Exception as e:
            QMessageBox.critical(self, "异常", str(e))
