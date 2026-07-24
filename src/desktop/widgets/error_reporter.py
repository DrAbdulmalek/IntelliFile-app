"""ErrorReporter — جمع وعرض الأخطاء بوضوح

ميزات:
  - يجمع الأخطاء أثناء العمليات (scan, dry_run, execute, watcher)
  - يعرض عدّادًا مرئيًا (badge) في الـ status bar
  - نافذة منبثقة لعرض كل الأخطاء مع التفاصيل
  - إشارة errors_changed(int) عند تغيّر العدد

الاستخدام:
    reporter = ErrorReporter()
    reporter.add_error("فشل الفحص", "تعذّر الوصول إلى /data/secret")
    reporter.add_warning("ملف تالف", "notes.txt")
    reporter.clear()

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ─── Error record ───────────────────────────────────────────────────────────

@dataclass
class ErrorRecord:
    """سجل خطأ واحد"""
    timestamp: str
    severity: str  # "error" | "warning"
    title: str
    message: str
    context: str = ""  # مصدر اختياري (مثل "scan", "execute")

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "context": self.context,
        }


# ─── ErrorReporter (compact badge) ──────────────────────────────────────────

class ErrorReporter(QFrame):
    """مُبلّغ الأخطاء — يعرض عدّادًا + نافذة تفاصيل

    Signals:
        errors_changed(int, int): تغيّر عدد الأخطاء/التحذيرات — (errors, warnings)
    """

    errors_changed = Signal(int, int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ErrorReporter")
        self._records: List[ErrorRecord] = []
        self._max_records = 500  # حد أقصى لمنع التضخّم

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # أيقونة + عدّاد
        self._icon_label = QLabel("✓")
        self._icon_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._icon_label)

        self._count_label = QLabel("0")
        self._count_label.setStyleSheet(
            "background: #1a7f37; color: white; border-radius: 8px; "
            "padding: 1px 6px; font-size: 11px; font-weight: 600;"
        )
        layout.addWidget(self._count_label)

        # زر العرض
        self._show_btn = QPushButton("الأخطاء")
        self._show_btn.setCursor(Qt.PointingHandCursor)
        self._show_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #656d76; "
            "text-decoration: underline; font-size: 11px; padding: 0 4px; }"
            "QPushButton:hover { color: #0969da; }"
        )
        self._show_btn.clicked.connect(self._show_dialog)
        layout.addWidget(self._show_btn)

        self._refresh_badge()

    # ─── Public API ────────────────────────────────────────────────────────

    def add_error(self, title: str, message: str, context: str = "") -> None:
        """يضيف خطأً جديدًا"""
        rec = ErrorRecord(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            severity="error",
            title=title,
            message=message,
            context=context,
        )
        self._records.append(rec)
        self._trim()
        self._refresh_badge()
        logger.error(f"[{context}] {title}: {message}")

    def add_warning(self, title: str, message: str, context: str = "") -> None:
        """يضيف تحذيرًا جديدًا"""
        rec = ErrorRecord(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            severity="warning",
            title=title,
            message=message,
            context=context,
        )
        self._records.append(rec)
        self._trim()
        self._refresh_badge()
        logger.warning(f"[{context}] {title}: {message}")

    def clear(self) -> None:
        """يفرّغ كل السجلات"""
        self._records.clear()
        self._refresh_badge()

    @property
    def errors_count(self) -> int:
        return sum(1 for r in self._records if r.severity == "error")

    @property
    def warnings_count(self) -> int:
        return sum(1 for r in self._records if r.severity == "warning")

    @property
    def total_count(self) -> int:
        return len(self._records)

    def records(self) -> List[ErrorRecord]:
        """يرجع نسخة من السجلات (الأحدث آخرًا)"""
        return list(self._records)

    # ─── Internal ──────────────────────────────────────────────────────────

    def _trim(self) -> None:
        """يحذف أقدم السجلات لو تجاوزنا الحد"""
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

    def _refresh_badge(self) -> None:
        """يحدّث العدّاد المرئي"""
        errs = self.errors_count
        warns = self.warnings_count
        total = errs + warns

        if total == 0:
            self._icon_label.setText("✓")
            self._icon_label.setStyleSheet("font-size: 14px; color: #1a7f37;")
            self._count_label.setText("0")
            self._count_label.setStyleSheet(
                "background: #1a7f37; color: white; border-radius: 8px; "
                "padding: 1px 6px; font-size: 11px; font-weight: 600;"
            )
            self._show_btn.setEnabled(False)
        else:
            self._icon_label.setText("⚠" if errs > 0 else "ℹ")
            self._icon_label.setStyleSheet(
                f"font-size: 14px; color: {'#d1242f' if errs > 0 else '#9a6700'};"
            )
            self._count_label.setText(str(total))
            color = "#d1242f" if errs > 0 else "#9a6700"
            self._count_label.setStyleSheet(
                f"background: {color}; color: white; border-radius: 8px; "
                "padding: 1px 6px; font-size: 11px; font-weight: 600;"
            )
            self._show_btn.setEnabled(True)

        self.errors_changed.emit(errs, warns)

    def _show_dialog(self) -> None:
        """يعرض نافذة بكل الأخطاء"""
        dlg = ErrorDetailsDialog(self._records, parent=self)
        dlg.exec()


# ─── ErrorDetailsDialog ─────────────────────────────────────────────────────

class ErrorDetailsDialog(QDialog):
    """نافذة عرض كل الأخطاء"""

    def __init__(self, records: List[ErrorRecord], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("سجل الأخطاء والتحذيرات")
        self.resize(720, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # عنوان
        title = QLabel(f"📊 {len(records)} سجل — {sum(1 for r in records if r.severity == 'error')} خطأ، "
                       f"{sum(1 for r in records if r.severity == 'warning')} تحذير")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        # جدول
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["الوقت", "النوع", "السياق", "العنوان", "الرسالة"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        # ملء الجدول (الأحدث آخرًا)
        for rec in records:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(rec.timestamp))
            type_item = QTableWidgetItem("✗ خطأ" if rec.severity == "error" else "⚠ تحذير")
            type_item.setForeground(QColor("#d1242f") if rec.severity == "error" else QColor("#9a6700"))
            self._table.setItem(row, 1, type_item)
            self._table.setItem(row, 2, QTableWidgetItem(rec.context))
            self._table.setItem(row, 3, QTableWidgetItem(rec.title))
            self._table.setItem(row, 4, QTableWidgetItem(rec.message))

        layout.addWidget(self._table, stretch=1)

        # أزرار
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("إغلاق")
        close_btn.setProperty("primary", True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


__all__ = ["ErrorReporter", "ErrorRecord", "ErrorDetailsDialog"]
