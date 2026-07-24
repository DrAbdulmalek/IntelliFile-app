"""UndoLogPanel — لوحة عرض سجل التراجع + أزرار undo

تعرض:
  - جدول بكل UndoEntry (وقت، قاعدة، نوع الإجراء، الملف، بعد، حالة)
  - زر تراجع عن الأخير + زر تراجع عن الكل

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class UndoLogPanel(QWidget):
    """لوحة سجل التراجع

    Signals:
        undo_last_requested(): طلب التراجع عن آخر إجراء
        undo_all_requested(): طلب التراجع عن كل الإجراءات
    """

    undo_last_requested = Signal()
    undo_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("سجل التراجع")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("كل إجراء منفّذ قابل للتراجع — اختر 'تراجع عن الأخير' أو 'تراجع عن الكل'")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── شريط الأدوات ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.undo_last_btn = QPushButton("↩ تراجع عن الأخير")
        self.undo_last_btn.setProperty("primary", True)
        self.undo_last_btn.setEnabled(False)
        self.undo_last_btn.clicked.connect(self._on_undo_last)
        toolbar.addWidget(self.undo_last_btn)

        self.undo_all_btn = QPushButton("↩↩ تراجع عن الكل")
        self.undo_all_btn.setProperty("danger", True)
        self.undo_all_btn.setEnabled(False)
        self.undo_all_btn.clicked.connect(self._on_undo_all)
        toolbar.addWidget(self.undo_all_btn)

        toolbar.addStretch(1)

        self.count_label = QLabel("0 إجراء")
        self.count_label.setStyleSheet("color: #656d76; font-size: 12px;")
        toolbar.addWidget(self.count_label)

        layout.addLayout(toolbar)

        # ─── جدول الإجراءات ───────────────────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "الوقت", "القاعدة", "نوع الإجراء", "الملف", "بعد النقل", "الحالة", "ملاحظات",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_undo_last(self) -> None:
        reply = QMessageBox.question(
            self, "تأكيد التراجع",
            "هل تريد التراجع عن آخر إجراء؟",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.undo_last_btn.setEnabled(False)
            self.undo_last_requested.emit()

    def _on_undo_all(self) -> None:
        reply = QMessageBox.question(
            self, "تأكيد التراجع الكلي",
            "هل تريد التراجع عن كل الإجراءات؟\n"
            "هذا الإجراء لا يمكن التراجع عنه.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.undo_all_btn.setEnabled(False)
            self.undo_all_requested.emit()

    # ─── Public API ────────────────────────────────────────────────────────

    def set_entries(self, entries: list) -> None:
        """يملأ الجدول بقائمة UndoEntry"""
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry.timestamp or ""))
            self.table.setItem(row, 1, QTableWidgetItem(entry.rule_name or ""))
            self.table.setItem(row, 2, QTableWidgetItem(entry.action_type or ""))
            self.table.setItem(row, 3, QTableWidgetItem(entry.file_path or ""))
            self.table.setItem(row, 4, QTableWidgetItem(entry.file_path_after or ""))
            status_text = "✓ نجح" if entry.success else "✗ فشل"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.darkGreen if entry.success else Qt.red)
            self.table.setItem(row, 5, status_item)
            self.table.setItem(row, 6, QTableWidgetItem(entry.error_message or ""))

        # تفعيل/تعطيل الأزرار
        has_entries = len(entries) > 0
        self.undo_last_btn.setEnabled(has_entries)
        self.undo_all_btn.setEnabled(has_entries)
        self.count_label.setText(f"{len(entries)} إجراء")

    def set_undo_result(self, success: bool, message: str = "") -> None:
        """يعرض نتيجة عملية التراجع"""
        if not success and message:
            QMessageBox.warning(self, "فشل التراجع", message)
        # أعد تفعيل الأزرار حسب الحالة
        has_entries = self.table.rowCount() > 0
        self.undo_last_btn.setEnabled(has_entries)
        self.undo_all_btn.setEnabled(has_entries)
