"""Sidebar — قائمة تنقل جانبية لـ IFM MainWindow

Widgets:
  - Sidebar(QWidget): قائمة أزرار تنقل بإشارة nav_clicked(str)

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

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
    ("inventory", "الجرد", "📁", "عرض الملفات المفهرسة (Ctrl+R للتحديث)"),
    ("preview", "المعاينة", "🔍", "معاينة محتوى الملف المحدّد (Ctrl+P)"),
    ("rules", "القواعد والتنفيذ", "⚙", "قواعد التنظيم + محاكاة + تنفيذ"),
    ("action_log", "سجل الإجراءات", "📜", "سجل مرئي للإجراءات المنفّذة + تصدير"),
    ("undo_log", "سجل التراجع", "↩", "تراجع عن آخر إجراء أو الكل (Ctrl+Z)"),
    ("watcher", "المراقب", "👁", "مراقبة مباشرة لتغيّرات المجلد"),
    ("settings", "الإعدادات", "🔧", "إعدادات التطبيق (Ctrl+,)"),
    ("plugins", "المكونات الإضافية", "🧩", "إدارة المكونات المُكتشفة (Phase E)"),
]


class Sidebar(QFrame):
    """قائمة تنقل جانبية

    Signal:
        nav_clicked(str): مُعرّف العنصر المُنقر (مثل "inventory")
    """

    nav_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None):
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
        for nav_id, label, icon, tooltip in NAV_ITEMS:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setProperty("navButton", True)
            btn.setProperty("active", False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setStatusTip(tooltip)
            btn.setWhatsThis(tooltip)
            btn.clicked.connect(lambda checked=False, nid=nav_id: self._on_nav(nid))
            self._buttons[nav_id] = btn
            layout.addWidget(btn)

        # فاصل مرن
        layout.addStretch(1)

        # إصدار في الأسفل
        version_label = QLabel("IFM v2.2.0 — PR-10")
        version_label.setStyleSheet(
            "color: #6e7681; padding: 12px 20px; font-size: 10px;"
        )
        version_label.setToolTip("إصدار IntelliFile — Phase C مكتملة")
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
    def nav_ids(self) -> list[str]:
        return [nid for nid, _, _, _ in NAV_ITEMS]

    def get_button(self, nav_id: str) -> QPushButton | None:
        """يُرجع زر التنقّل لـ nav_id (للاختبارات + tab order)."""
        return self._buttons.get(nav_id)
