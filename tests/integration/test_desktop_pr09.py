"""اختبارات IFM Desktop PR-09 — progress + previews + settings

يغطّي:
  - IFMSettings (default + persistence + update)
  - ProgressManager (start/update/finish/cancel)
  - ProgressToken + IFMController.cancel_operation
  - ErrorReporter (add_error/add_warning/clear + dialog)
  - RecentActionsWidget (set_entries/add_entry/clear_view)
  - FilePreviewPanel (text/image/unavailable/no-file)
  - SettingsPanel (load/save/reset + signals)
  - IFMMainWindow (معاينة بعد اختيار + إعدادات + إلغاء)
  - End-to-end: scan → select → preview + settings round-trip

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

# PySide6 imports — تتطلب qapp fixture
pytestmark = pytest.mark.desktop


# ─── Helpers ────────────────────────────────────────────────────────────────

def _process_events(app, count=3, sleep=0.05):
    """يعالج أحداث Qt عدة مرات لإتاحة المعالجة غير المتزامنة"""
    for _ in range(count):
        app.processEvents()
        time.sleep(sleep)


# ─── IFMSettings tests ──────────────────────────────────────────────────────

class TestIFMSettings:
    def test_defaults(self):
        from src.desktop.settings import IFMSettings
        s = IFMSettings()
        assert s.watch_folders_enabled is True
        assert s.default_dry_run is True
        assert s.confirm_destructive is True
        assert s.semantic_search_enabled is False
        assert s.dark_mode is True
        assert s.rtl is True
        assert s.auto_organize is False
        assert s.thumbnail_size > 0
        assert s.max_text_preview_bytes > 0
        assert s.save_undo_log_on_exit is True
        assert s.save_action_log_on_exit is True

    def test_to_json_roundtrip(self):
        from src.desktop.settings import IFMSettings
        s = IFMSettings(dark_mode=False, rtl=False, auto_organize=True)
        json_str = s.to_json()
        assert '"dark_mode": false' in json_str
        assert '"rtl": false' in json_str
        assert '"auto_organize": true' in json_str
        s2 = IFMSettings.from_json(json_str)
        assert s2.dark_mode is False
        assert s2.rtl is False
        assert s2.auto_organize is True

    def test_save_and_load(self, tmp_path):
        from src.desktop.settings import IFMSettings
        path = tmp_path / "settings.json"
        s = IFMSettings(dark_mode=False, auto_organize=True)
        saved_path = s.save(path)
        assert saved_path == path
        assert path.exists()
        # تحميل
        s2 = IFMSettings.load(path)
        assert s2.dark_mode is False
        assert s2.auto_organize is True

    def test_load_missing_file_returns_defaults(self, tmp_path):
        from src.desktop.settings import IFMSettings
        path = tmp_path / "nonexistent.json"
        s = IFMSettings.load(path)
        # قيم افتراضية
        assert s.dark_mode is True
        assert s.rtl is True

    def test_load_corrupt_file_returns_defaults(self, tmp_path):
        from src.desktop.settings import IFMSettings
        path = tmp_path / "corrupt.json"
        path.write_text("{ invalid json", encoding="utf-8")
        s = IFMSettings.load(path)
        assert s.dark_mode is True  # default

    def test_from_dict_ignores_unknown_keys(self):
        from src.desktop.settings import IFMSettings
        s = IFMSettings.from_dict({
            "dark_mode": False,
            "unknown_key": "value",
        })
        assert s.dark_mode is False

    def test_update_changes_values(self):
        from src.desktop.settings import IFMSettings
        s = IFMSettings()
        changed = s.update(dark_mode=False, rtl=False)
        assert changed is True
        assert s.dark_mode is False
        assert s.rtl is False
        # update بأ收支same values لا يُحدث تغييرًا
        changed2 = s.update(dark_mode=False, rtl=False)
        assert changed2 is False


# ─── ProgressManager tests ──────────────────────────────────────────────────

class TestProgressManager:
    def test_creation(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        assert pm is not None
        # في البداية لا توجد عمليات نشطة
        assert not pm.is_active("scan")

    def test_start_finish_lifecycle(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        events = []
        pm.started.connect(lambda op: events.append(("started", op)))
        pm.finished.connect(lambda op, ok, msg: events.append(("finished", op, ok, msg)))

        pm.start("scan", total=100, message="يفحص...")
        assert pm.is_active("scan")
        _process_events(qapp)

        pm.update("scan", current=50, message="50%")
        _process_events(qapp)

        pm.finish("scan", success=True, message="اكتمل")
        assert not pm.is_active("scan")

        # تحقّق من الأحداث
        assert events[0][0] == "started"
        assert events[0][1] == "scan"
        assert events[-1][0] == "finished"
        assert events[-1][1] == "scan"
        assert events[-1][2] is True

    def test_cancel_emits_signal(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        cancelled_ops = []
        pm.cancelled.connect(lambda op: cancelled_ops.append(op))

        pm.start("scan", total=100, message="يفحص")
        pm.cancel("scan")
        assert pm.is_cancelled("scan")
        assert "scan" in cancelled_ops

    def test_cancel_button_click_cancels_latest(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        cancelled = []
        pm.cancelled.connect(lambda op: cancelled.append(op))

        pm.start("scan", total=10)
        _process_events(qapp)
        pm._cancel_btn.click()
        _process_events(qapp)
        assert "scan" in cancelled

    def test_indeterminate_progress(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        pm.start("indeterminate", total=0, message="يعمل...")
        # indeterminate = total<=0
        assert pm.is_active("indeterminate")
        # شريط التقدّم في وضع indeterminate
        assert pm._progress_bar.maximum() == 0
        pm.finish("indeterminate", success=True)

    def test_reset_cancels_all(self, qapp):
        from src.desktop.widgets.progress_manager import ProgressManager
        pm = ProgressManager()
        pm.start("op1", total=10)
        pm.start("op2", total=20)
        pm.reset()
        assert not pm.is_active("op1")
        assert not pm.is_active("op2")


# ─── ProgressToken + IFMController cancellation ─────────────────────────────

class TestControllerCancellation:
    def test_cancel_operation_returns_false_for_inactive(self, qapp, tmp_path):
        from src.desktop import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        assert c.cancel_operation("nonexistent") is False

    def test_progress_token_callback(self):
        from src.desktop.controllers.ifm_controller import ProgressToken
        events = []
        token = ProgressToken(
            op_id="test",
            _update_callback=lambda cur, tot, msg: events.append((cur, tot, msg)),
        )
        token.update(5, 10, "half")
        assert token.is_cancelled() is False
        assert events == [(5, 10, "half")]
        token.cancel()
        assert token.is_cancelled() is True

    def test_scan_emits_progress(self, qapp, tmp_with_files):
        from src.desktop import IFMController
        c = IFMController(base_dir=tmp_with_files, ruleset_path=None)
        progress_events = []
        c.progress.connect(lambda op, cur, tot, msg: progress_events.append((op, cur, tot, msg)))

        c.scan_directory(tmp_with_files)
        _process_events(qapp)

        # يجب أن يكون هناك على الأقل حدث بدء وحدث اكتمال
        assert len(progress_events) >= 2
        # كل الأحداث باسم op_id="scan"
        assert all(p[0] == "scan" for p in progress_events)

    def test_dry_run_emits_progress(self, qapp, tmp_with_files, default_ruleset_path):
        from src.desktop import IFMController
        c = IFMController(
            base_dir=tmp_with_files, ruleset_path=default_ruleset_path
        )
        progress_events = []
        c.progress.connect(lambda op, cur, tot, msg: progress_events.append((op, cur, tot, msg)))

        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        c.dry_run()
        _process_events(qapp)

        # يجب أن تكون هناك أحداث dry_run
        dry_run_events = [p for p in progress_events if p[0] == "dry_run"]
        assert len(dry_run_events) >= 1


# ─── ErrorReporter tests ────────────────────────────────────────────────────

class TestErrorReporter:
    def test_creation(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        assert r.errors_count == 0
        assert r.warnings_count == 0
        assert r.total_count == 0

    def test_add_error_increments_count(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        r.add_error("فشل", "تعذّر الوصول", context="scan")
        assert r.errors_count == 1
        assert r.warnings_count == 0
        assert r.total_count == 1

    def test_add_warning_increments_count(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        r.add_warning("تنبيه", "ملف تالف", context="scan")
        assert r.errors_count == 0
        assert r.warnings_count == 1
        assert r.total_count == 1

    def test_clear_resets_counts(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        r.add_error("a", "b")
        r.add_warning("c", "d")
        r.clear()
        assert r.total_count == 0

    def test_errors_changed_signal(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        events = []
        r.errors_changed.connect(lambda errs, warns: events.append((errs, warns)))
        r.add_error("a", "b")
        assert events[-1] == (1, 0)
        r.add_warning("c", "d")
        assert events[-1] == (1, 1)
        r.clear()
        assert events[-1] == (0, 0)

    def test_records_returns_copy(self, qapp):
        from src.desktop.widgets.error_reporter import ErrorReporter
        r = ErrorReporter()
        r.add_error("a", "b", context="scan")
        records = r.records()
        assert len(records) == 1
        assert records[0].title == "a"
        assert records[0].severity == "error"
        # التعديل على النسخة لا يؤثّر على الأصل
        records.clear()
        assert r.total_count == 1


# ─── RecentActionsWidget tests ──────────────────────────────────────────────

class TestRecentActionsWidget:
    def test_creation(self, qapp):
        from src.desktop.widgets.recent_actions import RecentActionsWidget
        w = RecentActionsWidget(max_items=5)
        assert w is not None

    def test_set_entries_truncates_to_max(self, qapp):
        from src.desktop.widgets.recent_actions import RecentActionsWidget
        from src.core.action_log import ActionLogEntry

        w = RecentActionsWidget(max_items=3)
        entries = [
            ActionLogEntry(entry_id=i, action_type="move", file_path=f"/tmp/file{i}.txt", success=True)
            for i in range(10)
        ]
        w.set_entries(entries)
        assert w._list.count() == 3

    def test_add_entry_inserts_at_top(self, qapp):
        from src.desktop.widgets.recent_actions import RecentActionsWidget
        from src.core.action_log import ActionLogEntry

        w = RecentActionsWidget(max_items=5)
        e1 = ActionLogEntry(entry_id=1, action_type="move", file_path="a.txt", success=True)
        e2 = ActionLogEntry(entry_id=2, action_type="copy", file_path="b.txt", success=True)
        w.set_entries([e1])
        w.add_entry(e2)
        # العنصر الأول يجب أن يكون e2 (الأحدث)
        first_item = w._list.item(0)
        assert "copy" in first_item.text()

    def test_clear_view(self, qapp):
        from src.desktop.widgets.recent_actions import RecentActionsWidget
        from src.core.action_log import ActionLogEntry

        w = RecentActionsWidget(max_items=5)
        w.set_entries([
            ActionLogEntry(entry_id=1, action_type="move", file_path="a.txt", success=True)
        ])
        w.clear_view()
        # قائمة فارغة تعرض "لا إجراءات بعد"
        assert w._list.count() == 1
        assert "لا إجراءات" in w._list.item(0).text()

    def test_empty_state_shows_message(self, qapp):
        from src.desktop.widgets.recent_actions import RecentActionsWidget
        w = RecentActionsWidget(max_items=5)
        w.set_entries([])
        assert w._list.count() == 1
        assert "لا إجراءات" in w._list.item(0).text()


# ─── FilePreviewPanel tests ─────────────────────────────────────────────────

class TestFilePreviewPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.preview_panel import FilePreviewPanel
        p = FilePreviewPanel()
        assert p is not None

    def test_clear_preview_shows_no_file_message(self, qapp):
        from src.desktop.panels.preview_panel import FilePreviewPanel
        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.clear_preview()
        # نستخدم not isHidden() لأن isVisible() يتطلّب أن يكون كلّ سلسلة الآباء مرئية
        assert not p._no_file_label.isHidden()

    def test_preview_text_file(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        f = tmp_path / "notes.txt"
        f.write_text("hello world\nthis is a test", encoding="utf-8")

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(f))
        assert not p._text_preview.isHidden()
        assert "hello world" in p._text_preview.toPlainText()

    def test_preview_python_file(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        f = tmp_path / "script.py"
        f.write_text("print('hello')\n", encoding="utf-8")

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(f))
        assert not p._text_preview.isHidden()
        assert "print" in p._text_preview.toPlainText()

    def test_preview_json_file(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        f = tmp_path / "config.json"
        f.write_text('{"key": "value"}', encoding="utf-8")

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(f))
        assert not p._text_preview.isHidden()
        assert "key" in p._text_preview.toPlainText()

    def test_preview_nonexistent_file(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(tmp_path / "nonexistent.txt"))
        # يجب عرض رسالة خطأ
        assert "⚠" in p._unavailable_label.text() or p._text_preview.isHidden()

    def test_preview_unsupported_file(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\x03\x04\x05")

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(f))
        # يجب عرض "معاينة غير متاحة"
        assert not p._unavailable_label.isHidden()

    def test_preview_truncates_large_text(self, qapp, tmp_path):
        from src.desktop.panels.preview_panel import FilePreviewPanel

        f = tmp_path / "large.txt"
        # نص أكبر من حد المعاينة الافتراضي
        f.write_text("A" * (100 * 1024), encoding="utf-8")

        p = FilePreviewPanel(max_text_bytes=1024)
        p.preview_file(str(f))
        text = p._text_preview.toPlainText()
        # يجب أن يحتوي على رسالة القص
        assert "قُصعت" in text or "قُصّت" in text or len(text) < (100 * 1024)

    def test_set_max_text_bytes(self, qapp):
        from src.desktop.panels.preview_panel import FilePreviewPanel
        p = FilePreviewPanel()
        p.set_max_text_bytes(8192)
        assert p._max_text_bytes == 8192

    def test_preview_image_file(self, qapp, tmp_path):
        """يختبر معاينة صورة حقيقية عبر QPixmap"""
        from src.desktop.panels.preview_panel import FilePreviewPanel

        # نولّد صورة PNG صغيرة عبر PySide6.QtGui
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QImage, QColor, QPainter

        img_path = tmp_path / "test.png"
        img = QImage(QSize(64, 64), QImage.Format_ARGB32)
        img.fill(QColor(255, 0, 0))
        img.save(str(img_path))

        p = FilePreviewPanel()
        p.show()
        qapp.processEvents()
        p.preview_file(str(img_path))
        # يجب أن تكون تسمية الصورة مرئية
        assert not p._image_label.isHidden()
        assert p._image_label.pixmap() is not None


# ─── SettingsPanel tests ────────────────────────────────────────────────────

class TestSettingsPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings
        panel = SettingsPanel(settings=IFMSettings())
        assert panel is not None

    def test_loads_settings_into_fields(self, qapp):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings

        s = IFMSettings(
            dark_mode=False, rtl=False, auto_organize=True,
            semantic_search_enabled=True,
        )
        panel = SettingsPanel(settings=s)
        assert panel.dark_mode_check.isChecked() is False
        assert panel.rtl_check.isChecked() is False
        assert panel.auto_organize_check.isChecked() is True
        assert panel.semantic_search_check.isChecked() is True

    def test_get_settings_returns_updated_values(self, qapp):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings

        panel = SettingsPanel(settings=IFMSettings())
        panel.dark_mode_check.setChecked(False)
        panel.rtl_check.setChecked(False)
        panel.auto_organize_check.setChecked(True)

        s = panel.get_settings()
        assert s.dark_mode is False
        assert s.rtl is False
        assert s.auto_organize is True

    def test_reset_restores_defaults(self, qapp):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings
        from PySide6.QtWidgets import QMessageBox

        # نتجنّب النافذة المنبثقة بمونكي-بتش
        original = QMessageBox.question
        try:
            QMessageBox.question = staticmethod(lambda *a, **kw: QMessageBox.Yes)

            panel = SettingsPanel(settings=IFMSettings(dark_mode=False, rtl=False))
            panel._on_reset()
            assert panel.dark_mode_check.isChecked() is True
            assert panel.rtl_check.isChecked() is True
        finally:
            QMessageBox.question = original

    def test_save_emits_settings_changed(self, qapp, tmp_path, monkeypatch):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings
        from PySide6.QtWidgets import QMessageBox

        # تجنّب النوافذ المنبثقة
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

        # نوجّه الحفظ إلى tmp_path
        panel = SettingsPanel(settings=IFMSettings())
        # نضع المسار مباشرةً في _settings ليُستخدم في save
        panel._settings.last_base_dir = ""

        events = []
        panel.settings_changed.connect(lambda s: events.append(s))

        panel.dark_mode_check.setChecked(False)
        panel._on_save()

        assert len(events) == 1
        assert events[0].dark_mode is False

    def test_theme_change_emitted_on_save(self, qapp, monkeypatch):
        from src.desktop.panels.settings_panel import SettingsPanel
        from src.desktop.settings import IFMSettings
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

        panel = SettingsPanel(settings=IFMSettings(dark_mode=True))
        theme_events = []
        panel.theme_change_requested.connect(lambda mode: theme_events.append(mode))

        panel.dark_mode_check.setChecked(False)
        panel._on_save()

        assert len(theme_events) == 1
        assert theme_events[0] == "light"


# ─── IFMMainWindow integration (PR-09 features) ─────────────────────────────

class TestMainWindowPR09:
    def test_has_preview_and_settings_panels(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        assert hasattr(w, "preview_panel")
        assert hasattr(w, "settings_panel")
        assert w.preview_panel is not None
        assert w.settings_panel is not None

    def test_status_bar_has_progress_manager(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        assert w.status_bar.progress_manager is not None
        assert w.status_bar.error_reporter is not None

    def test_inventory_selection_updates_preview(self, qapp, tmp_with_files):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        from PySide6.QtCore import QItemSelectionModel
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_with_files, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_with_files))
        w.show()
        _process_events(qapp)

        # فحص الملفات
        c.scan_directory(tmp_with_files)
        _process_events(qapp)

        # اختيار أول ملف في الجدول
        # ملاحظة: selectRow() قد لا يُطلق إشارة itemSelectionChanged في Qt headless
        # لذلك نستخدم setCurrentCell مع علم SelectCurrent | Rows لضمان إطلاق الإشارة
        if w.inventory_panel.table.rowCount() > 0:
            w.inventory_panel.table.setCurrentCell(
                0, 0,
                QItemSelectionModel.SelectCurrent | QItemSelectionModel.Rows,
            )
            _process_events(qapp)
            # يجب أن تكون لوحة المعاينة قد حدّثت معلومات الملف
            assert "📁" in w.preview_panel._name_label.text()

    def test_progress_updates_during_scan(self, qapp, tmp_with_files):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_with_files, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_with_files))
        w.show()
        _process_events(qapp)

        # فحص يجب أن يُحدث الـ ProgressManager
        c.scan_directory(tmp_with_files)
        _process_events(qapp)

        # بعد الفحص، يجب أن يكون شريط التقدّم انتهى
        # (قد يكون مرئيًا أو مخفيًا — الأهم أنه اكتمل)
        assert not c.is_operation_active("scan")

    def test_settings_panel_connected_to_controller(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, IFMSettings, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))

        # محاكاة حفظ إعدادات جديدة
        new_settings = IFMSettings(dark_mode=False, auto_organize=True)
        w._on_settings_changed(new_settings)
        _process_events(qapp)

        # controller.settings يجب أن يُحدَّث
        assert c.settings.dark_mode is False
        assert c.settings.auto_organize is True

    def test_cancel_menu_action(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        # قائمة "إجراءات" موجودة
        # ملاحظة: نحتفظ بمرجع للقائمة (menubar + actions) لأن PySide6 قد يجمع
        # الـ wrappers المؤقتة وتُحذف كائنات C++ المرتبطة بها في pytest context
        menubar = w.menuBar()
        all_actions = menubar.actions()  # إبقاء المرجع حيًّا
        assert len(all_actions) >= 3
        # إيجاد قائمة "إجراءات" بالاسم بدلاً من الفهرس
        ops_action = None
        for a in all_actions:
            if a.text() == "إجراءات":
                ops_action = a
                break
        assert ops_action is not None, "قائمة 'إجراءات' غير موجودة"
        actions_menu = ops_action.menu()
        assert actions_menu is not None
        cancel_actions = [a for a in actions_menu.actions() if "إلغاء" in a.text()]
        assert len(cancel_actions) == 1


# ─── End-to-end PR-09 workflow ──────────────────────────────────────────────

class TestPR09EndToEnd:
    def test_scan_select_preview_settings(self, qapp, tmp_with_files, default_ruleset_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(
            base_dir=tmp_with_files, ruleset_path=default_ruleset_path
        )
        w = IFMMainWindow(controller=c, base_dir=str(tmp_with_files))
        w.show()
        _process_events(qapp)

        # 1) فحص
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        assert len(c.records) > 0

        # 2) اختيار ملف نصي لمعاينته
        text_record = None
        for r in c.records:
            if r.metadata.file_name == "notes.txt":
                text_record = r
                break
        assert text_record is not None

        w.preview_panel.preview_file(text_record.metadata.file_path)
        _process_events(qapp)
        assert "notes.txt" in w.preview_panel._name_label.text()
        # preview_panel داخل QStackedWidget — قد لا يكون التبويب الحالي
        # لذا نستخدم not isHidden() بدلاً من isVisible() لأن isVisible()
        # تتطلّب أن يكون كلّ سلسلة الآباء مرئية
        assert not w.preview_panel._text_preview.isHidden()

        # 3) حفظ إعدادات جديدة
        new_settings = c.settings
        new_settings.dark_mode = not new_settings.dark_mode
        c.apply_settings(new_settings)
        _process_events(qapp)
        # controller.settings يجب أن يُحدَّث
        assert c.settings.dark_mode == new_settings.dark_mode

    def test_error_reporter_collects_scan_failures(self, qapp, tmp_path, monkeypatch):
        """عند فشل فحص مجلد غير موجود، يجب أن يُسجَّل الخطأ في ErrorReporter"""
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        from PySide6.QtWidgets import QMessageBox
        # تجنّب النوافذ المنبثقة (QMessageBox.warning يُغلق الاختبار في headless)
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))

        # فحص مجلد غير موجود
        nonexistent = str(tmp_path / "does_not_exist")
        c.scan_directory(nonexistent)
        _process_events(qapp)

        # يجب أن يكون ErrorReporter قد سجّل الخطأ
        assert w.status_bar.error_reporter.errors_count >= 1


# ─── Export sanity check ────────────────────────────────────────────────────

class TestExportsPR09:
    def test_all_pr09_classes_exported(self):
        from src.desktop import (
            IFMMainWindow,
            IFMController,
            IFMStateSnapshot,
            ProgressToken,
            IFMSettings,
            FilePreviewPanel,
            SettingsPanel,
            ProgressManager,
            RecentActionsWidget,
            ErrorReporter,
            ErrorRecord,
            ErrorDetailsDialog,
        )
        # كلها فئات
        for cls in [
            IFMMainWindow, IFMController, IFMStateSnapshot, ProgressToken,
            IFMSettings, FilePreviewPanel, SettingsPanel, ProgressManager,
            RecentActionsWidget, ErrorReporter, ErrorRecord, ErrorDetailsDialog,
        ]:
            assert isinstance(cls, type), f"{cls} ليس نوعًا (class)"

    def test_nav_items_includes_preview_and_settings(self):
        from src.desktop.widgets.sidebar import NAV_ITEMS
        nav_ids = [nid for nid, _, _ in NAV_ITEMS]
        assert "preview" in nav_ids
        assert "settings" in nav_ids
        assert "inventory" in nav_ids
        assert "rules" in nav_ids
