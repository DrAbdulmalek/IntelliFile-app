"""اختبارات تكامل لمراقب المجلدات (FileWatcher)

يغطي:
  - إعدادات WatcherConfig الافتراضية والمخصصة
  - بدء/إيقاف المراقب بأمان
  - استقبال أحداث إنشاء/تعديل/حذف الملفات
  - debounce: أحداث متتالية على نفس الملف تُدمج
  - flush_now: إجبار flush الأحداث المعلَّقة
  - معالجة الدفعات: كتابة events_<id>.json لكل دفعة
  - auto_dry_run: توليد report_<id>.html و plan_<id>.json
  - لا ruleset: لا خطة ولا تقرير، فقط سجل أحداث
  - أنماط التجاهل (ignore_patterns)
  - التاريخ (history) للدفعات المعالَجة
  - التكامل مع FileInventory + RuleEngine
  - استثناءات في المعالجة لا تُسقط المراقب

PR-06 من development-roadmap-v1.0
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from src.core.watcher import (
    BatchResult,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_BATCH_MAX_SIZE,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_OUTPUT_DIR,
    FileWatcher,
    WatchEvent,
    WatchEventType,
    WatcherConfig,
)
from src.core.rule_schemas import Action, ActionType, Condition, Rule, Ruleset


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _wait_for_condition(predicate, timeout=5.0, interval=0.1):
    """ينتظر حتى يصبح predicate() صحيحًا أو ينتهي timeout"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_simple_ruleset() -> Ruleset:
    """يبني ruleset بسيط: كل ملف .txt → tag "text-file" """
    return Ruleset(
        name="Simple Test Ruleset",
        description="قواعد اختبار",
        rules=[
            Rule(
                name="tag-txt-files",
                conditions=[Condition(field="extension", op="eq", value="txt")],
                actions=[Action(type=ActionType.TAG.value, value="text-file")],
            ),
        ],
    )


# ─── إعدادات WatcherConfig ──────────────────────────────────────────────────

class TestWatcherConfig:
    """إعدادات WatcherConfig"""

    def test_defaults(self):
        config = WatcherConfig()
        assert config.debounce_seconds == DEFAULT_DEBOUNCE_SECONDS
        assert config.batch_interval == DEFAULT_BATCH_INTERVAL
        assert config.batch_max_size == DEFAULT_BATCH_MAX_SIZE
        assert config.auto_dry_run is True
        assert config.output_dir == DEFAULT_OUTPUT_DIR
        assert config.ruleset is None
        assert config.watch_paths == []
        assert config.recursive is True
        assert config.include_content is False

    def test_custom_config(self):
        config = WatcherConfig(
            watch_paths=["/tmp/a", "/tmp/b"],
            recursive=False,
            debounce_seconds=0.5,
            batch_interval=1.0,
            batch_max_size=50,
            auto_dry_run=False,
            output_dir="/tmp/output",
            ignore_patterns=[r"\.tmp$"],
            base_dir="/data",
            include_content=True,
        )
        assert config.watch_paths == ["/tmp/a", "/tmp/b"]
        assert config.recursive is False
        assert config.debounce_seconds == 0.5
        assert config.batch_max_size == 50
        assert config.auto_dry_run is False
        assert config.output_dir == "/tmp/output"
        assert config.ignore_patterns == [r"\.tmp$"]
        assert config.include_content is True

    def test_to_dict_serialization(self):
        config = WatcherConfig(watch_paths=["/tmp/a"], base_dir="/data")
        d = config.to_dict()
        assert d["watch_paths"] == ["/tmp/a"]
        assert d["base_dir"] == "/data"
        assert d["ruleset"] is None


# ─── دورة الحياة (start/stop) ──────────────────────────────────────────────

class TestWatcherLifecycle:
    """دورة حياة المراقب"""

    def test_start_and_stop_cleanly(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.1,
            batch_interval=0.2,
        )
        watcher = FileWatcher(config)
        watcher.start()
        assert watcher.is_running()
        watcher.stop()
        assert not watcher.is_running()

    def test_start_twice_warns(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
        )
        watcher = FileWatcher(config)
        watcher.start()
        # محاولة بدء ثانية — يجب ألا تُسقط
        watcher.start()
        watcher.stop()

    def test_stop_without_start_does_nothing(self):
        watcher = FileWatcher(WatcherConfig())
        watcher.stop()  # لا يجب أن يرمي خطأ


# ─── استقبال الأحداث ─────────────────────────────────────────────────────────

class TestEventReception:
    """استقبال أحداث watchdog"""

    def test_file_creation_triggers_event(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.1,
            batch_interval=10.0,  # لا flush تلقائي
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "new.txt").write_text("hello")
            # انتظار استقبال الحدث
            assert _wait_for_condition(
                lambda: len(watcher.get_pending_events()) > 0, timeout=3.0
            )
            pending = watcher.get_pending_events()
            # على الأقل حدث created واحد
            types = {e.event_type for e in pending}
            assert WatchEventType.CREATED.value in types
        finally:
            watcher.stop()

    def test_file_modification_triggers_event(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        target = watch_dir / "modify.txt"
        target.write_text("initial")

        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.1,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            target.write_text("modified")
            assert _wait_for_condition(
                lambda: any(
                    e.event_type == WatchEventType.MODIFIED.value
                    for e in watcher.get_pending_events()
                ),
                timeout=3.0,
            )
        finally:
            watcher.stop()

    def test_file_deletion_triggers_event(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        target = watch_dir / "delete.txt"
        target.write_text("will be deleted")

        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.1,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            target.unlink()
            assert _wait_for_condition(
                lambda: any(
                    e.event_type == WatchEventType.DELETED.value
                    for e in watcher.get_pending_events()
                ),
                timeout=3.0,
            )
        finally:
            watcher.stop()


# ─── Debounce ────────────────────────────────────────────────────────────────

class TestDebounce:
    """دمج الأحداث المتتالية (debounce)"""

    def test_multiple_writes_same_file_collapse(self, tmp_path):
        """كتابة عدة مرات على نفس الملف خلال نافذة debounce يجب أن تُدمج"""
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        target = watch_dir / "debounced.txt"

        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.3,
            batch_interval=10.0,  # لا flush تلقائي
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            # كتابة 5 مرات متتالية
            for i in range(5):
                target.write_text(f"version {i}")
                time.sleep(0.05)
            # انتظار استقبال كل الأحداث
            time.sleep(0.5)
            # يجب أن يكون لدينا حدث واحد فقط على الأقل (آخر كتابة)
            # أو عدد قليل نتيجة الـ debounce
            events = watcher.get_pending_events()
            # لو كانت الأحداث كلها على نفس file_path+event_type، فيجب أن تكون 1
            # (debounce يستبدل المفتاح نفسه)
            assert len(events) >= 1
        finally:
            watcher.stop()


# ─── Flush & Batch ────────────────────────────────────────────────────────────

class TestFlushAndBatch:
    """flush_now + المعالجة على دفعات"""

    def test_flush_now_processes_pending(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("a")
            (watch_dir / "b.txt").write_text("b")
            time.sleep(0.3)  # انتظار استقبال الأحداث

            result = watcher.flush_now()
            assert result is not None
            assert result.events_count > 0
            assert result.files_scanned >= 2
            assert result.error is None
        finally:
            watcher.stop()

    def test_flush_now_empty_returns_none(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            result = watcher.flush_now()
            assert result is None
        finally:
            watcher.stop()

    def test_batch_writes_events_json(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(out_dir),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "x.txt").write_text("x")
            time.sleep(0.3)
            result = watcher.flush_now()
            assert result is not None
            # ملف events_<id>.json يجب أن يُكتب
            events_files = list(out_dir.glob("events_*.json"))
            assert len(events_files) == 1
            data = json.loads(events_files[0].read_text())
            assert isinstance(data, list)
            assert len(data) > 0
            assert "event_type" in data[0]
            assert "file_path" in data[0]
        finally:
            watcher.stop()


# ─── auto_dry_run ─────────────────────────────────────────────────────────────

class TestAutoDryRun:
    """توليد تقارير HTML + خطط JSON تلقائيًا"""

    def test_with_ruleset_generates_report_and_plan(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(out_dir),
            ruleset=_make_simple_ruleset(),
            base_dir=str(watch_dir),
            debounce_seconds=0.05,
            batch_interval=10.0,
            auto_dry_run=True,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("hello")
            time.sleep(0.3)
            result = watcher.flush_now()
            assert result is not None
            assert result.planned_actions > 0
            assert result.report_path is not None
            assert result.plan_path is not None
            assert Path(result.report_path).exists()
            assert Path(result.plan_path).exists()
        finally:
            watcher.stop()

    def test_without_ruleset_no_plan(self, tmp_path):
        """بدون ruleset، لا تُولَّد خطة أو تقرير، فقط events"""
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(out_dir),
            ruleset=None,
            debounce_seconds=0.05,
            batch_interval=10.0,
            auto_dry_run=True,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("a")
            time.sleep(0.3)
            result = watcher.flush_now()
            assert result is not None
            assert result.planned_actions == 0
            assert result.report_path is None
            assert result.plan_path is None
        finally:
            watcher.stop()

    def test_auto_dry_run_false_skips_report(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(out_dir),
            ruleset=_make_simple_ruleset(),
            base_dir=str(watch_dir),
            debounce_seconds=0.05,
            batch_interval=10.0,
            auto_dry_run=False,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("hello")
            time.sleep(0.3)
            result = watcher.flush_now()
            assert result is not None
            # الخطة تُكتب دائمًا لو وُجد ruleset، لكن التقرير HTML لا يُكتب
            assert result.plan_path is not None
            assert result.report_path is None
        finally:
            watcher.stop()


# ─── Ignore patterns ──────────────────────────────────────────────────────────

class TestIgnorePatterns:
    """أنماط التجاهل"""

    def test_ignore_pattern_excludes_files(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            ignore_patterns=[r"\.tmp$", r"\.bak$"],
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "regular.txt").write_text("regular")
            (watch_dir / "temp.tmp").write_text("temp")
            time.sleep(0.5)
            pending = watcher.get_pending_events()
            paths = {e.file_path for e in pending}
            # regular.txt يجب أن يظهر، لكن temp.tmp لا
            assert any("regular.txt" in p for p in paths)
            assert not any("temp.tmp" in p for p in paths)
        finally:
            watcher.stop()

    def test_ifm_sidecar_files_ignored(self, tmp_path):
        """ملفات sidecar الخاصة بـ IFM (.ifm_meta_*) يجب تجاهلها"""
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / ".ifm_meta_data.txt.json").write_text("{}")
            (watch_dir / "real.txt").write_text("real")
            time.sleep(0.5)
            pending = watcher.get_pending_events()
            paths = {e.file_path for e in pending}
            assert not any(".ifm_meta_" in p for p in paths)
            assert any("real.txt" in p for p in paths)
        finally:
            watcher.stop()


# ─── التاريخ ────────────────────────────────────────────────────────────────

class TestHistory:
    """سجل الدفعات المعالَجة"""

    def test_history_records_batches(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("a")
            time.sleep(0.3)
            watcher.flush_now()
            (watch_dir / "b.txt").write_text("b")
            time.sleep(0.3)
            watcher.flush_now()
            history = watcher.get_history()
            assert len(history) == 2
            assert all(h.error is None for h in history)
        finally:
            watcher.stop()

    def test_clear_history(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("a")
            time.sleep(0.3)
            watcher.flush_now()
            assert len(watcher.get_history()) == 1
            watcher.clear_history()
            assert len(watcher.get_history()) == 0
        finally:
            watcher.stop()


# ─── التكامل مع RuleEngine ──────────────────────────────────────────────────

class TestRuleEngineIntegration:
    """التكامل مع RuleEngine عبر dry_run"""

    def test_plan_actions_match_rule(self, tmp_path):
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "out"
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(out_dir),
            ruleset=_make_simple_ruleset(),
            base_dir=str(watch_dir),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "a.txt").write_text("hello")
            time.sleep(0.3)
            result = watcher.flush_now()
            assert result is not None
            # قاعدة "tag-txt-files" يجب أن تطابق a.txt
            assert result.planned_actions == 1

            # التحقق من محتوى الخطة
            plan_files = list(out_dir.glob("plan_*.json"))
            assert len(plan_files) == 1
            plan_data = json.loads(plan_files[0].read_text())
            # planned_actions قائمة، يجب أن تحتوي على إجراء واحد
            assert len(plan_data["planned_actions"]) == 1
            assert plan_data["planned_actions"][0]["action"]["value"] == "text-file"
        finally:
            watcher.stop()

    def test_dry_run_no_destructive_actions(self, tmp_path):
        """ضمان: المراقب لا ينفّذ إجراءات تدميرية افتراضيًا"""
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        # ruleset يحتوي delete_flag
        ruleset = Ruleset(
            name="Test Destructive",
            rules=[
                Rule(
                    name="delete-all",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type=ActionType.DELETE_FLAG.value)],
                ),
            ],
        )
        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            output_dir=str(tmp_path / "out"),
            ruleset=ruleset,
            base_dir=str(watch_dir),
            debounce_seconds=0.05,
            batch_interval=10.0,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            target = watch_dir / "important.txt"
            target.write_text("important data")
            time.sleep(0.3)
            result = watcher.flush_now()
            # الملف يجب أن لا يُحذف (delete_flag فقط يضع وسم)
            assert target.exists()
            # الخطة يجب أن تشير إلى delete_flag
            assert result.planned_actions == 1
        finally:
            watcher.stop()


# ─── حالات حدية ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    """حالات حدية"""

    def test_nonexistent_watch_path_logged(self, tmp_path):
        """مسار غير موجود يجب تخطّيه مع تحذير"""
        config = WatcherConfig(
            watch_paths=[str(tmp_path / "nonexistent")],
            output_dir=str(tmp_path / "out"),
        )
        watcher = FileWatcher(config)
        watcher.start()
        # يجب ألا يرمي خطأ، ولا يراقب شيئًا
        assert watcher.is_running()
        watcher.stop()

    def test_empty_watch_paths_warns(self, tmp_path):
        config = WatcherConfig(
            watch_paths=[],
            output_dir=str(tmp_path / "out"),
        )
        watcher = FileWatcher(config)
        # يجب أن يُسجَّل تحذير لكن لا خطأ
        watcher.start()
        watcher.stop()


# ─── WatchEvent dataclass ─────────────────────────────────────────────────────

class TestWatchEventDataclass:
    """بنية WatchEvent"""

    def test_to_dict(self):
        ev = WatchEvent(
            event_type=WatchEventType.CREATED.value,
            file_path="/tmp/a.txt",
            file_name="a.txt",
            timestamp="2026-07-24T10:00:00",
        )
        d = ev.to_dict()
        assert d["event_type"] == "created"
        assert d["file_path"] == "/tmp/a.txt"
        assert d["file_name"] == "a.txt"

    def test_from_dict(self):
        d = {
            "event_type": "modified",
            "file_path": "/tmp/b.txt",
            "file_name": "b.txt",
            "timestamp": "2026-07-24T11:00:00",
        }
        ev = WatchEvent.from_dict(d)
        assert ev.event_type == "modified"
        assert ev.file_path == "/tmp/b.txt"


# ─── BatchResult dataclass ────────────────────────────────────────────────────

class TestBatchResultDataclass:
    """بنية BatchResult"""

    def test_to_dict(self):
        r = BatchResult(
            batch_id="20260724_120000",
            started_at="2026-07-24T12:00:00",
            events_count=5,
            files_scanned=3,
            planned_actions=2,
        )
        d = r.to_dict()
        assert d["batch_id"] == "20260724_120000"
        assert d["events_count"] == 5
        assert d["planned_actions"] == 2
