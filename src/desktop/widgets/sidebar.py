"""Sidebar — قائمة تنقل جانبية لـ IFM MainWindow

Widgets:
  - Sidebar(QWidget): قائمة أزرار تنقل بإشارة nav_clicked(str)

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ─── عناصر التنقل ──────────────────────────────────────────────────────────

NAV_ITEMS = [
    ("inventory", "الجرد", "📁"),
    ("rules", "القواعد والتنفيذ", "⚙"),
    ("action_log", "سجل الإجراءات", "📜"),
    ("undo_log", "سجل التراجع", "↩"),
    ("watcher", "المراقب", "👁"),
]


class Sidebar(QFrame):
    """قائمة تنقل جانبية

    Signal:
        nav_clicked(str): مُعرّف العنصر المُنقر (مثل "inventory")
    """

    nav_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # عنوان التطبيق
        title = QLabel("IntelliFile")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        subtitle = QLabel("منظّم الملفات الذكي")
        subtitle.setObjectName("SidebarSubtitle")
        subtitle.setStyleSheet(
            "color: #8b949e; padding: 0 20px 12px 20px; "
            "font-size: 11px;"
        )
        layout.addWidget(subtitle)

        # أزرار التنقل
        self._buttons: dict[str, QPushButton] = {}
        for nav_id, label, icon in NAV_ITEMS:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setProperty("navButton", True)
            btn.setProperty("active", False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, nid=nav_id: self._on_nav(nid))
            self._buttons[nav_id] = btn
            layout.addWidget(btn)

        # فاصل مرن
        layout.addStretch(1)

        # إصدار في الأسفل
        version_label = QLabel("IFM v1.0 — PR-08")
        version_label.setStyleSheet(
            "color: #6e7681; padding: 12px 20px; font-size: 10px;"
        )
        layout.addWidget(version_label)

        # تعيين العنصر النشط الافتراضي
        self.set_active("inventory")

    def _on_nav(self, nav_id: str) -> None:
        self.set_active(nav_id)
        self.nav_clicked.emit(nav_id)

    def set_active(self, nav_id: str) -> None:
        """يضبط العنصر النشط بصريًا"""
        for nid, btn in self._buttons.items():
            btn.setProperty("active", nid == nav_id)
            # إعادة تطبيق الستايل (dynamic property change)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @property
    def nav_ids(self) -> List[str]:
        return [nid for nid, _, _ in NAV_ITEMS]
