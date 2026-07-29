"""IFMProgressBar + ProgressManager — شريط تقدّم حقيقي قابل للإلغاء

يدعم:
  - بدء/تحديث/إنهاء عمليات طويلة (scan, dry_run, execute)
  - إلغاء العملية عبر زر "إلغاء"
  - عرض رسالة نصية تُحدّث أثناء التقدّم
  - حالات متعدّدة (indeterminate للعمليات التي لا يُعرف حجمها)

التصميم:
  - ProgressManager هو الواجهة الرئيسية؛ يلفّ QProgressBar + QLabel + QPushButton
  - يبثّ cancelled(op_id) عند طلب الإلغاء
  - يبثّ progress(op_id, current, total, message) عند التحديث

الاستخدام:
    pm = ProgressManager(status_bar)
    pm.start("scan", total=1000, message="يفحص الملفات...")
    for i, record in enumerate(records):
        if pm.is_cancelled("scan"):
            break
        pm.update("scan", i + 1, message=f"فحص: {record.name}")
    pm.finish("scan", success=True, message=f"اكتمل: {i+1} ملف")

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ─── Progress operation state ────────────────────────────────────────────────

class _OpState:
    """حالة عملية واحدة قيد التقدّم"""

    __slots__ = ("cancelled", "current", "indeterminate", "message", "op_id", "total")

    def __init__(
        self,
        op_id: str,
        total: int = 0,
        message: str = "",
        indeterminate: bool = False,
    ):
        self.op_id = op_id
        self.current = 0
        self.total = total
        self.message = message
        self.cancelled = False
        self.indeterminate = indeterminate or total <= 0


# ─── ProgressManager ─────────────────────────────────────────────────────────

class ProgressManager(QFrame):
    """مدير شريط التقدّم القابل للإلغاء

    Signals:
        cancelled(str): طلب إلغاء عملية (op_id)
        progress(str, int, int, str): تحديث تقدّم — (op_id, current, total, message)
        started(str): بدء عملية (op_id)
        finished(str, bool, str): انتهى — (op_id, success, message)
    """

    cancelled = Signal(str)
    progress = Signal(str, int, int, str)
    started = Signal(str)
    finished = Signal(str, bool, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ProgressManager")
        self._ops: dict[str, _OpState] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # صف واحد: شريط + رسالة + زر إلغاء
        row = QHBoxLayout()
        row.setSpacing(8)

        self._message_label = QLabel("")
        self._message_label.setStyleSheet("color: #656d76; font-size: 12px;")
        self._message_label.setMinimumWidth(120)
        row.addWidget(self._message_label, stretch=1)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setFixedWidth(220)
        row.addWidget(self._progress_bar)

        self._cancel_btn = QPushButton("إلغاء")
        self._cancel_btn.setProperty("danger", True)
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.setEnabled(False)
        row.addWidget(self._cancel_btn)

        layout.addLayout(row)

        # في البداية مخفي
        self._set_visible(False)

    # ─── Public API ────────────────────────────────────────────────────────

    def start(
        self,
        op_id: str,
        total: int = 0,
        message: str = "",
        indeterminate: bool = False,
    ) -> None:
        """يبدأ عملية جديدة

        Args:
            op_id: معرّف فريد للعملية (مثل "scan", "dry_run", "execute")
            total: العدد الكلي للعناصر (0 = indeterminate)
            message: رسالة أولية
            indeterminate: لو True، شريط متحرّك بلا نسبة
        """
        self._ops[op_id] = _OpState(
            op_id=op_id, total=total, message=message, indeterminate=indeterminate or total <= 0
        )
        self._set_visible(True)
        self._refresh_ui(op_id)
        self.started.emit(op_id)
        logger.debug(f"ProgressManager.start: {op_id} (total={total})")

    def update(
        self,
        op_id: str,
        current: int,
        total: int | None = None,
        message: str | None = None,
    ) -> None:
        """يحدّث تقدّم العملية

        Args:
            op_id: المعرّف
            current: القيمة الحالية
            total: القيمة الكلية (اختياري — لو None يُترك كما هو)
            message: رسالة جديدة (اختياري)
        """
        if op_id not in self._ops:
            # عملية غير مسجّلة — أنشئها كـ indeterminate
            self.start(op_id, total=total or 0, message=message or "")
        op = self._ops[op_id]
        op.current = current
        if total is not None:
            op.total = total
            op.indeterminate = total <= 0
        if message is not None:
            op.message = message
        self._refresh_ui(op_id)
        self.progress.emit(op_id, op.current, op.total, op.message)

    def finish(
        self,
        op_id: str,
        success: bool = True,
        message: str = "",
    ) -> None:
        """ينهي العملية"""
        if op_id not in self._ops:
            logger.debug(f"ProgressManager.finish: {op_id} not active")
            return
        op = self._ops.pop(op_id)
        final_msg = message or op.message
        # لو لا توجد عمليات أخرى، أخفِ
        if not self._ops:
            self._set_visible(False)
        else:
            # اعرض العملية التالية
            next_op_id = next(iter(self._ops))
            self._refresh_ui(next_op_id)
        self.finished.emit(op_id, success, final_msg)
        logger.debug(f"ProgressManager.finish: {op_id} success={success}")

    def is_cancelled(self, op_id: str) -> bool:
        """هل طُلب إلغاء العملية؟"""
        op = self._ops.get(op_id)
        return op is not None and op.cancelled

    def is_active(self, op_id: str) -> bool:
        """هل العملية قيد التشغيل؟"""
        return op_id in self._ops

    def cancel(self, op_id: str) -> None:
        """يُلغي العملية برمجيًا"""
        if op_id in self._ops:
            self._ops[op_id].cancelled = True
            self.cancelled.emit(op_id)
            logger.debug(f"ProgressManager.cancel: {op_id}")

    def reset(self) -> None:
        """يلغي كل العمليات النشطة ويعيد الواجهة للحالة الافتراضية"""
        for op_id in list(self._ops.keys()):
            self.cancel(op_id)
            self.finish(op_id, success=False, message="أُلغي")
        self._set_visible(False)

    # ─── Internal ──────────────────────────────────────────────────────────

    def _on_cancel_clicked(self) -> None:
        """يُلغي آخر عملية نشطة (لو عدّة عمليات، نُلغي الأحدث)"""
        if not self._ops:
            return
        # نُلغي العملية الأحدث (آخر مفتاح في القاموس)
        last_op_id = next(reversed(self._ops))
        self.cancel(last_op_id)

    def _refresh_ui(self, op_id: str) -> None:
        """يحدّث الواجهة لتعكس حالة العملية الحالية"""
        op = self._ops.get(op_id)
        if op is None:
            return

        # الرسالة
        self._message_label.setText(op.message or op_id)

        # شريط التقدّم
        if op.indeterminate:
            self._progress_bar.setRange(0, 0)  # indeterminate
            self._progress_bar.setTextVisible(False)
        else:
            self._progress_bar.setRange(0, max(1, op.total))
            self._progress_bar.setValue(min(op.current, op.total))
            self._progress_bar.setTextVisible(True)
            percent = int(100 * op.current / max(1, op.total))
            self._progress_bar.setFormat(f"{percent}% ({op.current}/{op.total})")

        # زر الإلغاء
        self._cancel_btn.setEnabled(True)

    def _set_visible(self, visible: bool) -> None:
        """يُظهر/يُخفي المدير"""
        self.setVisible(visible)
        self._message_label.setVisible(visible)
        self._progress_bar.setVisible(visible)
        self._cancel_btn.setVisible(visible)
        if not visible:
            self._cancel_btn.setEnabled(False)


__all__ = ["ProgressManager"]
