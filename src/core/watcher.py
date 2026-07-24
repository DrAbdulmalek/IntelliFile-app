"""FileWatcher — مراقبة المجلدات مع debounce + دفعات آمنة + dry-run تلقائي

يستخدم watchdog لمراقبة المجلدات، ويدمج الأحداث المتتالية (debounce) ثم
يعالجها على دفعات بأمان:
  - كل دفعة تُمرَّر عبر FileInventory + RuleEngine.dry_run()
  - يُكتب تقرير HTML + خطة JSON لكل دفعة (لا تنفيذ فعلي افتراضيًا)
  - لا توجد إجراءات تدميرية بدون تأكيد صريح خارجي
  - سجل تاريخ كامل للدفعات المُعالَجة

التصميم:
  - موضوع آمن (thread-safe): Observer يعمل في thread منفصل، المعالجة في thread آخر
  - debounce: أحداث متعددة على نفس الملف خلال debounce_seconds تُدمج في حدث واحد
  - batch: تجميع الأحداث المجمَّعة حتى batch_max_size أو batch_interval
  - auto_dry_run: افتراضيًا True — لا تنفيذ فعلي، فقط تقارير
  - graceful: استثناء في معالجة دفعة لا يُسقط المراقب

PR-06 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ─── ثوابت افتراضية ──────────────────────────────────────────────────────────
DEFAULT_DEBOUNCE_SECONDS = 2.0
DEFAULT_BATCH_INTERVAL = 5.0
DEFAULT_BATCH_MAX_SIZE = 100
DEFAULT_OUTPUT_DIR = ".ifm_watcher"


# ─── Enums ─────────────────────────────────────────────────────────────────

class WatchEventType(str, Enum):
    """أنواع أحداث المراقبة"""
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


# ─── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class WatchEvent:
    """حدث مراقبة واحد (بعد debounce)"""
    event_type: str
    file_path: str
    file_name: str = ""
    is_directory: bool = False
    # للأحداث من نوع moved
    src_path: Optional[str] = None
    dest_path: Optional[str] = None
    timestamp: str = ""
    # متى وصل آخر مرة (للـ debounce)
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WatchEvent":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class WatcherConfig:
    """إعدادات المراقب"""
    watch_paths: List[str] = field(default_factory=list)
    recursive: bool = True
    # debounce: دمج الأحداث المتتالية على نفس الملف
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS
    # batch: دمج أحداث متعددة في دفعة واحدة
    batch_interval: float = DEFAULT_BATCH_INTERVAL
    batch_max_size: int = DEFAULT_BATCH_MAX_SIZE
    # auto dry-run: افتراضيًا نولّد تقارير فقط (لا تنفيذ)
    auto_dry_run: bool = True
    # المجلد الذي تُكتب فيه التقارير والخطط
    output_dir: str = DEFAULT_OUTPUT_DIR
    # أنماط التجاهل (regex)
    ignore_patterns: List[str] = field(default_factory=list)
    # قواعد اختيارية لاستخدامها في dry_run. لو None، يُسجَّل السجل فقط دون خطة.
    ruleset: Optional[object] = None  # Ruleset — استيراد كسول لتجنّب الاستيراد الدائري
    base_dir: str = ""
    # تضمين استخراج المحتوى في FileInventory (ابطال افتراضيًا للسرعة)
    include_content: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        # ruleset قد لا يكون serializable مباشرة
        if self.ruleset is not None:
            try:
                d["ruleset"] = self.ruleset.to_dict()
            except Exception:
                d["ruleset"] = None
        return d


@dataclass
class BatchResult:
    """نتيجة معالجة دفعة واحدة"""
    batch_id: str
    started_at: str
    finished_at: str = ""
    events_count: int = 0
    files_scanned: int = 0
    planned_actions: int = 0
    skipped_files: int = 0
    report_path: Optional[str] = None
    plan_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ─── FileWatcher ────────────────────────────────────────────────────────────

class FileWatcher:
    """مراقب المجلدات مع debounce + دفعات آمنة + dry-run تلقائي

    الاستخدام الأساسي:

        from .rule_schemas import Ruleset
        from .rule_engine import RuleEngine

        config = WatcherConfig(
            watch_paths=["/data/downloads"],
            ruleset=Ruleset.from_yaml("rules/default_rules.yaml"),
            base_dir="/data",
            output_dir="/data/.ifm_watcher",
        )
        watcher = FileWatcher(config)
        watcher.start()
        # ... تعمل في الخلفية ...
        watcher.stop()

    ملاحظات:
      - watchdog.Observer يعمل في thread منفصل
      - المعالجة (batch flush) في thread آخر
      - thread-safe عبر قفل داخلي
      - كل دفعة تُنتج: report_<batch_id>.html + plan_<batch_id>.json
      - السجل الكامل متاح عبر get_history()
    """

    def __init__(self, config: WatcherConfig):
        self.config = config
        # حالة المراقب
        self._observer = None
        self._debounce_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        # قائمة الأحداث المعلَّقة (بعد debounce الأولي)
        self._pending: Dict[str, WatchEvent] = {}
        # التاريخ الكامل للدفعات المعالَجة
        self._history: List[BatchResult] = []
        # تجميع أنماط التجاهل
        self._ignore_regexes = [re.compile(p) for p in config.ignore_patterns]

        # التحقق من إعدادات المراقب
        if not config.watch_paths:
            logger.warning("FileWatcher: لا توجد مسارات للمراقبة")

    # ─── دورة الحياة ─────────────────────────────────────────────────────

    def start(self) -> None:
        """يبدأ المراقبة في thread منفصل"""
        if self._observer is not None:
            logger.warning("FileWatcher: المراقب يعمل بالفعل")
            return

        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise ImportError(
                "watchdog غير مثبت. ثبّته عبر: pip install watchdog"
            )

        # إنشاء مجلد الإخراج
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # إعداد Observer
        self._observer = Observer()
        handler = _WatchdogHandler(self)
        for path in self.config.watch_paths:
            p = Path(path)
            if not p.is_dir():
                logger.warning(f"FileWatcher: مسار المراقبة غير موجود: {path}")
                continue
            self._observer.schedule(
                handler,
                str(p),
                recursive=self.config.recursive,
            )

        # بدء الـ debounce/batch thread
        self._stop_event.clear()
        self._debounce_thread = threading.Thread(
            target=self._debounce_loop,
            name="ifm-watcher-debounce",
            daemon=True,
        )

        # بدء Observer
        self._observer.start()
        self._debounce_thread.start()
        logger.info(
            f"FileWatcher بدأ: {len(self.config.watch_paths)} مسار، "
            f"debounce={self.config.debounce_seconds}s, "
            f"batch_interval={self.config.batch_interval}s"
        )

    def stop(self, *, timeout: float = 5.0) -> None:
        """يوقف المراقبة بأمان"""
        if self._observer is None:
            return

        # إيقاف حلقة debounce
        self._stop_event.set()
        if self._debounce_thread and self._debounce_thread.is_alive():
            self._debounce_thread.join(timeout=timeout)

        # إيقاف watchdog Observer
        self._observer.stop()
        self._observer.join(timeout=timeout)
        self._observer = None
        self._debounce_thread = None
        logger.info("FileWatcher توقف")

    def is_running(self) -> bool:
        """هل المراقب يعمل؟"""
        return self._observer is not None and self._observer.is_alive()

    # ─── استقبال أحداث watchdog ───────────────────────────────────────────

    def _on_watchdog_event(self, event) -> None:
        """يُستدعى من _WatchdogHandler عند وصول حدث watchdog"""
        # تجاهل الأحداث على المجلدات (نُراقب الملفات فقط)
        if event.is_directory:
            return

        file_path = event.src_path
        # تطبيق أنماط التجاهل
        if self._is_ignored(file_path):
            return

        event_type = _watchdog_event_type(event)
        if event_type is None:
            return

        # إنشاء WatchEvent
        watch_event = WatchEvent(
            event_type=event_type,
            file_path=file_path,
            file_name=Path(file_path).name,
            is_directory=event.is_directory,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            last_seen=time.monotonic(),
        )
        # للأحداث من نوع moved
        if event_type == WatchEventType.MOVED.value:
            watch_event.src_path = getattr(event, "src_path", None)
            watch_event.dest_path = getattr(event, "dest_path", None)

        # إضافة لقائمة المعلَّقة (debounce: استبدال لو نفس file_path+event_type)
        key = f"{event_type}:{file_path}"
        with self._lock:
            self._pending[key] = watch_event

    def _is_ignored(self, file_path: str) -> bool:
        """هل يجب تجاهل هذا المسار؟"""
        for regex in self._ignore_regexes:
            if regex.search(file_path):
                return True
        # تجاهل ملفات sidecar الخاصة بـ IFM
        name = Path(file_path).name
        if name.startswith(".ifm_meta_") or name.startswith(".ifm_undo"):
            return True
        # تجاهل الملفات داخل مجلد الإخراج نفسه
        try:
            out_dir = str(Path(self.config.output_dir).resolve())
            if str(Path(file_path).resolve()).startswith(out_dir):
                return True
        except OSError:
            pass
        return False

    # ─── حلقة debounce + batch ──────────────────────────────────────────────

    def _debounce_loop(self) -> None:
        """حلقة خلفية تستهلك الأحداث المعلَّقة وتُجمّعها في دفعات"""
        last_flush = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            with self._lock:
                pending_count = len(self._pending)
                # هل حان وقت flush؟
                time_since_last = now - last_flush
                should_flush = (
                    pending_count >= self.config.batch_max_size
                    or (pending_count > 0 and time_since_last >= self.config.batch_interval)
                )
                if should_flush:
                    events = list(self._pending.values())
                    self._pending.clear()
                else:
                    events = []
            if events:
                try:
                    self._process_batch(events)
                except Exception as e:
                    logger.error(f"FileWatcher: خطأ في معالجة الدفعة: {e}", exc_info=True)
                last_flush = time.monotonic()
            # انتظار قصير قبل التحقق مرة أخرى
            self._stop_event.wait(0.5)

    def _process_batch(self, events: List[WatchEvent]) -> BatchResult:
        """يعالج دفعة أحداث: مسح + dry-run + كتابة تقرير"""
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        result = BatchResult(
            batch_id=batch_id,
            started_at=datetime.now().isoformat(timespec="seconds"),
            events_count=len(events),
        )

        try:
            # استخراج المجلدات المتأثرة
            affected_dirs: set[str] = set()
            for ev in events:
                if ev.event_type == WatchEventType.DELETED.value:
                    # الملف محذوف — نأخذ مجلده الأب
                    parent = str(Path(ev.file_path).parent)
                elif ev.event_type == WatchEventType.MOVED.value and ev.dest_path:
                    parent = str(Path(ev.dest_path).parent)
                else:
                    parent = str(Path(ev.file_path).parent)
                affected_dirs.add(parent)

            # مسح المجلدات المتأثرة عبر FileInventory
            from .file_inventory import FileInventory
            inventory = FileInventory(include_content=self.config.include_content)
            records = []
            for d in affected_dirs:
                if Path(d).is_dir():
                    records.extend(inventory.scan_directory(d))
            result.files_scanned = len(records)

            # dry-run لو توفّر ruleset
            if self.config.ruleset is not None and records:
                from .rule_engine import RuleEngine
                engine = RuleEngine(self.config.ruleset)
                plan = engine.dry_run(records, base_dir=self.config.base_dir)
                result.planned_actions = plan.total_actions
                result.skipped_files = len(plan.skipped_files)

                # كتابة الخطة JSON
                plan_path = Path(self.config.output_dir) / f"plan_{batch_id}.json"
                plan_path.write_text(
                    json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                result.plan_path = str(plan_path)

                # كتابة تقرير HTML لو auto_dry_run
                if self.config.auto_dry_run:
                    from .dry_run_reporter import generate_html_report
                    report_path = Path(self.config.output_dir) / f"report_{batch_id}.html"
                    generate_html_report(plan, output_path=report_path)
                    result.report_path = str(report_path)

            # كتابة سجل الدفعة (events)
            events_path = Path(self.config.output_dir) / f"events_{batch_id}.json"
            events_path.write_text(
                json.dumps(
                    [e.to_dict() for e in events],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        except Exception as e:
            logger.error(f"FileWatcher: فشل معالجة الدفعة {batch_id}: {e}", exc_info=True)
            result.error = str(e)[:500]

        result.finished_at = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            self._history.append(result)
        return result

    # ─── واجهة الاستعلام ──────────────────────────────────────────────────

    def get_pending_events(self) -> List[WatchEvent]:
        """يُرجع نسخة من الأحداث المعلَّقة (لم تُعالَج بعد)"""
        with self._lock:
            return list(self._pending.values())

    def get_history(self) -> List[BatchResult]:
        """يُرجع نسخة من تاريخ الدفعات المعالَجة"""
        with self._lock:
            return list(self._history)

    def clear_history(self) -> None:
        """يفرّغ التاريخ"""
        with self._lock:
            self._history = []

    def flush_now(self) -> Optional[BatchResult]:
        """يجبر flush الأحداث المعلَّقة فورًا (للاختبارات)

        Returns:
            BatchResult لو وُجدت أحداث معلَّقة، None لو لا
        """
        with self._lock:
            if not self._pending:
                return None
            events = list(self._pending.values())
            self._pending.clear()
        return self._process_batch(events)


# ─── Watchdog Handler (داخلي) ────────────────────────────────────────────────

class _WatchdogHandler:
    """مُعالج أحداث watchdog يحوّلها إلى WatchEvent"""

    # watchdog.events.FileSystemEventHandler
    def __init__(self, watcher: FileWatcher):
        self._watcher = watcher
        # وراثة من FileSystemEventHandler
        try:
            from watchdog.events import FileSystemEventHandler
            # تحويل الكلاس لوراثة ديناميكية (لتجنّب تكرار تعريف methods)
            self.__class__ = type(
                "_WatchdogHandlerImpl",
                (_WatchdogHandler, FileSystemEventHandler),
                {},
            )
        except ImportError:
            pass

    def on_created(self, event):
        self._watcher._on_watchdog_event(event)

    def on_modified(self, event):
        self._watcher._on_watchdog_event(event)

    def on_deleted(self, event):
        self._watcher._on_watchdog_event(event)

    def on_moved(self, event):
        self._watcher._on_watchdog_event(event)

    def on_any_event(self, event):
        # نُعالج فقط أنواعًا محددة، لا نريد تكرار
        pass


def _watchdog_event_type(event) -> Optional[WatchEventType]:
    """يحدد نوع الحدث من watchdog event object"""
    # watchdog event types: FileCreatedEvent, FileModifiedEvent, etc.
    event_class_name = type(event).__name__
    if "Created" in event_class_name:
        return WatchEventType.CREATED
    if "Modified" in event_class_name:
        return WatchEventType.MODIFIED
    if "Deleted" in event_class_name:
        return WatchEventType.DELETED
    if "Moved" in event_class_name:
        return WatchEventType.MOVED
    return None
