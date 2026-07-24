"""IFMMainWindow — النافذة الرئيسية لـ IFM Desktop

التصميم:
  - Sidebar (يمين) — قائمة تنقل بين اللوحات
  - Central QStackedWidget — يحتوي اللوحات السبع
  - IFMStatusBar (أسفل) — مؤشر المراقب + الإحصائيات + شريط التقدّم + الأخطاء + رسالة
  - QMenuBar — ملف (فتح مجلد، خروج) + عرض (تبديل السمة) + إجراءات (إلغاء) + مساعدة

التكامل مع IFMController:
  - كل لوحة تتصل بـ controller عبر signals/slots
  - تحديثات الحالة تُبَث للوحة status bar
  - إشارات التقدّم والإلغاء تُربط بـ ProgressManager في الـ status bar (PR-09)
  - إشارات الأخطاء تُربط بـ ErrorReporter في الـ status bar (PR-09)

PR-08 من development-roadmap-v1.0 (IFM Phase C)
PR-09 من development-roadmap-v1.0 (progress + previews + settings)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from .controllers.ifm_controller import IFMController, IFMStateSnapshot
from .panels.action_log_panel import ActionLogPanel
from .panels.inventory_panel import InventoryPanel
from .panels.preview_panel import FilePreviewPanel
from .panels.rule_engine_panel import RuleEnginePanel
from .panels.settings_panel import SettingsPanel
from .panels.undo_log_panel import UndoLogPanel
from .panels.watcher_panel import WatcherPanel
from .settings import IFMSettings
from .theme import toggle_theme
from .widgets.sidebar import Sidebar
from .widgets.status_bar import IFMStatusBar


class IFMMainWindow(QMainWindow):
    """النافذة الرئيسية لـ IFM Desktop"""

    def __init__(
        self,
        controller: IFMController | None = None,
        base_dir: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("IntelliFile — منظّم الملفات الذكي")
        self.resize(1280, 820)

        # ─── Controller ────────────────────────────────────────────────
        self.controller = controller or IFMController(
            base_dir=base_dir or str(Path.cwd()),
        )

        # ─── Build UI ──────────────────────────────────────────────────
        self._build_ui()
        self._build_menu()
        self._connect_signals()

        # ─── Initial state ─────────────────────────────────────────────
        self.rule_engine_panel.set_ruleset_info(
            self.controller.ruleset.name, len(self.controller.ruleset.rules)
        )
        if self.controller.ruleset_path:
            self.inventory_panel.set_path(str(self.controller.base_dir))

        # ─── تطبيق الإعدادات المحفوظة ──────────────────────────────────
        self._apply_initial_settings(self.controller.settings)

    # ─── Build UI ───────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        # Central stack
        self.stack = QStackedWidget()
        self.inventory_panel = InventoryPanel()
        self.preview_panel = FilePreviewPanel(
            max_text_bytes=self.controller.settings.max_text_preview_bytes
        )
        self.rule_engine_panel = RuleEnginePanel()
        self.action_log_panel = ActionLogPanel()
        self.undo_log_panel = UndoLogPanel()
        self.watcher_panel = WatcherPanel()
        self.settings_panel = SettingsPanel(settings=self.controller.settings)

        # ترتيب اللوحات يطابق ترتيب NAV_ITEMS في Sidebar
        # inventory=0, preview=1, rules=2, action_log=3, undo_log=4, watcher=5, settings=6
        self.stack.addWidget(self.inventory_panel)
        self.stack.addWidget(self.preview_panel)
        self.stack.addWidget(self.rule_engine_panel)
        self.stack.addWidget(self.action_log_panel)
        self.stack.addWidget(self.undo_log_panel)
        self.stack.addWidget(self.watcher_panel)
        self.stack.addWidget(self.settings_panel)

        layout.addWidget(self.stack, stretch=1)

        self.setCentralWidget(central)

        # Status bar
        self.status_bar = IFMStatusBar()
        self.setStatusBar(self.status_bar)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # ─── قائمة ملف ─────────────────────────────────────────────────
        file_menu = menubar.addMenu("ملف")

        open_action = QAction("فتح مجلد...", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self._on_open_folder)
        file_menu.addAction(open_action)

        file_menu.addSeparator()

        exit_action = QAction("خروج", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ─── قائمة عرض ─────────────────────────────────────────────────
        view_menu = menubar.addMenu("عرض")

        self.theme_action = QAction("تبديل السمة (داكن/فاتح)", self)
        self.theme_action.setShortcut(QKeySequence("Ctrl+T"))
        self.theme_action.triggered.connect(self._on_toggle_theme)
        view_menu.addAction(self.theme_action)

        # ─── قائمة إجراءات (PR-09) ─────────────────────────────────────
        ops_menu = menubar.addMenu("إجراءات")

        self.cancel_action = QAction("إلغاء العملية الحالية", self)
        self.cancel_action.setShortcut(QKeySequence("Esc"))
        self.cancel_action.triggered.connect(self._on_cancel_operation)
        ops_menu.addAction(self.cancel_action)

        # ─── قائمة مساعدة ──────────────────────────────────────────────
        help_menu = menubar.addMenu("مساعدة")

        about_action = QAction("حول IFM", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ─── Signal connections ────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Sidebar → Stack
        self.sidebar.nav_clicked.connect(self._on_nav)

        # Inventory panel
        self.inventory_panel.scan_requested.connect(self._on_scan_requested)
        self.inventory_panel.selection_changed.connect(self._on_inventory_selection)

        # Rule engine panel
        self.rule_engine_panel.load_ruleset_requested.connect(self._on_load_ruleset)
        self.rule_engine_panel.dry_run_requested.connect(self._on_dry_run)
        self.rule_engine_panel.execute_requested.connect(self._on_execute)

        # Action log panel
        self.action_log_panel.export_json_requested.connect(self._on_export_json)
        self.action_log_panel.export_html_requested.connect(self._on_export_html)
        self.action_log_panel.clear_requested.connect(self._on_clear_action_log)

        # Undo log panel
        self.undo_log_panel.undo_last_requested.connect(self._on_undo_last)
        self.undo_log_panel.undo_all_requested.connect(self._on_undo_all)

        # Watcher panel
        self.watcher_panel.start_requested.connect(self._on_watcher_start)
        self.watcher_panel.stop_requested.connect(self._on_watcher_stop)

        # Settings panel (PR-09)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.theme_change_requested.connect(self._on_theme_change_requested)
        self.settings_panel.rtl_change_requested.connect(self._on_rtl_change_requested)

        # Controller signals → UI updates
        self.controller.scan_started.connect(self._on_scan_started)
        self.controller.scan_finished.connect(self._on_scan_finished)
        self.controller.scan_failed.connect(self._on_scan_failed)
        self.controller.scan_cancelled.connect(self._on_scan_cancelled)

        self.controller.dry_run_started.connect(self._on_dry_run_started)
        self.controller.dry_run_ready.connect(self._on_dry_run_ready)
        self.controller.dry_run_failed.connect(self._on_dry_run_failed)

        self.controller.execute_started.connect(self._on_execute_started)
        self.controller.execute_finished.connect(self._on_execute_finished)
        self.controller.execute_failed.connect(self._on_execute_failed)
        self.controller.execute_cancelled.connect(self._on_execute_cancelled)

        self.controller.undo_finished.connect(self._on_undo_finished)
        self.controller.undo_log_changed.connect(self._on_undo_log_changed)

        self.controller.action_logged.connect(self._on_action_logged)
        self.controller.action_log_cleared.connect(self._on_action_log_cleared)

        self.controller.watcher_started.connect(self._on_watcher_started)
        self.controller.watcher_stopped.connect(self._on_watcher_stopped)

        self.controller.state_changed.connect(self._on_state_changed)
        self.controller.error.connect(self._on_error)

        # PR-09: progress + cancellation
        self.controller.progress.connect(self._on_progress)
        self.controller.operation_cancelled.connect(self._on_operation_cancelled)
        self.controller.file_previewed.connect(self._on_file_previewed)

        # PR-09: ProgressManager → controller.cancel_operation
        self.status_bar.progress_manager.cancelled.connect(self._on_progress_cancelled)

    # ─── Slots: Sidebar / Menu ──────────────────────────────────────────────

    def _on_nav(self, nav_id: str) -> None:
        idx_map = {
            "inventory": 0,
            "preview": 1,
            "rules": 2,
            "action_log": 3,
            "undo_log": 4,
            "watcher": 5,
            "settings": 6,
        }
        idx = idx_map.get(nav_id, 0)
        self.stack.setCurrentIndex(idx)
        self.sidebar.set_active(nav_id)

    def _on_open_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "فتح مجلد")
        if path:
            self.controller.base_dir = Path(path)
            self.inventory_panel.set_path(path)
            self._on_scan_requested(path)

    def _on_toggle_theme(self) -> None:
        app = QApplication.instance()
        if app:
            new_mode = toggle_theme(app)
            self.status_bar.set_message(f"السمة: {new_mode}")
            # تحديث الإعداد
            self.controller.settings.dark_mode = (new_mode == "dark")
            self.settings_panel.set_settings(self.controller.settings)

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "حول IntelliFile",
            "<h3>IntelliFile — منظّم الملفات الذكي</h3>"
            "<p>IFM Desktop UX — PR-09 (Phase C)</p>"
            "<p>واجهة PySide6 مع تكامل كامل لطبقة IFM الأساسية:</p>"
            "<ul>"
            "<li>FileInventory — جرد الملفات</li>"
            "<li>FilePreview — معاينة النص والصور</li>"
            "<li>RuleEngine — قواعد + محاكاة + تنفيذ</li>"
            "<li>ActionLog — سجل مرئي + JSON/HTML</li>"
            "<li>UndoLog — تراجع كامل</li>"
            "<li>FileWatcher — مراقبة مباشرة</li>"
            "<li>ProgressManager — شريط تقدّم قابل للإلغاء</li>"
            "<li>Settings — إعدادات قابلة للتخصيص</li>"
            "</ul>"
            "<p><i>لا AI، لا medical — فقط UX foundation.</i></p>"
        )

    # ─── Slots: Inventory + Preview ─────────────────────────────────────────

    def _on_scan_requested(self, path: str) -> None:
        self.controller.scan_directory(path)

    def _on_scan_started(self, path: str) -> None:
        self.inventory_panel.set_scanning(True)
        self.status_bar.set_message(f"يفحص: {path}")
        self.status_bar.set_watcher_state("pending")

    def _on_scan_finished(self, stats, records) -> None:
        self.inventory_panel.set_scanning(False)
        self.inventory_panel.set_records(records)
        self.inventory_panel.set_stats(
            stats.total_files, stats.total_size_bytes, stats.duplicate_candidates
        )
        self.status_bar.set_message(f"اكتمل الفحص: {stats.total_files} ملف")
        self.status_bar.set_watcher_state(
            "running" if self.controller.is_watcher_running() else "idle"
        )
        # تحديث سجل التراجع + الإجراءات
        self.undo_log_panel.set_entries(self.controller.undo_log.list_entries())
        self.action_log_panel.set_entries(self.controller.action_log.list_entries())

        # PR-09: auto-organize لو مفعّل في الإعدادات
        if self.controller.settings.auto_organize and self.controller.settings.default_dry_run:
            QTimer.singleShot(100, self._maybe_auto_organize)

    def _on_scan_failed(self, message: str) -> None:
        self.inventory_panel.set_scanning(False)
        self.status_bar.set_message(f"فشل الفحص: {message}")
        self.status_bar.set_watcher_state("error")
        self.status_bar.error_reporter.add_error("فشل الفحص", message, context="scan")

    def _on_scan_cancelled(self, path: str) -> None:
        self.inventory_panel.set_scanning(False)
        self.status_bar.set_message(f"أُلغي الفحص: {path}")
        self.status_bar.set_watcher_state(
            "running" if self.controller.is_watcher_running() else "idle"
        )

    def _on_inventory_selection(self, file_path: str) -> None:
        """عند اختيار ملف في الجرد — تحديث المعاينة"""
        self.preview_panel.preview_file(file_path)

    def _on_file_previewed(self, file_path: str) -> None:
        """عند طلب معاينة ملف — التنقّل للوحة المعاينة"""
        self.preview_panel.preview_file(file_path)
        self._on_nav("preview")

    def _maybe_auto_organize(self) -> None:
        """يشغّل dry_run تلقائيًا لو auto_organize مفعّل"""
        if not self.controller.records:
            return
        self.status_bar.set_message("تشغيل تلقائي: محاكاة...")
        self.controller.dry_run()

    # ─── Slots: Ruleset / Dry-Run / Execute ─────────────────────────────────

    def _on_load_ruleset(self, path: str) -> None:
        self.controller.reload_ruleset(path)
        self.rule_engine_panel.set_ruleset_info(
            self.controller.ruleset.name, len(self.controller.ruleset.rules)
        )
        self.status_bar.set_message(f"تم تحميل: {path}")

    def _on_dry_run(self) -> None:
        self.controller.dry_run()

    def _on_dry_run_started(self) -> None:
        self.status_bar.set_message("يعمل على المحاكاة...")

    def _on_dry_run_ready(self, plan) -> None:
        self.rule_engine_panel.set_plan(plan)
        self.status_bar.set_message(f"محاكاة جاهزة: {plan.total_actions} إجراء")

    def _on_dry_run_failed(self, message: str) -> None:
        self.rule_engine_panel.set_dry_run_failed(message)
        self.status_bar.set_message(f"فشل المحاكاة: {message}")
        self.status_bar.error_reporter.add_error("فشل المحاكاة", message, context="dry_run")

    def _on_execute(self, confirm_destructive: bool) -> None:
        self.controller.execute(confirm_destructive=confirm_destructive)

    def _on_execute_started(self, count: int) -> None:
        self.status_bar.set_message(f"ينفّذ {count} إجراء...")

    def _on_execute_finished(self, entries, failures) -> None:
        self.rule_engine_panel.set_execute_results(entries, failures)
        # تحديث لوحات السجل
        self.undo_log_panel.set_entries(self.controller.undo_log.list_entries())
        self.action_log_panel.set_entries(self.controller.action_log.list_entries())
        self.status_bar.set_message(
            f"اكتمل التنفيذ: {len(entries) - len(failures)} نجح، {len(failures)} فشل"
        )
        # الإبلاغ عن الأخطاء
        for f in failures:
            err_msg = f.get("error", "خطأ غير معروف") if isinstance(f, dict) else str(f)
            self.status_bar.error_reporter.add_error(
                "فشل تنفيذ إجراء", err_msg, context="execute"
            )

    def _on_execute_failed(self, message: str) -> None:
        self.rule_engine_panel.set_execute_failed(message)
        self.status_bar.set_message(f"فشل التنفيذ: {message}")
        self.status_bar.error_reporter.add_error("فشل التنفيذ", message, context="execute")

    def _on_execute_cancelled(self, executed_so_far: int) -> None:
        self.status_bar.set_message(f"أُلغي التنفيذ بعد {executed_so_far} إجراء")

    # ─── Slots: Action Log ──────────────────────────────────────────────────

    def _on_export_json(self, path: str) -> None:
        try:
            result = self.controller.export_action_log_json(path)
            self.status_bar.set_message(f"تم التصدير JSON: {result}")
        except Exception as e:
            QMessageBox.warning(self, "خطأ تصدير", str(e))
            self.status_bar.error_reporter.add_error(
                "فشل تصدير JSON", str(e), context="export"
            )

    def _on_export_html(self, path: str) -> None:
        try:
            result = self.controller.export_action_log_html(path)
            self.status_bar.set_message(f"تم التصدير HTML: {result}")
        except Exception as e:
            QMessageBox.warning(self, "خطأ تصدير", str(e))
            self.status_bar.error_reporter.add_error(
                "فشل تصدير HTML", str(e), context="export"
            )

    def _on_clear_action_log(self) -> None:
        reply = QMessageBox.question(
            self, "تأكيد التفريغ",
            "هل تريد تفريغ السجل المرئي؟ (لا يؤثر على سجل التراجع)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.controller.clear_action_log()

    def _on_action_logged(self, entry) -> None:
        self.action_log_panel.add_entry(entry)

    def _on_action_log_cleared(self) -> None:
        self.action_log_panel.clear_view()

    # ─── Slots: Undo Log ────────────────────────────────────────────────────

    def _on_undo_last(self) -> None:
        self.controller.undo_last()

    def _on_undo_all(self) -> None:
        self.controller.undo_all()

    def _on_undo_finished(self, entry, success, error) -> None:
        self.undo_log_panel.set_undo_result(success, error)
        self.undo_log_panel.set_entries(self.controller.undo_log.list_entries())
        self.action_log_panel.set_entries(self.controller.action_log.list_entries())
        if success:
            self.status_bar.set_message("تم التراجع عن الإجراء")
        else:
            self.status_bar.set_message(f"فشل التراجع: {error}")
            self.status_bar.error_reporter.add_error(
                "فشل التراجع", error, context="undo"
            )

    def _on_undo_log_changed(self, count: int) -> None:
        self.undo_log_panel.set_entries(self.controller.undo_log.list_entries())

    # ─── Slots: Watcher ─────────────────────────────────────────────────────

    def _on_watcher_start(self) -> None:
        self.controller.start_watcher()

    def _on_watcher_stop(self) -> None:
        self.controller.stop_watcher()

    def _on_watcher_started(self) -> None:
        self.watcher_panel.set_running(True)
        self.status_bar.set_watcher_state("running")
        self.status_bar.set_message("المراقب يعمل")

    def _on_watcher_stopped(self) -> None:
        self.watcher_panel.set_running(False)
        self.status_bar.set_watcher_state("idle")
        self.status_bar.set_message("المراقب متوقف")

    # ─── Slots: Settings (PR-09) ────────────────────────────────────────────

    def _on_settings_changed(self, settings: IFMSettings) -> None:
        """عند حفظ إعدادات جديدة من SettingsPanel"""
        self.controller.apply_settings(settings)
        # تحديث PreviewPanel لو تغيّر حد المعاينة
        self.preview_panel.set_max_text_bytes(settings.max_text_preview_bytes)
        self.status_bar.set_message("تم تطبيق الإعدادات")

    def _on_theme_change_requested(self, mode: str) -> None:
        """عند تغيير السمة من SettingsPanel"""
        app = QApplication.instance()
        if app:
            from .theme import apply_theme
            apply_theme(app, mode)
            app.setProperty("ifm_theme", mode)

    def _on_rtl_change_requested(self, rtl: bool) -> None:
        """عند تغيير اتجاه RTL من SettingsPanel"""
        app = QApplication.instance()
        if app:
            from PySide6.QtCore import Qt
            app.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)

    def _apply_initial_settings(self, settings: IFMSettings) -> None:
        """يطبّق الإعدادات المحفوظة عند بدء التشغيل"""
        app = QApplication.instance()
        if app:
            from .theme import apply_theme
            apply_theme(app, "dark" if settings.dark_mode else "light")
            app.setProperty("ifm_theme", "dark" if settings.dark_mode else "light")
            app.setLayoutDirection(Qt.RightToLeft if settings.rtl else Qt.LeftToRight)
        # تحديث الـ SettingsPanel لإ reflect القيم الفعلية المطبّقة
        self.settings_panel.set_settings(settings)

    # ─── Slots: Progress + Cancellation (PR-09) ─────────────────────────────

    def _on_progress(self, op_id: str, current: int, total: int, message: str) -> None:
        """تحديث شريط التقدّم في الـ status bar"""
        pm = self.status_bar.progress_manager
        if not pm.is_active(op_id):
            pm.start(op_id, total=total, message=message)
        else:
            pm.update(op_id, current=current, total=total, message=message)

    def _on_operation_cancelled(self, op_id: str) -> None:
        """عند تأكيد إلغاء عملية من الـ controller"""
        pm = self.status_bar.progress_manager
        pm.finish(op_id, success=False, message=f"أُلغي: {op_id}")
        self.status_bar.set_message(f"أُلغي: {op_id}")

    def _on_progress_cancelled(self, op_id: str) -> None:
        """عند نقر زر الإلغاء في ProgressManager"""
        ok = self.controller.cancel_operation(op_id)
        if not ok:
            self.status_bar.set_message(f"لا عملية نشطة: {op_id}")

    def _on_cancel_operation(self) -> None:
        """عند اختيار 'إلغاء العملية الحالية' من القائمة"""
        pm = self.status_bar.progress_manager
        # يُلغي آخر عملية نشطة
        pm._on_cancel_clicked()

    # ─── Slots: State / Error ───────────────────────────────────────────────

    def _on_state_changed(self, snap: IFMStateSnapshot) -> None:
        # تحديث الـ status bar
        self.status_bar.set_stats(
            snap.inventory_count,
            snap.action_log_size,
            snap.undo_log_size,
        )
        # تحديث المراقب
        if snap.watcher_running:
            self.watcher_panel.set_running(True)
            self.status_bar.set_watcher_state(
                "pending" if snap.watcher_pending > 0 else "running"
            )
        # تحديث سجل المراقب
        history = self.controller.get_watcher_history()
        if history:
            self.watcher_panel.set_history(history)

    def _on_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)
        self.status_bar.set_message(f"{title}: {message}")
        self.status_bar.error_reporter.add_error(title, message, context="controller")

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """تنظيف الموارد قبل الإغلاق"""
        self.controller.cleanup()
        super().closeEvent(event)
