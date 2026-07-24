"""سمات IFM — Light + Dark + RTL Arabic

هذه الوحدة توفر:
  - LIGHT_QSS / DARK_QSS: أوراق أنماط Qt جاهزة
  - apply_theme(app, mode): تطبيق السمة على QApplication
  - toggle_theme(app): تبديل بين فاتح/داكن
  - RTL support عبر setLayoutDirection(Qt.RightToLeft)

التصميم:
  - ألوان مستوحاة من تصميم Material 3 مع لمسة عربية (Noto Sans Arabic)
  - دعم كامل للوضع الداكن مع تباين كافٍ للقراءة
  - حدود ناعمة (border-radius 6px) ومسافات مريحة
  - لا AI، لا medical — فقط CSS

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# ─── ثوابت الألوان ─────────────────────────────────────────────────────────

# لوحة فاتحة (Light)
LIGHT_PALETTE = {
    "bg": "#f7f8fa",
    "surface": "#ffffff",
    "surface_alt": "#f0f2f5",
    "text": "#1f2328",
    "text_muted": "#656d76",
    "border": "#d0d7de",
    "accent": "#0969da",
    "accent_hover": "#0860c5",
    "ok": "#1a7f37",
    "ok_bg": "#dafbe1",
    "warn": "#9a6700",
    "warn_bg": "#fff8c5",
    "err": "#d1242f",
    "err_bg": "#ffebe9",
    "sidebar_bg": "#1f2328",
    "sidebar_text": "#e6edf3",
    "sidebar_active": "#2f353d",
}

# لوحة داكنة (Dark)
DARK_PALETTE = {
    "bg": "#0d1117",
    "surface": "#161b22",
    "surface_alt": "#21262d",
    "text": "#e6edf3",
    "text_muted": "#8b949e",
    "border": "#30363d",
    "accent": "#58a6ff",
    "accent_hover": "#79b8ff",
    "ok": "#3fb950",
    "ok_bg": "#1c3a26",
    "warn": "#d29922",
    "warn_bg": "#3a2f1c",
    "err": "#f85149",
    "err_bg": "#3a1c1c",
    "sidebar_bg": "#010409",
    "sidebar_text": "#e6edf3",
    "sidebar_active": "#1c2330",
}


def _build_qss(p: dict) -> str:
    """يبني ورقة أنماط Qt من قاموس ألوان"""
    return f"""
QWidget {{
    background-color: {p['bg']};
    color: {p['text']};
    font-family: "Noto Sans Arabic", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {p['bg']};
}}

/* ─── Sidebar ──────────────────────────────────── */
#Sidebar {{
    background-color: {p['sidebar_bg']};
    color: {p['sidebar_text']};
    border: none;
    border-left: 1px solid {p['border']};
}}
#Sidebar QLabel {{
    color: {p['sidebar_text']};
    background: transparent;
    font-size: 16px;
    font-weight: 600;
    padding: 16px 20px 8px 20px;
}}
QPushButton[navButton="true"] {{
    background: transparent;
    color: {p['sidebar_text']};
    border: none;
    text-align: right;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton[navButton="true"]:hover {{
    background-color: {p['sidebar_active']};
}}
QPushButton[navButton="true"][active="true"] {{
    background-color: {p['sidebar_active']};
    border-right: 3px solid {p['accent']};
}}

/* ─── Central panel ────────────────────────────── */
QStackedWidget {{
    background-color: {p['bg']};
    border: none;
}}

/* ─── Headers ──────────────────────────────────── */
QLabel#PanelTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {p['text']};
    padding: 8px 0;
}}
QLabel#PanelSubtitle {{
    font-size: 13px;
    color: {p['text_muted']};
    padding-bottom: 12px;
}}

/* ─── Buttons ──────────────────────────────────── */
QPushButton {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    min-height: 18px;
}}
QPushButton:hover {{
    border-color: {p['accent']};
    background-color: {p['surface_alt']};
}}
QPushButton:pressed {{
    background-color: {p['border']};
}}
QPushButton:disabled {{
    color: {p['text_muted']};
    background-color: {p['surface_alt']};
    border-color: {p['border']};
}}
QPushButton[primary="true"] {{
    background-color: {p['accent']};
    color: #ffffff;
    border: 1px solid {p['accent']};
}}
QPushButton[primary="true"]:hover {{
    background-color: {p['accent_hover']};
    border-color: {p['accent_hover']};
}}
QPushButton[danger="true"] {{
    background-color: {p['err_bg']};
    color: {p['err']};
    border: 1px solid {p['err']};
}}
QPushButton[danger="true"]:hover {{
    background-color: {p['err']};
    color: #ffffff;
}}

/* ─── Inputs ───────────────────────────────────── */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {p['accent']};
    selection-color: #ffffff;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {p['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['surface']};
    color: {p['text']};
    selection-background-color: {p['accent']};
    selection-color: #ffffff;
    border: 1px solid {p['border']};
}}

/* ─── Tables ───────────────────────────────────── */
QTableWidget {{
    background-color: {p['surface']};
    alternate-background-color: {p['surface_alt']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    gridline-color: {p['border']};
    selection-background-color: {p['accent']};
    selection-color: #ffffff;
}}
QTableWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {p['border']};
}}
QHeaderView::section {{
    background-color: {p['surface_alt']};
    color: {p['text']};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {p['border']};
    border-right: 1px solid {p['border']};
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {p['surface_alt']};
    border: none;
    border-bottom: 1px solid {p['border']};
}}

/* ─── Tabs ─────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {p['surface_alt']};
    color: {p['text_muted']};
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid {p['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background-color: {p['surface']};
    color: {p['text']};
    border-bottom: 2px solid {p['accent']};
}}
QTabBar::tab:hover:!selected {{
    color: {p['text']};
}}

/* ─── Status bar ───────────────────────────────── */
QStatusBar {{
    background-color: {p['surface_alt']};
    color: {p['text_muted']};
    border-top: 1px solid {p['border']};
}}
QStatusBar QLabel {{
    color: {p['text_muted']};
    padding: 0 12px;
}}
QStatusBar #WatcherIndicator {{
    padding: 2px 10px;
    border-radius: 10px;
    font-weight: 600;
}}

/* ─── Group boxes ──────────────────────────────── */
QGroupBox {{
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top right;
    padding: 0 8px;
    color: {p['text_muted']};
}}

/* ─── Scroll bars ──────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['text_muted']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ─── Progress bar ─────────────────────────────── */
QProgressBar {{
    background-color: {p['surface_alt']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    text-align: center;
    color: {p['text']};
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {p['accent']};
    border-radius: 5px;
}}

/* ─── Tooltips ─────────────────────────────────── */
QToolTip {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 4px;
    padding: 4px 8px;
}}

/* ─── Menu bar ─────────────────────────────────── */
QMenuBar {{
    background-color: {p['surface_alt']};
    color: {p['text']};
    border-bottom: 1px solid {p['border']};
}}
QMenuBar::item:selected {{
    background-color: {p['accent']};
    color: #ffffff;
}}
QMenu {{
    background-color: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['border']};
}}
QMenu::item:selected {{
    background-color: {p['accent']};
    color: #ffffff;
}}
"""


LIGHT_QSS = _build_qss(LIGHT_PALETTE)
DARK_QSS = _build_qss(DARK_PALETTE)


# ─── واجهة عامة ────────────────────────────────────────────────────────────

ThemeMode = Literal["light", "dark"]


def apply_theme(app: QApplication, mode: ThemeMode = "dark") -> None:
    """يطبّق السمة على QApplication

    Args:
        app: QApplication instance
        mode: "light" أو "dark"
    """
    qss = DARK_QSS if mode == "dark" else LIGHT_QSS
    app.setStyleSheet(qss)

    # ضبط لوحة الألوان الأساسية (QPalette) لضمان توافق الرسومات
    palette = QPalette()
    p = DARK_PALETTE if mode == "dark" else LIGHT_PALETTE
    palette.setColor(QPalette.Window, QColor(p["bg"]))
    palette.setColor(QPalette.WindowText, QColor(p["text"]))
    palette.setColor(QPalette.Base, QColor(p["surface"]))
    palette.setColor(QPalette.AlternateBase, QColor(p["surface_alt"]))
    palette.setColor(QPalette.Text, QColor(p["text"]))
    palette.setColor(QPalette.Button, QColor(p["surface"]))
    palette.setColor(QPalette.ButtonText, QColor(p["text"]))
    palette.setColor(QPalette.Highlight, QColor(p["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)


def apply_rtl(app: QApplication) -> None:
    """يضبط اتجاه الواجهة إلى RTL (يمين-إلى-يسار) للعربية"""
    app.setLayoutDirection(Qt.RightToLeft)


def toggle_theme(app: QApplication) -> ThemeMode:
    """يبدّل بين الوضع الفاتح والداكن

    Returns:
        الوضع الجديد بعد التبديل
    """
    current = app.property("ifm_theme") or "dark"
    new_mode: ThemeMode = "light" if current == "dark" else "dark"
    apply_theme(app, new_mode)
    app.setProperty("ifm_theme", new_mode)
    return new_mode


def init_app_theme(app: QApplication, mode: ThemeMode = "dark", rtl: bool = True) -> None:
    """تهيئة كاملة: السمة + RTL + الخط الافتراضي

    Args:
        app: QApplication instance
        mode: "light" أو "dark"
        rtl: True لتشغيل RTL للعربية
    """
    # خط افتراضي يدعم العربية
    font = QFont("Noto Sans Arabic", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    apply_theme(app, mode)
    app.setProperty("ifm_theme", mode)
    if rtl:
        apply_rtl(app)
