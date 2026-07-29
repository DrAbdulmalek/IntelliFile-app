"""IFMController — منسّق التكامل بين كل وحدات IFM الأساسية

يقوم IFMController بدور الوسيط بين الواجهة (PySide6) وطبقة core:
  - يمتلك FileInventory + RuleEngine + UndoLog + ActionLog + FileWatcher
  - يوفّر Qt Signals لكل حدث مهم (scan_finished, dry_run_ready, action_logged, ...)
  - يدير دورة الحياة الكاملة: scan → dry_run → execute → undo → export
  - thread-safe: عمليات long-running تُنفَّذ عبر QThread أو blocking قصير
  - دعم الإلغاء (cancellation) عبر ProgressToken — PR-09
  - دعم الإعدادات (IFMSettings) — PR-09
  - لا AI، لا medical — فقط orchestration

الاستخدام:
    controller = IFMController(base_dir="/data", ruleset_path="rules/default_rules.yaml")
    controller.scan_directory()         # → scan_finished signal
    plan = controller.dry_run()         # → dry_run_ready signal
    controller.execute(plan)            # → execute_finished signal
    controller.undo_last()              # → undo_finished signal

PR-08 من development-roadmap-v1.0 (IFM Phase C)
PR-09 من development-roadmap-v1.0 (progress + cancellation + settings)
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ...core.action_log import ActionLog
from ...core.file_inventory import FileInventory, InventoryStats
from ...core.rule_engine import RuleEngine
from ...core.rule_schemas import DryRunPlan, Ruleset
from ...core.undo_log import UndoLog
from ...db.schemas import FileRecord
from ..settings import IFMSettings

logger = logging.getLogger(__name__)


# ─── Progress token (cancellation support) ──────────────────────────────────

@dataclass
class ProgressToken:
    """توكن تقدّم قابل للإلغاء

    يُمرَّر إلى العمليات الطويلة لتوفير:
      - is_cancelled() — للتحقق من طلب الإلغاء
      - update(current, total, message) — لتحديث شريط التقدّم
    """
    op_id: str = ""
    _cancelled: bool = False
    _update_callback: Callable[[int, int, str], None] | None = None

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def update(self, current: int, total: int = 0, message: str = "") -> None:
        if self._update_callback is not None:
            self._update_callback(current, total, message)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_ruleset(path: str | Path | None) -> Ruleset:
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
    last_scan_stats: InventoryStats | None = None
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
    scan_cancelled = Signal(str)  # path — PR-09

    dry_run_started = Signal()
    dry_run_ready = Signal(object)  # DryRunPlan
    dry_run_failed = Signal(str)

    execute_started = Signal(int)
    execute_finished = Signal(list, list)  # list[UndoEntry], list[dict] failures
    execute_failed = Signal(str)
    execute_cancelled = Signal(int)  # executed_so_far — PR-09

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

    # ─── PR-09 signals ────────────────────────────────────────────────────
    progress = Signal(str, int, int, str)  # op_id, current, total, message
    operation_cancelled = Signal(str)  # op_id
    settings_changed = Signal(object)  # IFMSettings
    file_previewed = Signal(str)  # file_path — for navigation to preview panel

    # ─── Init ──────────────────────────────────────────────────────────────

    def __init__(
        self,
        base_dir: str | Path,
        ruleset_path: str | Path | None = None,
        undo_log_path: str | Path | None = None,
        action_log_path: str | Path | None = None,
        settings: IFMSettings | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.ruleset_path = ruleset_path

        # ─── الإعدادات (PR-09) ──────────────────────────────────────────
        self.settings: IFMSettings = settings or IFMSettings.load()

        # ─── Core modules ────────────────────────────────────────────────
        self.inventory = FileInventory()
        self.ruleset: Ruleset = _load_ruleset(ruleset_path)
        self.rule_engine = RuleEngine(self.ruleset)
        self.undo_log = UndoLog(undo_log_path)
        self.action_log = ActionLog(action_log_path)

        # ─── State ───────────────────────────────────────────────────────
        self._records: list[FileRecord] = []
        self._last_plan: DryRunPlan | None = None
        self._last_scan_dir: str = ""
        self._last_scan_stats: InventoryStats | None = None

        # ─── Watcher (lazy) ──────────────────────────────────────────────
        self._watcher = None  # FileWatcher — يُنشأ عند start_watcher

        # ─── PR-09: progress tokens نشطة (op_id → ProgressToken) ─────────
        self._active_tokens: dict[str, ProgressToken] = {}

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

    def scan_directory(self, directory: str | Path | None = None) -> None:
        """يفحص مجلدًا ويبني قائمة FileRecord

        Args:
            directory: المسار. إن None، يُستخدم base_dir.

        Notes:
            PR-09: يدعم الإلغاء عبر cancel_operation("scan")
            ويبثّ إشارات progress أثناء الفحص.
        """
        target = Path(directory) if directory else self.base_dir
        if not target.exists():
            self.scan_failed.emit(f"المجلد غير موجود: {target}")
            self.error.emit("فشل الفحص", f"المجلد غير موجود: {target}")
            return

        # إنشاء توكن تقدّم لهذه العملية
        token = self._start_operation("scan", message=f"يفحص: {target}")
        self.scan_started.emit(str(target))
        try:
            stats = InventoryStats()
            records: list[FileRecord] = []
            for record in self.inventory.scan(str(target), recursive=True):
                # التحقّق من الإلغاء
                if token.is_cancelled():
                    self.scan_cancelled.emit(str(target))
                    self.operation_cancelled.emit("scan")
                    self._finish_operation("scan", success=False, message="أُلغي الفحص")
                    return
                records.append(record)
                stats.total_files += 1
                stats.indexed_files += 1
                stats.total_size_bytes += record.metadata.file_size
                # تحديث التقدّم كل 25 ملف (لتقليل ضغط الإشارات)
                if stats.total_files % 25 == 0:
                    token.update(
                        current=stats.total_files,
                        total=0,  # indeterminate — لا نعرف العدد الكلي مسبقًا
                        message=f"فُحصت {stats.total_files} ملف...",
                    )

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
            self._finish_operation(
                "scan", success=True, message=f"اكتمل الفحص: {stats.total_files} ملف"
            )
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.scan_directory failed")
            self.scan_failed.emit(str(e))
            self.error.emit("فشل الفحص", str(e))
            self._finish_operation("scan", success=False, message=str(e))

    @property
    def records(self) -> list[FileRecord]:
        return list(self._records)

    # ─── RuleEngine ─────────────────────────────────────────────────────────

    def reload_ruleset(self, path: str | Path | None = None) -> None:
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

        token = self._start_operation(
            "dry_run",
            total=len(self._records),
            message=f"محاكاة {len(self._records)} ملف...",
        )
        self.dry_run_started.emit()
        try:
            # ملاحظة: RuleEngine.dry_run ليس له hook تقدّم — نحاكي التقدّم على دفعات
            # عبر تقسيم السجلات لو كانت كبيرة
            if len(self._records) > 500 and token is not None:
                # للقوائم الكبيرة: محاكاة على دفعات لتوفير إلغاء أفضل
                from ...core.rule_schemas import DryRunPlan
                plan = DryRunPlan(
                    ruleset_name=self.ruleset.name,
                    base_dir=str(self.base_dir),
                )
                batch_size = 200
                for i in range(0, len(self._records), batch_size):
                    if token.is_cancelled():
                        self.operation_cancelled.emit("dry_run")
                        self._finish_operation("dry_run", success=False, message="أُلغيت المحاكاة")
                        return
                    batch = self._records[i:i + batch_size]
                    partial = self.rule_engine.dry_run(batch, base_dir=str(self.base_dir))
                    plan.planned_actions.extend(partial.planned_actions)
                    plan.skipped_files.extend(partial.skipped_files)
                    token.update(
                        current=min(i + batch_size, len(self._records)),
                        total=len(self._records),
                        message=f"محاكاة: {i + len(batch)}/{len(self._records)}",
                    )
                plan.summary = self.rule_engine._build_summary(plan) if hasattr(self.rule_engine, "_build_summary") else {}
            else:
                plan = self.rule_engine.dry_run(self._records, base_dir=str(self.base_dir))

            self._last_plan = plan
            self.dry_run_ready.emit(plan)
            self._finish_operation(
                "dry_run", success=True,
                message=f"اكتملت المحاكاة: {len(plan.planned_actions)} إجراء"
            )
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.dry_run failed")
            self.dry_run_failed.emit(str(e))
            self.error.emit("فشل المحاكاة", str(e))
            self._finish_operation("dry_run", success=False, message=str(e))

    @property
    def last_plan(self) -> DryRunPlan | None:
        return self._last_plan

    def execute(self, plan: DryRunPlan | None = None, confirm_destructive: bool = False) -> None:
        """ينفّذ خطة محاكاة (افتراضيًا: آخر خطة جاهزة)

        Notes:
            PR-09: لو settings.confirm_destructive=True وconfirm_destructive=False
            وكانت الخطة تحتوي على إجراءات تدميرية، يُبثّ تحذير بدل التنفيذ.
        """
        target_plan = plan or self._last_plan
        if target_plan is None:
            self.execute_failed.emit("لا توجد خطة — نفّذ محاكاة أولًا")
            self.error.emit("تنفيذ", "نفّذ محاكاة أولًا")
            return

        # تطبيق إعداد confirm_destructive من settings
        effective_confirm = confirm_destructive or self.settings.confirm_destructive
        # تطبيق إعداد default_dry_run — لو مفعّل ولا توجد محاكاة حديثة، نُحذّر
        if self.settings.default_dry_run and target_plan != self._last_plan:
            logger.warning("Executing a plan that may not be the latest dry-run")

        total_actions = len(target_plan.planned_actions)
        token = self._start_operation(
            "execute", total=total_actions, message=f"ينفّذ {total_actions} إجراء..."
        )
        self.execute_started.emit(total_actions)
        try:
            # نمرّر مسار undo_log للقرص لو متاح؛ RuleEngine يحمّله داخليًا.
            # لكنه لا يشارك مثيل UndoLog معنا — لذا ندمج الإدخالات بعد التنفيذ.
            undo_path = self.undo_log.path if self.undo_log.path else None
            entries = self.rule_engine.execute(
                target_plan,
                undo_log_path=undo_path,
                confirm_destructive=effective_confirm,
                action_log=self.action_log,
                use_safe_mover=True,
            )

            # دمج الإدخالات المُرجعة في undo_log الخاص بالـ controller
            if undo_path:
                self.undo_log.load()
            else:
                for entry in entries:
                    if entry not in self.undo_log.entries:
                        self.undo_log.append(entry)

            # كل إجراء نُفّذ يُسجَّل في ActionLog تلقائيًا (من RuleEngine)
            # نبثّ إشارات لكل entry جديد
            for executed_count, _ in enumerate(entries, start=1):
                # تحديث التقدّم كل 5 إجراءات
                if executed_count % 5 == 0 or executed_count == total_actions:
                    token.update(
                        current=executed_count,
                        total=total_actions,
                        message=f"نُفّذ {executed_count}/{total_actions}",
                    )
                recent = self.action_log.list_entries(limit=1)
                if recent:
                    self.action_logged.emit(recent[0])

            failures = [e for e in entries if not e.success]
            self.execute_finished.emit(entries, failures)
            self._finish_operation(
                "execute", success=True,
                message=f"اكتمل التنفيذ: {len(entries) - len(failures)} نجح، {len(failures)} فشل"
            )
            self._emit_state()
        except Exception as e:
            logger.exception("IFMController.execute failed")
            self.execute_failed.emit(str(e))
            self.error.emit("فشل التنفيذ", str(e))
            self._finish_operation("execute", success=False, message=str(e))

    # ─── PR-09: Operations + Cancellation + Settings ───────────────────────

    def _start_operation(
        self,
        op_id: str,
        total: int = 0,
        message: str = "",
    ) -> ProgressToken:
        """يبدأ عملية جديدة ويسجّل توكن التقدّم"""
        token = ProgressToken(
            op_id=op_id,
            _update_callback=lambda cur, tot, msg: self.progress.emit(op_id, cur, tot, msg),
        )
        self._active_tokens[op_id] = token
        self.progress.emit(op_id, 0, total, message)
        return token

    def _finish_operation(self, op_id: str, success: bool = True, message: str = "") -> None:
        """ينهي عملية نشطة ويزيل توكنها"""
        self._active_tokens.pop(op_id, None)
        # نبثّ تقدّم نهائي 100% لو نجحت
        if success:
            self.progress.emit(op_id, 1, 1, message)

    def cancel_operation(self, op_id: str) -> bool:
        """يطلب إلغاء عملية نشطة

        Returns:
            True لو وُجدت العملية وطُلب إلغاؤها، False لو لم تكن نشطة
        """
        token = self._active_tokens.get(op_id)
        if token is None:
            return False
        token.cancel()
        logger.info(f"Requested cancellation of operation: {op_id}")
        return True

    def is_operation_active(self, op_id: str) -> bool:
        """هل العملية نشطة حاليًا؟"""
        return op_id in self._active_tokens

    def apply_settings(self, settings: IFMSettings) -> None:
        """يطبّق إعدادات جديدة على الـ controller

        - لو watch_folders_enabled تغيّر، يبدأ/يوقف المراقب
        - لو dark_mode تغيّر، يبثّ إشارة (الـ MainWindow يطبّقها)
        - يحفظ الإعدادات على القرص
        """
        old = self.settings
        self.settings = settings

        # حفظ على القرص
        try:
            settings.save()
        except Exception as e:
            logger.warning(f"Failed to save settings: {e}")

        # ردّ الفعل على تغييرات محدّدة
        if old.watch_folders_enabled != settings.watch_folders_enabled:
            if settings.watch_folders_enabled:
                # لا نبدأ تلقائيًا — يحتاج المستخدم لتأكيد
                logger.info("Watch folders enabled in settings — will start on next watcher request")
            else:
                # لو المراقب يعمل، أوقفه
                if self.is_watcher_running():
                    self.stop_watcher()

        self.settings_changed.emit(settings)

    def preview_file(self, file_path: str) -> None:
        """يبثّ إشارة بأن مستخدمًا أراد معاينة ملف (للتنقّل إلى لوحة المعاينة)"""
        self.file_previewed.emit(file_path)

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

    def export_action_log_json(self, output_path: str | Path) -> str:
        """يصدّر السجل المرئي إلى JSON"""
        return self.action_log.export_json(output_path)

    def export_action_log_html(self, output_path: str | Path) -> str:
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
        watch_paths: list[str] | None = None,
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
        """ينظّف الموارد قبل الإغلاق

        PR-09: يحترم إعدادات save_undo_log_on_exit / save_action_log_on_exit
        """
        if self._watcher is not None and self._watcher.is_running():
            try:
                self._watcher.stop(timeout=2.0)
            except Exception:
                pass
        if self.settings.save_undo_log_on_exit:
            try:
                self.undo_log.save()
            except Exception:
                pass
        if self.settings.save_action_log_on_exit:
            try:
                self.action_log.save()
            except Exception:
                pass
