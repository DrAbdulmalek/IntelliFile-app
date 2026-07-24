"""RuleEnginePanel — لوحة القواعد: محاكاة → تنفيذ → عرض النتائج

تعرض:
  - زر تحميل قواعد YAML + عرض اسم/عدد القواعد
  - زر محاكاة (dry-run) → جدول بالإجراءات المخطّطة
  - زر تنفيذ (execute) + تأكيد للإجراءات التدميرية
  - عرض الإجراءات المنفّذة + الفشل

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
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


class RuleEnginePanel(QWidget):
    """لوحة RuleEngine: محاكاة + تنفيذ + عرض النتائج

    Signals:
        load_ruleset_requested(str): طلب تحميل قواعد من ملف YAML
        dry_run_requested(): طلب توليد خطة محاكاة
        execute_requested(bool): طلب تنفيذ الخطة (confirm_destructive)
    """

    load_ruleset_requested = Signal(str)
    dry_run_requested = Signal()
    execute_requested = Signal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("القواعد والتنفيذ")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("حمّل قواعد YAML، شغّل محاكاة، ثم نفّذ الإجراءات بأمان")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── صندوق القواعد ─────────────────────────────────────────────
        rules_box = QGroupBox("القواعد المحمّلة")
        rules_layout = QHBoxLayout(rules_box)

        self.ruleset_label = QLabel("لا قواعد محمّلة")
        self.ruleset_label.setStyleSheet("font-size: 13px;")
        rules_layout.addWidget(self.ruleset_label, stretch=1)

        load_btn = QPushButton("تحميل YAML...")
        load_btn.clicked.connect(self._on_load)
        rules_layout.addWidget(load_btn)

        layout.addWidget(rules_box)

        # ─── صندوق المحاكاة ────────────────────────────────────────────
        sim_box = QGroupBox("المحاكاة (Dry-Run)")
        sim_layout = QVBoxLayout(sim_box)

        # شريط أزرار المحاكاة
        sim_buttons = QHBoxLayout()
        self.dry_run_btn = QPushButton("▶ تشغيل المحاكاة")
        self.dry_run_btn.setProperty("primary", True)
        self.dry_run_btn.clicked.connect(self._on_dry_run)
        sim_buttons.addWidget(self.dry_run_btn)

        self.dry_run_summary = QLabel("—")
        self.dry_run_summary.setStyleSheet("color: #656d76; font-size: 12px;")
        sim_buttons.addWidget(self.dry_run_summary, stretch=1)

        sim_layout.addLayout(sim_buttons)

        # جدول الإجراءات المخطّطة
        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels([
            "القاعدة", "الملف", "الإجراء", "الوجهة/القيمة", "الحالة",
        ])
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        sim_layout.addWidget(self.plan_table)

        layout.addWidget(sim_box, stretch=1)

        # ─── صندوق التنفيذ ────────────────────────────────────────────
        exec_box = QGroupBox("التنفيذ")
        exec_layout = QHBoxLayout(exec_box)

        self.execute_btn = QPushButton("⚡ تنفيذ الخطة")
        self.execute_btn.setProperty("primary", True)
        self.execute_btn.setEnabled(False)
        self.execute_btn.clicked.connect(self._on_execute)
        exec_layout.addWidget(self.execute_btn)

        self.execute_summary = QLabel("—")
        self.execute_summary.setStyleSheet("color: #656d76; font-size: 12px;")
        exec_layout.addWidget(self.execute_summary, stretch=1)

        layout.addWidget(exec_box)

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "اختر ملف قواعد YAML", "", "YAML files (*.yaml *.yml)"
        )
        if path:
            self.load_ruleset_requested.emit(path)

    def _on_dry_run(self) -> None:
        self.dry_run_btn.setEnabled(False)
        self.dry_run_btn.setText("يعمل...")
        self.dry_run_requested.emit()

    def _on_execute(self) -> None:
        # تأكيد قبل التنفيذ
        reply = QMessageBox.question(
            self, "تأكيد التنفيذ",
            "هل تريد تنفيذ الإجراءات المخطّطة؟\n"
            "يمكن التراجع عنها لاحقًا من سجل التراجع.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.execute_btn.setEnabled(False)
            self.execute_btn.setText("ينفّذ...")
            # افتراضيًا لا نسمح بالإجراءات التدميرية بدون تأكيد إضافي
            self.execute_requested.emit(False)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_ruleset_info(self, name: str, rules_count: int) -> None:
        """يحدّث معلومات القواعد المحمّلة"""
        self.ruleset_label.setText(
            f"📋 <b>{name}</b> — {rules_count} قاعدة مفعّلة"
        )

    def set_plan(self, plan) -> None:
        """يملأ جدول الإجراءات المخطّطة من DryRunPlan"""
        self.plan_table.setRowCount(0)
        for action in plan.planned_actions:
            row = self.plan_table.rowCount()
            self.plan_table.insertRow(row)
            self.plan_table.setItem(row, 0, QTableWidgetItem(action.rule_name))
            self.plan_table.setItem(row, 1, QTableWidgetItem(action.file_name))
            self.plan_table.setItem(row, 2, QTableWidgetItem(action.action.type))
            # الوجهة أو القيمة
            target = action.action.target or action.action.value or ""
            self.plan_table.setItem(row, 3, QTableWidgetItem(str(target)))
            self.plan_table.setItem(row, 4, QTableWidgetItem("مخطّط"))

        # ملخص المحاكاة
        counts = plan.action_type_counts() if hasattr(plan, "action_type_counts") else {}
        summary_text = " | ".join(f"{k}: {v}" for k, v in counts.items())
        if not summary_text:
            summary_text = "لا إجراءات"
        self.dry_run_summary.setText(
            f"📊 {plan.total_actions} إجراء | {plan.files_affected} ملف | {summary_text}"
        )

        self.dry_run_btn.setEnabled(True)
        self.dry_run_btn.setText("▶ تشغيل المحاكاة")
        self.execute_btn.setEnabled(plan.total_actions > 0)

    def set_dry_run_failed(self, message: str) -> None:
        """يعرض رسالة فشل المحاكاة"""
        self.dry_run_summary.setText(f"⚠ {message}")
        self.dry_run_btn.setEnabled(True)
        self.dry_run_btn.setText("▶ تشغيل المحاكاة")

    def set_execute_results(self, entries: list, failures: list) -> None:
        """يحدّث جدول الإجراءات بنتائج التنفيذ"""
        for row in range(self.plan_table.rowCount()):
            status_item = self.plan_table.item(row, 4)
            if status_item:
                status_item.setText("✓ نُفّذ")
                status_item.setForeground(Qt.darkGreen)

        success_count = len(entries) - len(failures)
        self.execute_summary.setText(
            f"✓ {success_count} نجح | ✗ {len(failures)} فشل"
        )
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("⚡ تنفيذ الخطة")

    def set_execute_failed(self, message: str) -> None:
        """يعرض رسالة فشل التنفيذ"""
        self.execute_summary.setText(f"⚠ {message}")
        self.execute_btn.setEnabled(True)
        self.execute_btn.setText("⚡ تنفيذ الخطة")
