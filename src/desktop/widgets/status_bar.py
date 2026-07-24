"""IFMStatusBar — شريط حالة مخصص مع مؤشر المراقب والإحصائيات + شريط التقدّم + الأخطاء

يعرض:
  - رسالة الحالة العامة (يمين)
  - عدد السجلات + الإجراءات + سجل التراجع
  - مؤشر المراقب LED
  - ProgressManager (شريط تقدّم قابل للإلغاء) — PR-09
  - ErrorReporter (عدّاد الأخطاء) — PR-09

PR-08 من development-roadmap-v1.0 (IFM Phase C)
PR-09 من development-roadmap-v1.0 (progress + error reporting)
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar

from .error_reporter import ErrorReporter
from .progress_manager import ProgressManager
from .watcher_indicator import WatcherIndicator


class IFMStatusBar(QStatusBar):
    """شريط حالة IFM

    يعرض:
      - رسالة الحالة العامة (يمين)
      - عدد السجلات + الإجراءات + سجل التراجع (يسار)
      - مؤشر المراقب LED
      - شريط تقدّم قابل للإلغاء (ProgressManager)
      - عدّاد أخطاء (ErrorReporter)
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

        # عدّاد الأخطاء (PR-09)
        self.error_reporter = ErrorReporter(self)
        self.addPermanentWidget(self.error_reporter)

        # شريط التقدّم القابل للإلغاء (PR-09)
        self.progress_manager = ProgressManager(self)
        self.addPermanentWidget(self.progress_manager)

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
