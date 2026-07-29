"""اختبارات IFM Desktop UX (PR-08) — PySide6 main window + core panels

يغطّي:
  - السمات (light/dark + RTL)
  - Sidebar (تنقّل + حالات active)
  - IFMController (تكامل مع كل وحدات core)
  - InventoryPanel (جدول + إحصائيات + اختيار)
  - RuleEnginePanel (تحميل + محاكاة + تنفيذ)
  - ActionLogPanel (تصفية + تصدير)
  - UndoLogPanel (undo last + undo all)
  - WatcherPanel (بدء + إيقاف + أحداث)
  - IFMMainWindow (تكامل شامل)
  - WatcherIndicator (states)
  - End-to-end: scan → dry-run → execute → undo → export

PR-08 من development-roadmap-v1.0 (IFM Phase C)
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


# ─── Theme tests ───────────────────────────────────────────────────────────

class TestTheme:
    def test_light_qss_not_empty(self):
        from src.desktop.theme import LIGHT_QSS
        assert len(LIGHT_QSS) > 1000
        assert "background-color" in LIGHT_QSS

    def test_dark_qss_not_empty(self):
        from src.desktop.theme import DARK_QSS
        assert len(DARK_QSS) > 1000
        assert "background-color" in DARK_QSS

    def test_apply_theme_light(self, qapp):
        from src.desktop.theme import apply_theme
        apply_theme(qapp, "light")
        assert qapp.styleSheet()  # غير فارغ

    def test_apply_theme_dark(self, qapp):
        from src.desktop.theme import apply_theme
        apply_theme(qapp, "dark")
        assert qapp.styleSheet()

    def test_apply_rtl(self, qapp):
        from src.desktop.theme import apply_rtl
        from PySide6.QtCore import Qt
        apply_rtl(qapp)
        assert qapp.layoutDirection() == Qt.RightToLeft

    def test_toggle_theme(self, qapp):
        from src.desktop.theme import apply_theme, toggle_theme
        apply_theme(qapp, "dark")
        qapp.setProperty("ifm_theme", "dark")
        new_mode = toggle_theme(qapp)
        assert new_mode == "light"
        new_mode2 = toggle_theme(qapp)
        assert new_mode2 == "dark"

    def test_init_app_theme_full(self, qapp):
        from src.desktop.theme import init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        assert qapp.property("ifm_theme") == "dark"
        assert qapp.styleSheet()

    def test_palettes_have_required_keys(self):
        from src.desktop.theme import LIGHT_PALETTE, DARK_PALETTE
        required = {"bg", "surface", "text", "border", "accent", "sidebar_bg"}
        for p in (LIGHT_PALETTE, DARK_PALETTE):
            for key in required:
                assert key in p


# ─── Sidebar tests ─────────────────────────────────────────────────────────

class TestSidebar:
    def test_creation(self, qapp):
        from src.desktop.widgets.sidebar import Sidebar
        s = Sidebar()
        assert s.objectName() == "Sidebar"
        assert s.width() == 220

    def test_nav_ids(self, qapp):
        from src.desktop.widgets.sidebar import Sidebar
        s = Sidebar()
        assert "inventory" in s.nav_ids
        assert "preview" in s.nav_ids
        assert "rules" in s.nav_ids
        assert "action_log" in s.nav_ids
        assert "undo_log" in s.nav_ids
        assert "watcher" in s.nav_ids
        assert "settings" in s.nav_ids
        assert len(s.nav_ids) == 7

    def test_default_active_is_inventory(self, qapp):
        from src.desktop.widgets.sidebar import Sidebar
        s = Sidebar()
        # inventory يجب أن يكون نشطًا افتراضيًا
        inv_btn = s._buttons["inventory"]
        assert inv_btn.property("active") is True

    def test_set_active_changes_state(self, qapp):
        from src.desktop.widgets.sidebar import Sidebar
        s = Sidebar()
        s.set_active("rules")
        assert s._buttons["rules"].property("active") is True
        assert s._buttons["inventory"].property("active") is False

    def test_nav_clicked_signal(self, qapp):
        from src.desktop.widgets.sidebar import Sidebar
        s = Sidebar()
        received = []
        s.nav_clicked.connect(lambda nid: received.append(nid))
        s._buttons["action_log"].click()
        assert received == ["action_log"]


# ─── WatcherIndicator tests ────────────────────────────────────────────────

class TestWatcherIndicator:
    def test_default_state_idle(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        assert w.state == "idle"
        assert "متوقف" in w.text()

    def test_set_state_running(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        w.set_state("running")
        assert w.state == "running"
        assert "يعمل" in w.text()

    def test_set_state_pending(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        w.set_state("pending")
        assert w.state == "pending"
        assert "معالجة" in w.text()

    def test_set_state_error(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        w.set_state("error")
        assert w.state == "error"
        assert "خطأ" in w.text()

    def test_set_running_true(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        w.set_running(True)
        assert w.state == "running"

    def test_set_running_false_from_running(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        w.set_running(True)
        w.set_running(False)
        assert w.state == "idle"

    def test_invalid_state_ignored(self, qapp):
        from src.desktop.widgets.watcher_indicator import WatcherIndicator
        w = WatcherIndicator()
        original_state = w.state
        w.set_state("invalid_state_name")
        assert w.state == original_state


# ─── IFMStatusBar tests ────────────────────────────────────────────────────

class TestIFMStatusBar:
    def test_creation(self, qapp):
        from src.desktop.widgets.status_bar import IFMStatusBar
        sb = IFMStatusBar()
        assert sb.watcher_indicator is not None
        assert sb.stats_label is not None

    def test_set_stats(self, qapp):
        from src.desktop.widgets.status_bar import IFMStatusBar
        sb = IFMStatusBar()
        sb.set_stats(10, 5, 2)
        assert "10" in sb.stats_label.text()
        assert "5" in sb.stats_label.text()
        assert "2" in sb.stats_label.text()

    def test_set_message(self, qapp):
        from src.desktop.widgets.status_bar import IFMStatusBar
        sb = IFMStatusBar()
        sb.set_message("اختبار")
        assert "اختبار" in sb._message_label.text()

    def test_set_watcher_state(self, qapp):
        from src.desktop.widgets.status_bar import IFMStatusBar
        sb = IFMStatusBar()
        sb.set_watcher_state("running")
        assert sb.watcher_indicator.state == "running"


# ─── IFMController tests ───────────────────────────────────────────────────

class TestIFMController:
    def test_creation_with_empty_ruleset(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        assert c.base_dir == tmp_path
        assert c.ruleset.name == "Empty"
        assert len(c.ruleset.rules) == 0
        assert len(c.records) == 0

    def test_creation_with_default_ruleset(self, qapp, tmp_path, default_ruleset_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=default_ruleset_path)
        assert c.ruleset.name == "Default Organization Rules"
        assert len(c.ruleset.rules) > 0

    def test_scan_directory_populates_records(self, qapp, tmp_with_files):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_with_files, ruleset_path=None)
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        assert len(c.records) > 0
        assert all(hasattr(r, "metadata") for r in c.records)

    def test_scan_nonexistent_directory_fails(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        failures = []
        c.scan_failed.connect(lambda msg: failures.append(msg))
        c.scan_directory(str(tmp_path / "nonexistent"))
        _process_events(qapp)
        assert len(failures) > 0

    def test_dry_run_without_scan_fails(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        failures = []
        c.dry_run_failed.connect(lambda msg: failures.append(msg))
        c.dry_run()
        assert len(failures) > 0

    def test_dry_run_with_records(self, qapp, tmp_with_files, default_ruleset_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_with_files, ruleset_path=default_ruleset_path)
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        c.dry_run()
        _process_events(qapp)
        plan = c.last_plan
        assert plan is not None
        assert plan.ruleset_name

    def test_execute_without_plan_fails(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        failures = []
        c.execute_failed.connect(lambda msg: failures.append(msg))
        c.execute()
        assert len(failures) > 0

    def test_full_workflow_scan_dryrun_execute(self, qapp, tmp_with_files, default_ruleset_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_with_files, ruleset_path=default_ruleset_path)
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        c.dry_run()
        _process_events(qapp)
        plan = c.last_plan
        if plan and plan.total_actions > 0:
            c.execute(confirm_destructive=False)
            _process_events(qapp)
            # يجب أن يكون هناك إدخالات في undo_log و action_log
            assert len(c.undo_log) > 0 or len(c.action_log) > 0

    def test_undo_last_empty_log(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        results = []
        c.undo_finished.connect(lambda e, s, msg: results.append((e, s, msg)))
        c.undo_last()
        _process_events(qapp)
        assert len(results) == 1
        assert results[0][1] is False  # success=False

    def test_export_action_log_json(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        out_path = tmp_path / "log.json"
        c.export_action_log_json(str(out_path))
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(data, (dict, list))

    def test_export_action_log_html(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        out_path = tmp_path / "log.html"
        c.export_action_log_html(str(out_path))
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "<html" in content.lower() or "<!doctype" in content.lower()

    def test_clear_action_log(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        cleared = []
        c.action_log_cleared.connect(lambda: cleared.append(True))
        c.clear_action_log()
        assert len(c.action_log) == 0
        assert len(cleared) == 1

    def test_reload_ruleset(self, qapp, tmp_path, default_ruleset_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        assert len(c.ruleset.rules) == 0
        c.reload_ruleset(default_ruleset_path)
        assert len(c.ruleset.rules) > 0

    def test_state_snapshot_emitted(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController, IFMStateSnapshot
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        snapshots = []
        c.state_changed.connect(lambda s: snapshots.append(s))
        c.scan_directory(tmp_path)
        _process_events(qapp)
        assert len(snapshots) > 0
        assert isinstance(snapshots[0], IFMStateSnapshot)


# ─── InventoryPanel tests ──────────────────────────────────────────────────

class TestInventoryPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        assert panel.table.columnCount() == 7
        assert panel.table.rowCount() == 0

    def test_set_records_populates_table(self, qapp, tmp_with_files):
        from src.desktop.panels.inventory_panel import InventoryPanel
        from src.core.file_inventory import FileInventory
        panel = InventoryPanel()
        inv = FileInventory()
        records = list(inv.scan(str(tmp_with_files), recursive=True))
        panel.set_records(records)
        assert panel.table.rowCount() == len(records)

    def test_set_stats(self, qapp):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        panel.set_stats(10, 1024, 2)
        assert "10" in panel.stats_label.text()
        assert "2" in panel.stats_label.text()

    def test_set_path(self, qapp):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        panel.set_path("/tmp/test")
        assert panel.path_edit.text() == "/tmp/test"

    def test_set_scanning_state(self, qapp):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        panel.set_scanning(True)
        assert not panel.scan_btn.isEnabled()
        panel.set_scanning(False)
        assert panel.scan_btn.isEnabled()

    def test_scan_requested_signal(self, qapp, tmp_path):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        received = []
        panel.scan_requested.connect(lambda p: received.append(p))
        panel.set_path(str(tmp_path))
        panel._on_scan()
        assert received == [str(tmp_path)]

    def test_scan_requested_empty_path(self, qapp):
        from src.desktop.panels.inventory_panel import InventoryPanel
        panel = InventoryPanel()
        received = []
        panel.scan_requested.connect(lambda p: received.append(p))
        panel._on_scan()  # path فارغ
        assert len(received) == 0
        assert "أدخل" in panel.stats_label.text()


# ─── RuleEnginePanel tests ─────────────────────────────────────────────────

class TestRuleEnginePanel:
    def test_creation(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        panel = RuleEnginePanel()
        assert panel.plan_table.columnCount() == 5
        assert not panel.execute_btn.isEnabled()  # لا خطة بعد

    def test_set_ruleset_info(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        panel = RuleEnginePanel()
        panel.set_ruleset_info("Test Rules", 5)
        assert "Test Rules" in panel.ruleset_label.text()
        assert "5" in panel.ruleset_label.text()

    def test_set_plan(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        from src.core.rule_schemas import DryRunPlan, PlannedAction, Action
        panel = RuleEnginePanel()
        plan = DryRunPlan(ruleset_name="test", base_dir="/tmp")
        plan.planned_actions.append(PlannedAction(
            rule_name="R1",
            file_path="/tmp/f.txt",
            file_name="f.txt",
            action=Action(type="move", target="/tmp/dst"),
        ))
        panel.set_plan(plan)
        assert panel.plan_table.rowCount() == 1
        assert panel.execute_btn.isEnabled()

    def test_set_plan_empty_disables_execute(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        from src.core.rule_schemas import DryRunPlan
        panel = RuleEnginePanel()
        plan = DryRunPlan(ruleset_name="empty", base_dir="/tmp")
        panel.set_plan(plan)
        assert panel.plan_table.rowCount() == 0
        assert not panel.execute_btn.isEnabled()

    def test_dry_run_clicked_emits_signal(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        panel = RuleEnginePanel()
        received = []
        panel.dry_run_requested.connect(lambda: received.append(True))
        panel._on_dry_run()
        assert len(received) == 1
        assert not panel.dry_run_btn.isEnabled()  # معطّل أثناء العمل

    def test_set_dry_run_failed(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        panel = RuleEnginePanel()
        panel.set_dry_run_failed("خطأ تجريبي")
        assert "خطأ تجريبي" in panel.dry_run_summary.text()
        assert panel.dry_run_btn.isEnabled()

    def test_set_execute_results(self, qapp):
        from src.desktop.panels.rule_engine_panel import RuleEnginePanel
        from src.core.rule_schemas import DryRunPlan, PlannedAction, Action, UndoEntry
        panel = RuleEnginePanel()
        plan = DryRunPlan(ruleset_name="test", base_dir="/tmp")
        plan.planned_actions.append(PlannedAction(
            rule_name="R1",
            file_path="/tmp/f.txt",
            file_name="f.txt",
            action=Action(type="move", target="/tmp/dst"),
        ))
        panel.set_plan(plan)
        # محاكاة نتيجة تنفيذ
        entries = [UndoEntry(action_type="move", file_path="/tmp/f.txt", rule_name="R1")]
        failures = []
        panel.set_execute_results(entries, failures)
        assert "1" in panel.execute_summary.text()
        assert panel.execute_btn.isEnabled()


# ─── ActionLogPanel tests ──────────────────────────────────────────────────

class TestActionLogPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        panel = ActionLogPanel()
        assert panel.table.columnCount() == 7

    def test_set_entries(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry
        panel = ActionLogPanel()
        entries = [
            ActionLogEntry(timestamp="2026-01-01 10:00:00", action_type="move",
                          rule_name="R1", file_path="/tmp/a", success=True, source="rule_engine"),
            ActionLogEntry(timestamp="2026-01-01 10:01:00", action_type="copy",
                          rule_name="R2", file_path="/tmp/b", success=False, source="manual"),
        ]
        panel.set_entries(entries)
        assert panel.table.rowCount() == 2
        assert "2" in panel.summary_label.text()

    def test_filter_success_only(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry
        panel = ActionLogPanel()
        entries = [
            ActionLogEntry(action_type="move", success=True),
            ActionLogEntry(action_type="copy", success=False),
        ]
        panel.set_entries(entries)
        panel.success_filter.setCurrentIndex(1)  # ناجح فقط
        assert panel.table.rowCount() == 1

    def test_filter_failure_only(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry
        panel = ActionLogPanel()
        entries = [
            ActionLogEntry(action_type="move", success=True),
            ActionLogEntry(action_type="copy", success=False),
        ]
        panel.set_entries(entries)
        panel.success_filter.setCurrentIndex(2)  # فاشل فقط
        assert panel.table.rowCount() == 1

    def test_filter_by_source(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry, SOURCE_WATCHER, SOURCE_RULE_ENGINE
        panel = ActionLogPanel()
        entries = [
            ActionLogEntry(action_type="move", success=True, source=SOURCE_RULE_ENGINE),
            ActionLogEntry(action_type="copy", success=True, source=SOURCE_WATCHER),
        ]
        panel.set_entries(entries)
        panel.source_filter.setCurrentText(SOURCE_WATCHER)
        assert panel.table.rowCount() == 1

    def test_add_entry(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry
        panel = ActionLogPanel()
        panel.add_entry(ActionLogEntry(action_type="move", success=True))
        assert panel.table.rowCount() == 1
        # إضافة آخر
        panel.add_entry(ActionLogEntry(action_type="copy", success=True))
        assert panel.table.rowCount() == 2

    def test_clear_view(self, qapp):
        from src.desktop.panels.action_log_panel import ActionLogPanel
        from src.core.action_log import ActionLogEntry
        panel = ActionLogPanel()
        panel.add_entry(ActionLogEntry(action_type="move", success=True))
        panel.clear_view()
        assert panel.table.rowCount() == 0
        assert "لا" in panel.summary_label.text()


# ─── UndoLogPanel tests ────────────────────────────────────────────────────

class TestUndoLogPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.undo_log_panel import UndoLogPanel
        panel = UndoLogPanel()
        assert panel.table.columnCount() == 7
        assert not panel.undo_last_btn.isEnabled()
        assert not panel.undo_all_btn.isEnabled()

    def test_set_entries_enables_buttons(self, qapp):
        from src.desktop.panels.undo_log_panel import UndoLogPanel
        from src.core.rule_schemas import UndoEntry
        panel = UndoLogPanel()
        entries = [UndoEntry(action_type="move", file_path="/tmp/a", rule_name="R1")]
        panel.set_entries(entries)
        assert panel.undo_last_btn.isEnabled()
        assert panel.undo_all_btn.isEnabled()
        assert "1" in panel.count_label.text()

    def test_set_empty_entries_disables_buttons(self, qapp):
        from src.desktop.panels.undo_log_panel import UndoLogPanel
        panel = UndoLogPanel()
        panel.set_entries([])
        assert not panel.undo_last_btn.isEnabled()
        assert not panel.undo_all_btn.isEnabled()

    def test_undo_result_re_enables_buttons(self, qapp):
        from src.desktop.panels.undo_log_panel import UndoLogPanel
        panel = UndoLogPanel()
        panel.set_undo_result(True, "")
        # بدون إدخالات، الأزرار تبقى معطّلة
        assert not panel.undo_last_btn.isEnabled()


# ─── WatcherPanel tests ────────────────────────────────────────────────────

class TestWatcherPanel:
    def test_creation(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        assert panel.start_btn.isEnabled()
        assert not panel.stop_btn.isEnabled()
        assert "متوقف" in panel.status_label.text()

    def test_set_running_true(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        panel.set_running(True)
        assert not panel.start_btn.isEnabled()
        assert panel.stop_btn.isEnabled()
        assert "يعمل" in panel.status_label.text()

    def test_set_running_false(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        panel.set_running(True)
        panel.set_running(False)
        assert panel.start_btn.isEnabled()
        assert not panel.stop_btn.isEnabled()

    def test_add_event(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        panel.add_event("created", "/tmp/new.txt")
        assert panel.events_table.rowCount() == 1
        assert panel.events_table.item(0, 1).text() == "created"
        assert panel.events_table.item(0, 2).text() == "/tmp/new.txt"

    def test_add_multiple_events_caps_at_200(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        for i in range(250):
            panel.add_event("created", f"/tmp/file_{i}.txt")
        assert panel.events_table.rowCount() == 200

    def test_set_history(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        from src.core.watcher import BatchResult
        panel = WatcherPanel()
        batches = [
            BatchResult(batch_id="b1", started_at="2026-01-01 10:00:00",
                       events_count=5, files_scanned=5, planned_actions=3),
        ]
        panel.set_history(batches)
        assert panel.history_table.rowCount() == 1
        assert panel.history_table.item(0, 1).text() == "5"

    def test_clear_events(self, qapp):
        from src.desktop.panels.watcher_panel import WatcherPanel
        panel = WatcherPanel()
        panel.add_event("created", "/tmp/x.txt")
        panel.clear_events()
        assert panel.events_table.rowCount() == 0


# ─── IFMMainWindow integration tests ───────────────────────────────────────

class TestIFMMainWindow:
    def test_creation_with_default_controller(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        assert w.windowTitle().startswith("IntelliFile")
        assert w.stack.count() == 7
        assert len(w.sidebar.nav_ids) == 7

    def test_navigation_switches_panels(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        # النقر على "rules" في الـ sidebar — الآن في الفهرس 2 (بعد inventory=0, preview=1)
        w.sidebar._buttons["rules"].click()
        _process_events(qapp)
        assert w.stack.currentIndex() == 2
        # النقر على "action_log" — الفهرس 3
        w.sidebar._buttons["action_log"].click()
        _process_events(qapp)
        assert w.stack.currentIndex() == 3

    def test_full_workflow_e2e(self, qapp, tmp_with_files, default_ruleset_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_with_files, ruleset_path=default_ruleset_path)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_with_files))
        w.show()
        _process_events(qapp)

        # 1) فحص
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        assert w.inventory_panel.table.rowCount() > 0
        assert "ملف" in w.inventory_panel.stats_label.text()

        # 2) محاكاة
        c.dry_run()
        _process_events(qapp)
        plan = c.last_plan
        assert plan is not None

        # 3) تنفيذ لو كان هناك إجراءات
        if plan.total_actions > 0:
            initial_undo = len(c.undo_log)
            c.execute(confirm_destructive=False)
            _process_events(qapp)
            # تحقق أن الإجراءات نُفّذت
            assert len(c.action_log) > 0
            assert len(c.undo_log) > initial_undo

            # 4) تراجع
            undo_before = len(c.undo_log)
            c.undo_last()
            _process_events(qapp)
            assert len(c.undo_log) < undo_before

        # 5) تصدير JSON + HTML
        json_path = tmp_with_files / "log.json"
        c.export_action_log_json(str(json_path))
        assert json_path.exists()
        html_path = tmp_with_files / "log.html"
        c.export_action_log_html(str(html_path))
        assert html_path.exists()

    def test_status_bar_updates_on_scan(self, qapp, tmp_with_files):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_with_files, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_with_files))
        w.show()
        _process_events(qapp)
        c.scan_directory(tmp_with_files)
        _process_events(qapp)
        # بعد الفحص، stats_label يجب أن يُحدّث
        assert "ملف" in w.status_bar.stats_label.text() or c.records

    def test_menu_actions_exist(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        # التحقق من وجود قوائم الـ menubar
        menu_texts = [a.text() for a in w.menuBar().actions()]
        assert "ملف" in menu_texts
        assert "عرض" in menu_texts
        assert "مساعدة" in menu_texts

    def test_theme_toggle(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        # تبديل السمة
        w._on_toggle_theme()
        assert qapp.property("ifm_theme") == "light"
        w._on_toggle_theme()
        assert qapp.property("ifm_theme") == "dark"

    def test_close_event_cleans_up(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        from PySide6.QtGui import QCloseEvent
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        # محاكاة حدث الإغلاق (QCloseEvent وليس QEvent)
        event = QCloseEvent()
        w.closeEvent(event)
        # يجب ألا يرمي استثناء

    def test_ruleset_loaded_on_init(self, qapp, tmp_path, default_ruleset_path):
        from src.desktop import IFMMainWindow, IFMController, init_app_theme
        init_app_theme(qapp, mode="dark", rtl=True)
        c = IFMController(base_dir=tmp_path, ruleset_path=default_ruleset_path)
        w = IFMMainWindow(controller=c, base_dir=str(tmp_path))
        assert "Default Organization Rules" in w.rule_engine_panel.ruleset_label.text()


# ─── Watcher integration tests ─────────────────────────────────────────────

class TestWatcherIntegration:
    def test_watcher_start_stop(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        assert not c.is_watcher_running()
        c.start_watcher(watch_paths=[str(tmp_path)])
        _process_events(qapp)
        assert c.is_watcher_running()
        c.stop_watcher()
        _process_events(qapp)
        assert not c.is_watcher_running()

    def test_watcher_start_without_paths(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        # start_watcher with no paths should use base_dir
        c.start_watcher()
        _process_events(qapp)
        assert c.is_watcher_running()
        c.stop_watcher()

    def test_watcher_signals_emitted(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        started = []
        stopped = []
        c.watcher_started.connect(lambda: started.append(True))
        c.watcher_stopped.connect(lambda: stopped.append(True))
        c.start_watcher(watch_paths=[str(tmp_path)])
        _process_events(qapp)
        c.stop_watcher()
        _process_events(qapp)
        assert len(started) == 1
        assert len(stopped) == 1

    def test_watcher_history_initially_empty(self, qapp, tmp_path):
        from src.desktop.controllers.ifm_controller import IFMController
        c = IFMController(base_dir=tmp_path, ruleset_path=None)
        assert c.get_watcher_history() == []
        assert c.get_watcher_pending() == []
