"""IFMController — منسّق التكامل بين كل وحدات IFM الأساسية

يقوم IFMController بدور الوسيط بين الواجهة (PySide6) وطبقة core:
  - يمتلك FileInventory + RuleEngine + UndoLog + ActionLog + FileWatcher
  - يوفّر Qt Signals لكل حدث مهم (scan_finished, dry_run_ready, action_logged, ...)
  - يدير دورة الحياة الكاملة: scan → dry_run → execute → undo → export
  - thread-safe: عمليات long-running تُنفَّذ عبر QThread أو blocking قصير
  - لا AI، لا medical — فقط orchestration

الاستخدام:
    controller = IFMController(base_dir="/data", ruleset_path="rules/default_rules.yaml")
    controller.scan_directory()         # → scan_finished signal
    plan = controller.dry_run()         # → dry_run_ready signal
    controller.execute(plan)            # → execute_finished signal
    controller.undo_last()              # → undo_finished signal

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from PySide6.QtCore import QObject, Signal

from ...core.action_log import ActionLog, ActionLogEntry
from ...core.file_inventory import FileInventory, InventoryStats
from ...core.rule_engine import RuleEngine
from ...core.rule_schemas import DryRunPlan, Ruleset, UndoEntry
from ...core.undo_log import UndoLog
from ...db.schemas import FileRecord

logger = logging.getLogger(__name__)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_ruleset(path: Optional[Union[str, Path]]) -> Ruleset:
    """يحمّل Ruleset من ملف YAML، أو يُرجع Ruleset فارغ لو None"""
    if path is None:
        return Ruleset(name="Empty", description="لا قواعد محمّلة", rules=[])
    p = Path(path)
    if not p.exists():
        logger.warning(f"IFMController: ملف القواعد غير موجود: {p}")
        return Ruleset(name="Empty", description=f"غير موجود: {p}", rules=[])
    return Ruleset.from_yaml(p)


# ─── State snapshot ─────────────────────────────────────────────────────────

@dataclass
class IFMStateSnapshot:
    """لقطة من حالة IFM لعرضها في الـ status bar"""
    inventory_count: int = 0
    last_scan_dir: str = ""
    last_scan_stats: Optional[InventoryStats] = None
    ruleset_name: str = ""
    ruleset_rules_count: int = 0
    plan_actions_count: int = 0
    plan_skipped_count: int = 0
    undo_log_size: int = 0
    action_log_size: int = 0
    watcher_running: bool = False
    watcher_pending: int = 0


# ─── Controller ─────────────────────────────────────────────────────────────

class IFMController(QObject):
    """منسّق IFM بين الواجهة وطبقة core

    Signals:
        scan_started(str): بداية فحص مجلد
        scan_finished(InventoryStats, list): نهاية فحص — الإحصائيات + السجلات
        scan_failed(str): فشل الفحص — رسالة الخطأ

        dry_run_started(): بداية محاكاة
        dry_run_ready(DryRunPlan): المحاكاة جاهزة
        dry_run_failed(str): فشل المحاكاة

        execute_started(int): بداية تنفيذ — عدد الإجراءات
        execute_finished(list, list): نهاية تنفيذ — UndoEntries + failures
        execute_failed(str): فشل التنفيذ

        undo_finished(UndoEntry, bool, str): تراجع عن إجراء — entry, success, error
        undo_log_changed(int): تغيّر حجم سجل التراجع

        action_logged(ActionLogEntry): إجراء جديد في السجل المرئي
        action_log_cleared(): تفريغ السجل المرئي

        watcher_started(): بدأ المراقب
        watcher_stopped(): توقّف المراقب
        watcher_event(str, str): حدث مراقبة — (event_type, file_path)
        watcher_batch(int): دفعة معالَجة — عدد الأحداث

        state_changed(IFMStateSnapshot): تغيّرت الحالة العامة
        error(str, str): خطأ — (title, message)
    """

    # ─── Signals ───────────────────────────────────────────────────────────
    scan_started = Signal(str)
    scan_finished = Signal(object, list)  # InventoryStats, list[FileRecord]
    scan_failed = Signal(str)

    dry_run_started = Signal()
    dry_run_ready = Signal(object)  # DryRunPlan
    dry_run_failed = Signal(str)

    execute_started = Signal(int)
    execute_finished = Signal(list, list)  # list[UndoEntry], list[dict] failures
    execute_failed = Signal(str)

    undo_finished = Signal(object, bool, str)  # UndoEntry, success, error
    undo_log_changed = Signal(int)

    action_logged = Signal(object)  # ActionLogEntry
    action_log_cleared = Signal()

    watcher_started = Signal()
    watcher_stopped = Signal()
    watcher_event = Signal(str, str)
    watcher_batch = Signal(int)

    state_changed = Signal(object)  # IFMStateSnapshot
    error = Signal(str, str)

    # ─── Init ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        base_dir: Union[str, Path],
        ruleset_path: Optional[Union[str, Path]] = None,
        undo_log_path: Optional[Union[str, Path]] = None,
        action_log_path: Optional[Union[str, Path]] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.ruleset_path = ruleset_path

        # ─── Core modules ────────────────────────────────────────────────
        self.inventory = FileInventory()
        self.ruleset: Ruleset = _load_ruleset(ruleset_path)
        self.rule_engine = RuleEngine(self.ruleset)
        self.undo_log = UndoLog(undo_log_path)
        self.action_log = ActionLog(action_log_path)

        # ─── State ───────────────────────────────────────────────────────
        self._records: List[FileRecord] = []
        self._last_plan: Optional[DryRunPlan] = None
        self._last_scan_dir: str = ""
        self._last_scan_stats: Optional[InventoryStats] = None

        # ─── Watcher (lazy) ──────────────────────────────────────────────
        self._watcher = None  # FileWatcher — يُنشأ عند start_watcher

        # إشارة أولية للحالة
        self._emit_state()

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _emit_state(self) -> None:
        """يبث لقطة الحالة الحالية"""
        snap = IFMStateSnapshot(
            inventory_count=len(self._records),
            last_scan_dir=self._last_scan_dir,
            last_scan_stats=self._last_scan_stats,
            ruleset_name=self.ruleset.name,
            ruleset_rules_count=len(self.ruleset.rules),
            plan_actions_count=len(self._last_plan.planned_actions) if self._last_plan else 0,
            plan_skipped_count=len(self._last_plan.skipped_files) if self._last_plan else 0,
            undo_log_size=len(self.undo_log),
            action_log_size=len(self.action_log),
            watcher_running=self._watcher is not None and self._watcher.is_running(),
            watcher_pending=len(self._watcher.get_pending_events()) if self._watcher else 0,
        )
        self.state_changed.emit(snap)

    # ─── FileInventory ──────────────────────────────────────────────────────

    def scan_directory(self, directory: Optional[Union[str, Path]] = None) -> None:
        """يفحص مجلدًا ويبني قائمة FileRecord

        Args:
            directory: المسار. إن None، يُستخدم base_dir.
        """
        target = Path(directory) if directory else self.base_dir
        if not target.exists():
            self.scan_failed.emit(f"المجلد غير موجود: {target}")
            self.error.emit("فشل الفحص", f"المجلد غير موجود: {target}")
            return
        self.scan_started.emit(str(target))
        try:
            stats = InventoryStats()
            records: List[FileRecord] = []
            for record in self.inventory.scan(str(target), recursive=True):
                records.append(record)
                stats.total_files += 1
                stats.indexed_files += 1
                stats.total_size_bytes += record.metadata.file_size
            # محاولة حساب duplicate_candidates عبر DuplicateDetector (exact only)
            try:
                from ...core.duplicate_detector import DuplicateDetector
                detector = DuplicateDetector(use_embeddings=False)
                report = detector.detect(records)
                stats.duplicate_candidates = report.total_duplicate_files
            except Exception:
                pass

            self._records = records
            self._last_scan_dir = str(target)
            self._last_scan_stats = stats
            self.scan_finished.emit(stats, records)
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.scan_directory failed")
            self.scan_failed.emit(str(e))
            self.error.emit("فشل الفحص", str(e))

    @property
    def records(self) -> List[FileRecord]:
        return list(self._records)

    # ─── RuleEngine ─────────────────────────────────────────────────────────

    def reload_ruleset(self, path: Optional[Union[str, Path]] = None) -> None:
        """يعيد تحميل القواعد من ملف YAML"""
        target = path or self.ruleset_path
        if target is None:
            self.error.emit("إعادة تحميل", "لا يوجد مسار قواعد")
            return
        self.ruleset = _load_ruleset(target)
        self.ruleset_path = target
        self.rule_engine = RuleEngine(self.ruleset)
        self._last_plan = None
        self._emit_state()

    def dry_run(self) -> None:
        """يولّد خطة محاكاة من السجلات الحالية"""
        if not self._records:
            self.dry_run_failed.emit("لا توجد سجلات — افحص مجلدًا أولًا")
            self.error.emit("محاكاة", "افحص مجلدًا أولًا")
            return
        self.dry_run_started.emit()
        try:
            plan = self.rule_engine.dry_run(self._records, base_dir=str(self.base_dir))
            self._last_plan = plan
            self.dry_run_ready.emit(plan)
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.dry_run failed")
            self.dry_run_failed.emit(str(e))
            self.error.emit("فشل المحاكاة", str(e))

    @property
    def last_plan(self) -> Optional[DryRunPlan]:
        return self._last_plan

    def execute(self, plan: Optional[DryRunPlan] = None, confirm_destructive: bool = False) -> None:
        """ينفّذ خطة محاكاة (افتراضيًا: آخر خطة جاهزة)"""
        target_plan = plan or self._last_plan
        if target_plan is None:
            self.execute_failed.emit("لا توجد خطة — نفّذ محاكاة أولًا")
            self.error.emit("تنفيذ", "نفّذ محاكاة أولًا")
            return
        self.execute_started.emit(len(target_plan.planned_actions))
        try:
            # نمرّر مسار undo_log للقرص لو متاح؛ RuleEngine يحمّله داخليًا.
            # لكنه لا يشارك مثيل UndoLog معنا — لذا ندمج الإدخالات بعد التنفيذ.
            undo_path = self.undo_log.path if self.undo_log.path else None
            entries = self.rule_engine.execute(
                target_plan,
                undo_log_path=undo_path,
                confirm_destructive=confirm_destructive,
                action_log=self.action_log,
                use_safe_mover=True,
            )
            # دمج الإدخالات المُرجعة في undo_log الخاص بالـ controller
            # (نتجنّب التكرار: نعيد تحميل من القرص لو كان path متاحًا،
            #  وإلا نلحق الإدخالات يدويًا)
            if undo_path:
                self.undo_log.load()
            else:
                from ...core.rule_schemas import UndoEntry
                for entry in entries:
                    if entry not in self.undo_log.entries:
                        self.undo_log.append(entry)

            # كل إجراء نُفّذ يُسجَّل في ActionLog تلقائيًا (من RuleEngine)
            # نبثّ إشارات لكل entry جديد
            for _ in entries:
                recent = self.action_log.list_entries(limit=1)
                if recent:
                    self.action_logged.emit(recent[0])
            failures = [e for e in entries if not e.success]
            self.execute_finished.emit(entries, failures)
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.execute failed")
            self.execute_failed.emit(str(e))
            self.error.emit("فشل التنفيذ", str(e))

    # ─── UndoLog ────────────────────────────────────────────────────────────

    def undo_last(self) -> None:
        """يتراجع عن آخر إجراء"""
        if len(self.undo_log) == 0:
            self.undo_finished.emit(None, False, "سجل التراجع فارغ")
            return
        try:
            # نأخذ آخر entry قبل التراجع (للإشارة)
            entries_before = self.undo_log.list_entries()
            target_entry = entries_before[-1] if entries_before else None
            rolled = self.undo_log.rollback_last()
            # تسجيل العملية العكسية في ActionLog (log_rollback يأخذ UndoEntry)
            if rolled is not None:
                self.action_log.log_rollback(rolled, success=True)
                recent = self.action_log.list_entries(limit=1)
                if recent:
                    self.action_logged.emit(recent[0])
            self.undo_finished.emit(target_entry, True, "")
            self.undo_log_changed.emit(len(self.undo_log))
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.undo_last failed")
            self.undo_finished.emit(None, False, str(e))
            self.error.emit("فشل التراجع", str(e))

    def undo_all(self) -> None:
        """يتراجع عن كل الإجراءات"""
        try:
            rolled = self.undo_log.rollback_all()
            for entry in rolled:
                self.action_log.log_rollback(entry, success=True)
            self.undo_log_changed.emit(len(self.undo_log))
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.undo_all failed")
            self.error.emit("فشل التراجع الكلي", str(e))

    def clear_action_log(self) -> None:
        """يفرّغ السجل المرئي"""
        self.action_log.clear()
        self.action_log_cleared.emit()
        self._emit_state()

    def export_action_log_json(self, output_path: Union[str, Path]) -> str:
        """يصدّر السجل المرئي إلى JSON"""
        return self.action_log.export_json(output_path)

    def export_action_log_html(self, output_path: Union[str, Path]) -> str:
        """يصدّر السجل المرئي إلى HTML"""
        return self.action_log.export_html(output_path)

    def save_undo_log(self) -> None:
        """يحفظ سجل التراجع على القرص"""
        self.undo_log.save()

    def save_action_log(self) -> None:
        """يحفظ السجل المرئي على القرص"""
        self.action_log.save()

    # ─── Watcher ────────────────────────────────────────────────────────────

    def start_watcher(
        self,
        watch_paths: Optional[List[str]] = None,
        recursive: bool = True,
        auto_dry_run: bool = True,
    ) -> None:
        """يبدأ مراقبة المجلدات

        Args:
            watch_paths: المسارات. إن None، يُستخدم base_dir.
            recursive: مراقبة متكررة
            auto_dry_run: توليد تقارير فقط (لا تنفيذ)
        """
        if self._watcher is not None and self._watcher.is_running():
            self.error.emit("مراقب", "المراقب يعمل بالفعل")
            return
        paths = watch_paths or [str(self.base_dir)]
        if not paths:
            self.error.emit("مراقب", "لا توجد مسارات")
            return
        try:
            from ...core.watcher import FileWatcher, WatcherConfig
            config = WatcherConfig(
                watch_paths=paths,
                recursive=recursive,
                auto_dry_run=auto_dry_run,
                ruleset=self.ruleset,
                base_dir=str(self.base_dir),
                output_dir=str(self.base_dir / ".ifm_watcher"),
                action_log=self.action_log,
            )
            self._watcher = FileWatcher(config)
            # ربط أحداث المراقب بإشارات الـ controller
            self._watcher.start()
            self.watcher_started.emit()
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.start_watcher failed")
            self.error.emit("فشل بدء المراقب", str(e))

    def stop_watcher(self) -> None:
        """يوقف المراقب"""
        if self._watcher is None:
            return
        try:
            self._watcher.stop()
            self.watcher_stopped.emit()
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.stop_watcher failed")
            self.error.emit("فشل إيقاف المراقب", str(e))

    def is_watcher_running(self) -> bool:
        if self._watcher is None:
            return False
        return self._watcher.is_running()

    def get_watcher_history(self) -> list:
        if self._watcher is None:
            return []
        return self._watcher.get_history()

    def get_watcher_pending(self) -> list:
        if self._watcher is None:
            return []
        return self._watcher.get_pending_events()

    # ─── Cleanup ────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """ينظّف الموارد قبل الإغلاق"""
        if self._watcher is not None and self._watcher.is_running():
            try:
                self._watcher.stop(timeout=2.0)
            except Exception:
                pass
        try:
            self.undo_log.save()
        except Exception:
            pass
        try:
            self.action_log.save()
        except Exception:
            pass
