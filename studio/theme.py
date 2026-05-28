"""颜色、字体、QSS。集中管理,UI 模块只 import 不重复定义。"""

C = {
    "bg":          "#faf9f5",
    "surface":     "#ffffff",
    "surface_alt": "#f4f3ee",
    "ink":         "#0a0a0a",
    "ink_soft":    "#3f3f46",
    "muted":       "#71717a",
    "border":      "#e7e5e0",
    "border_soft": "#efede8",
    "accent":      "#dc5a3a",       # 深珊瑚
    "accent_soft": "#fef3ee",
    "online":      "#16a34a",
    "warning":     "#f59e0b",
    "danger":      "#dc2626",
    "info":        "#0369a1",
}

PALETTE = ["#1e3a8a", "#dc5a3a", "#15803d", "#7c3aed",
           "#be185d", "#0d9488", "#b45309", "#0369a1"]

SANS  = '"Inter Tight", "PingFang SC", "Microsoft YaHei UI", "Segoe UI", sans-serif'
SERIF = '"Fraunces", "Source Han Serif SC", "Songti SC", "STSong", serif'
MONO  = '"JetBrains Mono", "SF Mono", "Consolas", monospace'


def build_stylesheet() -> str:
    return f"""
    QWidget {{
        background: {C['bg']}; color: {C['ink']};
        font-family: {SANS};
        font-size: 13px;
    }}
    QFrame#Panel    {{ background: {C['surface']}; }}
    QFrame#PanelAlt {{ background: {C['surface_alt']}; }}
    QFrame#Card {{
        background: {C['surface']};
        border: 1px solid {C['border_soft']};
        border-radius: 8px;
    }}
    QFrame#CardSelected {{
        background: {C['surface_alt']};
        border: 1px solid {C['ink']};
        border-radius: 8px;
    }}
    QFrame#CardAccent {{
        background: {C['accent_soft']};
        border: 1px solid {C['accent']};
        border-radius: 8px;
    }}
    QLabel#H1 {{
        font-family: {SERIF};
        font-size: 23px; font-weight: 500; color: {C['ink']};
        letter-spacing: -0.3px;
    }}
    QLabel#H2 {{
        font-family: {SERIF};
        font-size: 17px; font-weight: 500; color: {C['ink']};
    }}
    QLabel#Mono {{
        font-family: {MONO};
        font-size: 10px; letter-spacing: 1px; color: {C['muted']};
    }}
    QLabel#Secondary {{ color: {C['muted']}; font-size: 11px; }}
    QLabel#FieldLabel {{
        color: {C['muted']}; font-size: 10.5px; font-weight: 500;
        font-family: {MONO}; letter-spacing: 0.6px; text-transform: uppercase;
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {C['surface_alt']};
        border: 1px solid {C['border']};
        border-radius: 6px; padding: 6px 10px;
        color: {C['ink']};
        selection-background-color: {C['accent']};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {C['ink']};
    }}
    QComboBox::drop-down {{ border: none; width: 16px; }}
    QComboBox::down-arrow {{ image: none; }}
    QPushButton {{
        background: {C['surface']};
        border: 1px solid {C['border']};
        border-radius: 6px; padding: 6px 12px;
        color: {C['ink_soft']};
    }}
    QPushButton:hover {{ background: {C['surface_alt']}; }}
    QPushButton:disabled {{ color: {C['muted']}; background: {C['surface_alt']}; }}
    QPushButton#Primary {{
        background: {C['ink']}; color: white; border: none;
        padding: 8px 14px; font-weight: 500;
    }}
    QPushButton#Primary:hover {{ background: #2a2a2a; }}
    QPushButton#Accent {{
        background: {C['accent']}; color: white; border: none;
        padding: 6px 14px; font-weight: 500;
    }}
    QPushButton#Accent:hover {{ background: #c44d30; }}
    QPushButton#Accent:disabled {{ background: #e5b8aa; color: white; }}
    QPushButton#Subtle {{
        background: transparent; border: 1px solid {C['border']};
        padding: 4px 10px; font-size: 11px; color: {C['muted']};
    }}
    QPushButton#Subtle:hover {{ background: {C['surface_alt']}; color: {C['ink_soft']}; }}
    QPushButton#TabActive {{
        background: {C['surface']}; border: none; padding: 6px 12px;
        font-weight: 500; color: {C['ink']}; border-radius: 4px;
    }}
    QPushButton#TabInactive {{
        background: transparent; border: none; padding: 6px 12px; color: {C['muted']};
    }}
    QPushButton#TabInactive:hover {{ color: {C['ink_soft']}; }}
    QPushButton#IconOnly {{
        border: none; background: transparent; padding: 4px;
        color: {C['muted']}; font-size: 13px;
    }}
    QPushButton#IconOnly:hover {{ background: {C['surface_alt']}; border-radius: 4px; }}
    QPushButton#Danger {{ color: {C['danger']}; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    QScrollBar:vertical   {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: #d4d4d4; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #a3a3a3; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: #d4d4d4; border-radius: 4px; min-width: 30px; }}
    QSplitter::handle {{ background: {C['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QPlainTextEdit#Log {{
        background: {C['bg']}; border: none;
        border-top: 1px solid {C['border_soft']};
        font-family: {MONO}; font-size: 11px;
        color: {C['ink_soft']}; padding: 6px 12px;
    }}
    QListWidget {{
        background: transparent; border: none; outline: none;
    }}
    QListWidget::item {{
        padding: 8px 10px; border-radius: 6px;
    }}
    QListWidget::item:selected {{
        background: {C['surface_alt']}; color: {C['ink']};
    }}
    QListWidget::item:hover {{ background: {C['border_soft']}; }}
    QTabWidget::pane {{ border: none; background: transparent; }}
    QTabBar::tab {{
        background: transparent; padding: 8px 14px;
        color: {C['muted']}; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {C['ink']}; border-bottom: 2px solid {C['accent']};
    }}
    QHeaderView::section {{
        background: {C['surface_alt']}; color: {C['muted']};
        font-family: {MONO}; font-size: 10px; letter-spacing: 0.5px;
        padding: 6px 8px; border: none;
        border-right: 1px solid {C['border']};
        border-bottom: 1px solid {C['border']};
        text-transform: uppercase;
    }}
    QTableWidget, QTableView {{
        background: {C['surface']}; gridline-color: {C['border_soft']};
        selection-background-color: {C['accent_soft']};
        selection-color: {C['ink']};
    }}
    """
