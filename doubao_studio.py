"""
DoubaoStudio v3 - 短剧工厂
=========================
基于"蒙哥 AI"方法论的 AI 短剧分镜与生产流水线工具。

四栏布局:
- 左: 项目导航(项目库 / 角色 / 场景 / 道具 / 分镜表)
- 中: 编辑器(根据左栏选中的 tab 切换视图)
- 右: 制作台(账号配额 / 任务队列 / 素材库)
- 下: 日志栏

M1 范围(本版本):
  ✅ 项目/角色/场景/道具/集/分镜的完整 CRUD
  ✅ 每镜 6 维度 + 衔接锚点 + 自动生成 prompt
  ✅ 内置蒙哥 AI 模板(角色/场景/分镜板/视频)
  ✅ 账号配额面板(5/视频/天)
  ❌ Playwright 自动化生成(M2)
  ❌ AI 自动拆分镜(M3)
  ❌ ffmpeg 拼接 + PDF 导出(M4)

Usage:
  pip install -r requirements.txt
  python doubao_studio.py
"""
from __future__ import annotations
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QPlainTextEdit, QLabel, QFrame, QStatusBar
)

from studio.theme import C, build_stylesheet
from studio.widgets import Hline
from studio.ui_projects import ProjectNavigator
from studio.ui_editor import EditorPanel
from studio.ui_assets import AssetsPanel
from studio import storage as ST


class LogBar(QPlainTextEdit):
    """底部日志栏。"""
    def __init__(self):
        super().__init__()
        self.setObjectName("Log")
        self.setReadOnly(True)
        self.setMaximumBlockCount(500)
        self.setFixedHeight(110)
        from datetime import datetime
        self.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] DoubaoStudio v0.3.0 启动")

    def info(self, msg: str):
        from datetime import datetime
        self.appendPlainText(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DoubaoStudio · 短剧工厂")
        self.resize(1480, 900)
        self.setStyleSheet(build_stylesheet())

        # 中心容器
        center = QWidget(); root = QVBoxLayout(center)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # 主体三栏
        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(1)

        self.nav    = ProjectNavigator()
        self.editor = EditorPanel()
        self.assets = AssetsPanel()

        body.addWidget(self.nav)
        body.addWidget(self.editor)
        body.addWidget(self.assets)
        body.setSizes([280, 840, 360])
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)

        root.addWidget(body, 1)

        # 日志栏
        self.log = LogBar()
        root.addWidget(self.log)

        self.setCentralWidget(center)

        # 状态栏
        sb = QStatusBar()
        sb.setStyleSheet(f"""
            background: {C['surface_alt']}; color: {C['muted']};
            font-family: 'JetBrains Mono', monospace; font-size: 10px;
            border-top: 1px solid {C['border_soft']};
        """)
        sb.showMessage(f"📁 {ST.APP_DIR}")
        self.setStatusBar(sb)

        # 信号连接
        self.nav.project_selected.connect(self._on_project_selected)
        self.nav.tab_changed.connect(self._on_tab_changed)
        self.nav.project_changed.connect(lambda: self.log.info("项目列表已更新"))
        self.editor.log.connect(self.log.info)
        self.assets.log.connect(self.log.info)

        # M2: Worker(可用时才启)
        from studio.playwright_worker import get_worker
        from studio.playwright_session import HAS_PLAYWRIGHT
        self.worker = get_worker()
        self.worker.log.connect(self.log.info)
        if HAS_PLAYWRIGHT:
            self.worker.start()
            self.log.info("✓ Playwright 已就绪 — 任务进队列后自动派发")
        else:
            self.log.info("⚠ Playwright 未安装 — 「🤖 用 GPT 生成」会退化为复制 prompt + 开浏览器手动操作")
            self.log.info("   装好运行: pip install playwright && playwright install chromium")

    def _on_project_selected(self, pid: str):
        if pid:
            self.editor.set_context(pid, "overview")
            self.assets.set_current_project(pid)
            self.log.info(f"打开项目 {pid}")
        else:
            self.editor.set_context(None, "")
            self.assets.set_current_project(None)

    def _on_tab_changed(self, pid: str, tab: str):
        self.editor.set_context(pid, tab)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("DoubaoStudio")

    # 默认字体回退链
    default_font = QFont("Inter Tight, PingFang SC, Microsoft YaHei UI, Segoe UI")
    default_font.setPointSize(10)
    app.setFont(default_font)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
