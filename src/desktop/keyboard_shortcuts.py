"""اختصارات لوحة المفاتيح العامة لـ IFM Desktop (PR-10).

يوفّر `ShortcutManager` اختصارات موحّدة على مستوى التطبيق:

  - Ctrl+R        — تحديث العرض الحالي
  - F5            — فحص المجلد الحالي
  - Ctrl+Z        — التراجع عن آخر إجراء
  - Ctrl+F        — تركيز البحث في اللوحة الحالية
  - Ctrl+,        — فتح لوحة الإعدادات
  - Ctrl+P        — فتح لوحة المعاينة
  - Ctrl+T        — تبديل السمة (داكن/فاتح)
  - Esc           — إلغاء العملية الجارية

التصميم:
  - كل اختصار يصدر إشارة مستقلة، MainWindow يربطها بالـ slots المناسبة
  - يمكن تفعيل/تعطيل أي اختصار عبر `set_shortcut_enabled`
  - يعمل على مستوى التطبيق (Qt.ApplicationShortcut)

PR-10 من development-roadmap-v1.0 (Desktop polish + release checklist)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

# قائمة الاختصارات (تُستخدم للاختبارات والتوثيق)
SHORTCUTS: list[tuple[str, str, str]] = [
    ("Ctrl+R", "refresh_requested", "تحديث"),
    ("F5", "scan_requested", "فحص مجلد"),
    ("Ctrl+Z", "undo_requested", "تراجع"),
    ("Ctrl+F", "search_requested", "بحث"),
    ("Ctrl+,", "settings_requested", "إعدادات"),
    ("Ctrl+P", "preview_requested", "معاينة"),
    ("Ctrl+T", "toggle_theme_requested", "تبديل السمة"),
    ("Esc", "cancel_requested", "إلغاء"),
]


class ShortcutManager(QObject):
    """يدير اختصارات لوحة المفاتيح العامة لـ IFM Desktop."""

    # إشارات مستقلة لكل إجراء
    refresh_requested = Signal()
    scan_requested = Signal()
    undo_requested = Signal()
    search_requested = Signal()
    settings_requested = Signal()
    preview_requested = Signal()
    toggle_theme_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._window = parent_window
        self._shortcuts: list[QShortcut] = []
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """تسجيل كل الاختصارات العامة."""
        signal_by_name = {
            "refresh_requested": self.refresh_requested,
            "scan_requested": self.scan_requested,
            "undo_requested": self.undo_requested,
            "search_requested": self.search_requested,
            "settings_requested": self.settings_requested,
            "preview_requested": self.preview_requested,
            "toggle_theme_requested": self.toggle_theme_requested,
            "cancel_requested": self.cancel_requested,
        }

        for seq, signal_name, tooltip in SHORTCUTS:
            shortcut = QShortcut(QKeySequence(seq), self._window)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(signal_by_name[signal_name].emit)
            shortcut.setWhatsThis(tooltip)
            self._shortcuts.append(shortcut)

    def set_shortcut_enabled(self, seq: str, enabled: bool) -> None:
        """تفعيل/تعطيل اختصار معيّن حسب تسلسله النصّي."""
        for sc in self._shortcuts:
            if sc.key().toString() == seq:
                sc.setEnabled(enabled)
                return
        raise KeyError(f"لا اختصار بالتسلسل: {seq}")

    def get_shortcut_count(self) -> int:
        """عدد الاختصارات المسجّلة (للاختبارات)."""
        return len(self._shortcuts)

    def get_shortcuts_info(self) -> list[dict]:
        """قائمة معلومات الاختصارات (للتوثيق ولوحة المساعدة)."""
        return [
            {
                "sequence": sc.key().toString(),
                "tooltip": sc.whatsThis(),
                "enabled": sc.isEnabled(),
            }
            for sc in self._shortcuts
        ]
