"""RecentActionsWidget — عرض مختصر لأحدث الإجراءات

يعرض آخر N إجراءً (افتراضيًا 10) من ActionLog في صيغة مختصرة:
  - أيقونة الحالة (✓/✗)
  - نوع الإجراء
  - اسم الملف
  - الوقت النسبي

يُوضع عادةً في الشريط الجانبي أو كجزء من الـ status bar.

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _relative_time(timestamp: str) -> str:
    """يحوّل طابع زمني ISO إلى صيغة نسبية (قبل دقيقة، قبل ساعة، ...)"""
    if not timestamp:
        return "—"
    try:
        # نحاول عدّة صيغ
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                ts = datetime.strptime(timestamp, fmt)
                break
            except ValueError:
                continue
        else:
            return timestamp[:19]
    except Exception:
        return timestamp[:19] if len(timestamp) >= 19 else timestamp

    delta = datetime.now() - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "الآن"
    if seconds < 3600:
        return f"قبل {seconds // 60} دقيقة"
    if seconds < 86400:
        return f"قبل {seconds // 3600} ساعة"
    if seconds < 604800:
        return f"قبل {seconds // 86400} يوم"
    return ts.strftime("%Y-%m-%d %H:%M")


def _action_icon(action_type: str, success: bool) -> str:
    """يرجع أيقونة مناسبة للإجراء"""
    if not success:
        return "✗"
    icon_map = {
        "move": "→",
        "copy": "⎘",
        "tag": "#",
        "untag": "−#",
        "set_category": "🏷",
        "delete_flag": "⚠",
        "rollback": "↩",
    }
    return icon_map.get(action_type, "•")


# ─── RecentActionsWidget ────────────────────────────────────────────────────

class RecentActionsWidget(QFrame):
    """عرض مختصر لأحدث الإجراءات

    Signals:
        action_clicked(int): نُقر إجراء بمعرّف entry_id
        show_all_clicked(): نُقر زر "عرض الكل"
    """

    action_clicked = Signal(int)
    show_all_clicked = Signal()

    def __init__(self, max_items: int = 10, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("RecentActionsWidget")
        self._max_items = max_items
        self._entries: List = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # عنوان
        header = QLabel("آخر الإجراءات")
        header.setStyleSheet("font-weight: 600; font-size: 12px;")
        layout.addWidget(header)

        # قائمة الإجراءات
        self._list = QListWidget()
        self._list.setMaximumHeight(180)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; border: none; }"
            "QListWidget::item { padding: 4px 6px; border-bottom: 1px solid rgba(0,0,0,0.05); }"
            "QListWidget::item:selected { background: rgba(9,105,218,0.1); }"
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        # زر "عرض الكل"
        self._show_all_label = QLabel('<a href="#">عرض الكل في سجل الإجراءات</a>')
        self._show_all_label.setStyleSheet(
            "color: #0969da; font-size: 11px; padding: 4px 6px;"
        )
        self._show_all_label.setCursor(Qt.PointingHandCursor)
        self._show_all_label.mousePressEvent = lambda e: self.show_all_clicked.emit()
        layout.addWidget(self._show_all_label)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """يضع قائمة كاملة من ActionLogEntry ويعرض آخر N منها"""
        # نأخذ آخر N (الأحدث أولًا)
        self._entries = list(entries)[: self._max_items]
        self._refresh()

    def add_entry(self, entry) -> None:
        """يضيف إجراءً جديدًا في أعلى القائمة"""
        self._entries.insert(0, entry)
        if len(self._entries) > self._max_items:
            self._entries = self._entries[: self._max_items]
        self._refresh()

    def clear_view(self) -> None:
        """يفرّغ القائمة"""
        self._entries = []
        self._refresh()

    # ─── Internal ──────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._list.clear()
        for entry in self._entries:
            icon = _action_icon(entry.action_type, entry.success)
            time_str = _relative_time(entry.timestamp)
            file_name = entry.file_name() if hasattr(entry, "file_name") else ""
            text = f"{icon}  [{time_str}]  {entry.action_type}  —  {file_name}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, entry.entry_id)
            # لون حسب النجاح
            if not entry.success:
                item.setForeground(Qt.red)
            elif entry.is_destructive() if hasattr(entry, "is_destructive") else False:
                item.setForeground(Qt.darkYellow)
            self._list.addItem(item)

        # لو لا توجد إجراءات
        if not self._entries:
            empty = QListWidgetItem("لا إجراءات بعد")
            empty.setFlags(empty.flags() & ~Qt.ItemIsEnabled)
            self._list.addItem(empty)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        entry_id = item.data(Qt.UserRole)
        if entry_id is not None and isinstance(entry_id, int):
            self.action_clicked.emit(entry_id)


__all__ = ["RecentActionsWidget"]
