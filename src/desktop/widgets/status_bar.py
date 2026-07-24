"""IFMStatusBar — شريط حالة مخصص مع مؤشر المراقب والإحصائيات

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStatusBar

from .watcher_indicator import WatcherIndicator


class IFMStatusBar(QStatusBar):
    """شريط حالة IFM

    يعرض:
      - رسالة الحالة العامة (يمين)
      - عدد السجلات + الإجراءات + سجل التراجع (يسار)
      - مؤشر المراقب LED
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)

        # مؤشر المراقب
        self.watcher_indicator = WatcherIndicator(self)
        self.addPermanentWidget(self.watcher_indicator)

        # تسمية الإحصائيات
        self.stats_label = QLabel("0 ملف | 0 إجراء | 0 تراجع")
        self.stats_label.setObjectName("StatsLabel")
        self.addPermanentWidget(self.stats_label)

        # رسالة عامة
        self._message_label = QLabel("جاهز")
        self.addWidget(self._message_label)

    def set_stats(self, files: int, actions: int, undo: int) -> None:
        """يحدّث الإحصائيات المعروضة"""
        self.stats_label.setText(
            f"{files} ملف | {actions} إجراء | {undo} تراجع"
        )

    def set_message(self, message: str) -> None:
        """يحدّث الرسالة العامة"""
        self._message_label.setText(message)

    def set_watcher_state(self, state: str) -> None:
        """يحدّث حالة مؤشر المراقب"""
        self.watcher_indicator.set_state(state)
