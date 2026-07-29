"""ActionLogPanel — لوحة عرض سجل الإجراءات المرئي

تعرض:
  - جدول بكل الإجراءات (وقت، نوع، قاعدة، ملف، حالة، مصدر)
  - أزرار تصفية (نجاح/فشل، حسب المصدر)
  - تصدير JSON + HTML

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ActionLogPanel(QWidget):
    """لوحة عرض سجل الإجراءات

    Signals:
        export_json_requested(str): طلب تصدير JSON إلى مسار
        export_html_requested(str): طلب تصدير HTML إلى مسار
        clear_requested(): طلب تفريغ السجل
    """

    export_json_requested = Signal(str)
    export_html_requested = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("سجل الإجراءات")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("كل إجراءات IFM مسجّلة هنا — تصدير JSON/HTML للمراجعة")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── شريط الأدوات ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # تصفية حسب النجاح
        self.success_filter = QComboBox()
        self.success_filter.addItems(["الكل", "ناجح فقط", "فاشل فقط"])
        self.success_filter.currentIndexChanged.connect(self._refilter)
        toolbar.addWidget(QLabel("الحالة:"))
        toolbar.addWidget(self.success_filter)

        # تصفية حسب المصدر
        self.source_filter = QComboBox()
        self.source_filter.addItems(["الكل", "rule_engine", "watcher", "manual", "undo_rollback"])
        self.source_filter.currentIndexChanged.connect(self._refilter)
        toolbar.addWidget(QLabel("المصدر:"))
        toolbar.addWidget(self.source_filter)

        toolbar.addStretch(1)

        # أزرار التصدير
        export_json_btn = QPushButton("تصدير JSON")
        export_json_btn.clicked.connect(self._on_export_json)
        toolbar.addWidget(export_json_btn)

        export_html_btn = QPushButton("تصدير HTML")
        export_html_btn.clicked.connect(self._on_export_html)
        toolbar.addWidget(export_html_btn)

        clear_btn = QPushButton("تفريغ")
        clear_btn.setProperty("danger", True)
        clear_btn.clicked.connect(self._on_clear)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # ─── ملخص ──────────────────────────────────────────────────────
        self.summary_label = QLabel("لا إجراءات بعد")
        self.summary_label.setStyleSheet("color: #656d76; font-size: 12px;")
        layout.addWidget(self.summary_label)

        # ─── جدول الإجراءات ───────────────────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "الوقت", "النوع", "القاعدة", "الملف", "بعد", "الحالة", "المصدر",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, stretch=1)

        # تخزين كل الإجراءات للتصفية
        self._all_entries: list = []

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ سجل الإجراءات (JSON)", "action_log.json", "JSON files (*.json)"
        )
        if path:
            self.export_json_requested.emit(path)

    def _on_export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "حفظ سجل الإجراءات (HTML)", "action_log.html", "HTML files (*.html)"
        )
        if path:
            self.export_html_requested.emit(path)

    def _on_clear(self) -> None:
        self.clear_requested.emit()

    def _refilter(self) -> None:
        """يعيد تطبيق التصفية على الجدول"""
        success_idx = self.success_filter.currentIndex()
        source_text = self.source_filter.currentText()

        self.table.setRowCount(0)
        for entry in self._all_entries:
            # تصفية النجاح
            if success_idx == 1 and not entry.success:
                continue
            if success_idx == 2 and entry.success:
                continue
            # تصفية المصدر
            if source_text != "الكل" and entry.source != source_text:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry.timestamp or ""))
            self.table.setItem(row, 1, QTableWidgetItem(entry.action_type or ""))
            self.table.setItem(row, 2, QTableWidgetItem(entry.rule_name or ""))
            self.table.setItem(row, 3, QTableWidgetItem(entry.file_path or ""))
            self.table.setItem(row, 4, QTableWidgetItem(entry.file_path_after or ""))
            status_text = "✓ نجح" if entry.success else "✗ فشل"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.darkGreen if entry.success else Qt.red)
            self.table.setItem(row, 5, status_item)
            self.table.setItem(row, 6, QTableWidgetItem(entry.source or ""))

    # ─── Public API ────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """يضع قائمة كاملة من ActionLogEntry ويعرضها"""
        self._all_entries = list(entries)
        self._refilter()
        # ملخص
        success_count = sum(1 for e in entries if e.success)
        fail_count = len(entries) - success_count
        self.summary_label.setText(
            f"📊 {len(entries)} إجراء | ✓ {success_count} نجح | ✗ {fail_count} فشل"
        )

    def add_entry(self, entry) -> None:
        """يضيف إجراءً جديدًا للعرض (للتحديث المباشر)"""
        self._all_entries.insert(0, entry)
        self._refilter()
        success_count = sum(1 for e in self._all_entries if e.success)
        fail_count = len(self._all_entries) - success_count
        self.summary_label.setText(
            f"📊 {len(self._all_entries)} إجراء | ✓ {success_count} نجح | ✗ {fail_count} فشل"
        )

    def clear_view(self) -> None:
        """يفرّغ الجدول"""
        self._all_entries = []
        self.table.setRowCount(0)
        self.summary_label.setText("لا إجراءات بعد")
