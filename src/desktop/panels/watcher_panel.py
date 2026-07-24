"""WatcherPanel — لوحة عرض حالة المراقب + الأحداث المباشرة + السجل

تعرض:
  - زر بدء/إيقاف المراقب
  - قائمة الأحداث المباشرة (مع تحديث لحظي)
  - سجل الدفعات المعالَجة (BatchResult)

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class WatcherPanel(QWidget):
    """لوحة المراقب المباشر

    Signals:
        start_requested(): طلب بدء المراقب
        stop_requested(): طلب إيقاف المراقب
    """

    start_requested = Signal()
    stop_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("مراقب المجلدات")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("راقب المجلدات تلقائيًا — الأحداث تُجمَّع وتُعالَج بأمان (auto dry-run)")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── صندوق التحكم ──────────────────────────────────────────────
        control_box = QGroupBox("التحكم بالمراقب")
        control_layout = QHBoxLayout(control_box)

        self.start_btn = QPushButton("▶ بدء المراقبة")
        self.start_btn.setProperty("primary", True)
        self.start_btn.clicked.connect(self.start_requested.emit)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■ إيقاف")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        control_layout.addWidget(self.stop_btn)

        self.status_label = QLabel("متوقف")
        self.status_label.setStyleSheet("color: #656d76; font-size: 12px;")
        control_layout.addWidget(self.status_label, stretch=1)

        layout.addWidget(control_box)

        # ─── Splitter للأحداث + السجل ─────────────────────────────────
        splitter = QSplitter(Qt.Vertical)

        # الأحداث المباشرة
        events_box = QGroupBox("الأحداث المباشرة")
        events_layout = QVBoxLayout(events_box)
        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(["الوقت", "النوع", "الملف", "الحالة"])
        self.events_table.setAlternatingRowColors(True)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.events_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.events_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        events_layout.addWidget(self.events_table)
        splitter.addWidget(events_box)

        # سجل الدفعات
        history_box = QGroupBox("سجل الدفعات المعالَجة")
        history_layout = QVBoxLayout(history_box)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels([
            "وقت البدء", "عدد الأحداث", "ملفات مُفهرسة", "إجراءات مخطّطة", "الحالة",
        ])
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        history_layout.addWidget(self.history_table)
        splitter.addWidget(history_box)

        splitter.setSizes([300, 200])
        layout.addWidget(splitter, stretch=1)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_running(self, running: bool) -> None:
        """يحدّث حالة الواجهة حسب حالة المراقب"""
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.status_label.setText("يعمل ●" if running else "متوقف")
        self.status_label.setStyleSheet(
            f"color: {'#3fb950' if running else '#656d76'}; font-size: 12px; font-weight: 600;"
        )

    def add_event(self, event_type: str, file_path: str) -> None:
        """يضيف حدثًا جديدًا في أعلى جدول الأحداث المباشرة"""
        # الحد الأقصى 200 حدث (للأداء)
        if self.events_table.rowCount() >= 200:
            self.events_table.removeRow(self.events_table.rowCount() - 1)
        # إدراج في الأعلى
        self.events_table.insertRow(0)
        from datetime import datetime
        self.events_table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self.events_table.setItem(0, 1, QTableWidgetItem(event_type))
        self.events_table.setItem(0, 2, QTableWidgetItem(file_path))
        self.events_table.setItem(0, 3, QTableWidgetItem("معلَّق"))

    def mark_event_processed(self, row: int, success: bool = True) -> None:
        """يحدّث حالة حدث بعد المعالجة"""
        if 0 <= row < self.events_table.rowCount():
            status_text = "✓ معالَج" if success else "✗ فشل"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.darkGreen if success else Qt.red)
            self.events_table.setItem(row, 3, status_item)

    def set_history(self, history: list) -> None:
        """يملأ سجل الدفعات"""
        self.history_table.setRowCount(0)
        for batch in history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(batch.started_at or ""))
            self.history_table.setItem(row, 1, QTableWidgetItem(str(batch.events_count)))
            self.history_table.setItem(row, 2, QTableWidgetItem(str(batch.files_scanned)))
            self.history_table.setItem(row, 3, QTableWidgetItem(str(batch.planned_actions)))
            status = "✓ نجح" if not batch.error else f"✗ {batch.error[:30]}"
            status_item = QTableWidgetItem(status)
            status_item.setForeground(Qt.darkGreen if not batch.error else Qt.red)
            self.history_table.setItem(row, 4, status_item)

    def clear_events(self) -> None:
        """يفرّغ جدول الأحداث المباشرة"""
        self.events_table.setRowCount(0)
