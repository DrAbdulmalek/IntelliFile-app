"""ActionLog — سجل إجراءات مرئي مع تصدير JSON/HTML وتكامل مع UndoLog

هذه الوحدة تنفّذ:
  - سجل مرئي لكل إجراءات IFM (move, copy, tag, untag, set_category, delete_flag)
  - تكامل مع UndoLog: كل entry في UndoLog يُضاف تلقائيًا إلى ActionLog
  - تصدير JSON و HTML قابل للعرض في المتصفح
  - تصفية وبحث في السجل (by action_type, by rule, by success)
  - إحصائيات ملخصة (عدد النجاح/الفشل، الإجراءات حسب النوع)
  - thread-safe عبر قفل داخلي
  - تخزين JSON قابل للقراءة عبر الجلسات

التصميم:
  - كل ActionLogEntry يحتوي على: timestamp, action_type, rule_name, file_path,
    file_path_after, success, error_message, tags_added, tags_removed,
    old_category, new_category, checksum_before, checksum_after, source
  - source: "rule_engine" | "watcher" | "manual" | "undo_rollback"
  - لا AI، لا medical — فقط تسجيل وعرض

PR-07 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import html
import json
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ─── ثوابت ─────────────────────────────────────────────────────────────────

# مصادر الإجراءات
SOURCE_RULE_ENGINE = "rule_engine"
SOURCE_WATCHER = "watcher"
SOURCE_MANUAL = "manual"
SOURCE_UNDO_ROLLBACK = "undo_rollback"

# صيغة التاريخ للعرض
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ─── Dataclass ──────────────────────────────────────────────────────────────

@dataclass
class ActionLogEntry:
    """سجل إجراء واحد في سجل الإجراءات المرئي

    يحتوي على معلومات كاملة لعرض الإجراء في الواجهة أو تصديره.
    """
    timestamp: str = ""
    action_type: str = ""
    rule_name: str = ""
    file_path: str = ""
    file_path_after: Optional[str] = None
    success: bool = True
    error_message: str = ""
    tags_added: List[str] = field(default_factory=list)
    tags_removed: List[str] = field(default_factory=list)
    old_category: str = ""
    new_category: str = ""
    # للتحقّق من سلامة النقل/النسخ (من SafeMover)
    checksum_before: str = ""
    checksum_after: str = ""
    # مصدر الإجراء
    source: str = SOURCE_RULE_ENGINE
    # مدة العملية بالميلي ثانية
    duration_ms: float = 0.0
    # معرّف فريد للسجل (للاستخدام في الروابط/الترتيب)
    entry_id: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionLogEntry":
        # تجاهل المفاتيح غير المعروفة (للتوافق مع الإصدارات السابقة)
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def file_name(self) -> str:
        """اسم الملف فقط (للعرض)"""
        try:
            return Path(self.file_path).name if self.file_path else ""
        except Exception:
            return self.file_path or ""

    def status_icon(self) -> str:
        """أيقونة الحالة (للعرض في HTML)"""
        return "✓" if self.success else "✗"

    def is_destructive(self) -> bool:
        """هل هذا إجراء يحتمل أن يكون تدميريًا؟"""
        return self.action_type in ("delete_flag", "move")


# ─── ActionLog ──────────────────────────────────────────────────────────────

class ActionLog:
    """سجل إجراءات مرئي مع تصدير JSON/HTML

    الاستخدام الأساسي:

        log = ActionLog("/data/.ifm_action_log.json")
        # من RuleEngine:
        log.log_from_undo_entry(entry, source="rule_engine")
        log.save()
        # تصدير:
        log.export_json("/tmp/actions.json")
        log.export_html("/tmp/actions.html")

    الخصائص:
      - thread-safe عبر RLock
      - قابل للحفظ/التحميل من JSON
      - حد أقصى للإدخالات (افتراضيًا 10000) — FIFO عند التجاوز
      - إضافة IDs متسلسلة لكل إدخال
    """

    def __init__(
        self,
        path: Optional[Union[str, Path]] = None,
        *,
        max_entries: int = 10000,
    ):
        """
        Args:
            path: مسار ملف JSON للسجل (None = ذاكرة فقط)
            max_entries: أقصى عدد إدخالات (FIFO)
        """
        self.path = Path(path) if path else None
        self.max_entries = max_entries
        self._entries: List[ActionLogEntry] = []
        self._lock = threading.RLock()
        self._next_id = 1

        if self.path and self.path.exists():
            self.load()

    # ─── الواجهة الأساسية ───────────────────────────────────────────────

    def log(
        self,
        *,
        action_type: str,
        file_path: str,
        rule_name: str = "",
        file_path_after: Optional[str] = None,
        success: bool = True,
        error_message: str = "",
        tags_added: Optional[List[str]] = None,
        tags_removed: Optional[List[str]] = None,
        old_category: str = "",
        new_category: str = "",
        checksum_before: str = "",
        checksum_after: str = "",
        source: str = SOURCE_RULE_ENGINE,
        duration_ms: float = 0.0,
        timestamp: Optional[str] = None,
    ) -> ActionLogEntry:
        """يضيف سجل إجراء جديدًا

        Returns:
            ActionLogEntry المُضاف (مع entry_id معيَّن)
        """
        with self._lock:
            entry = ActionLogEntry(
                timestamp=timestamp or datetime.now().isoformat(timespec="seconds"),
                action_type=action_type,
                rule_name=rule_name,
                file_path=file_path,
                file_path_after=file_path_after,
                success=success,
                error_message=error_message,
                tags_added=list(tags_added or []),
                tags_removed=list(tags_removed or []),
                old_category=old_category,
                new_category=new_category,
                checksum_before=checksum_before,
                checksum_after=checksum_after,
                source=source,
                duration_ms=duration_ms,
                entry_id=self._next_id,
            )
            self._next_id += 1
            self._entries.append(entry)
            # FIFO عند التجاوز
            if len(self._entries) > self.max_entries:
                # نحذف أقدم 10% (وليس واحدًا فقط) لتقليل عمليات القص
                trim_count = max(1, self.max_entries // 10)
                self._entries = self._entries[trim_count:]
            return entry

    def log_from_undo_entry(
        self,
        undo_entry,
        *,
        source: str = SOURCE_RULE_ENGINE,
        checksum_before: str = "",
        checksum_after: str = "",
        duration_ms: float = 0.0,
    ) -> ActionLogEntry:
        """يضيف سجلًا من UndoEntry (من rule_schemas)

        Args:
            undo_entry: UndoEntry من rule_schemas
            source: مصدر الإجراء
            checksum_before/after: للتحقّق (من SafeMover)
            duration_ms: مدة العملية
        """
        return self.log(
            action_type=undo_entry.action_type,
            file_path=undo_entry.file_path,
            rule_name=undo_entry.rule_name,
            file_path_after=undo_entry.file_path_after,
            success=undo_entry.success,
            error_message=undo_entry.error_message,
            tags_added=undo_entry.tags_added,
            tags_removed=undo_entry.tags_removed,
            old_category=undo_entry.old_category,
            new_category=undo_entry.new_category,
            timestamp=undo_entry.timestamp,
            source=source,
            checksum_before=checksum_before,
            checksum_after=checksum_after,
            duration_ms=duration_ms,
        )

    def log_from_move_result(
        self,
        move_result,
        *,
        rule_name: str = "",
        source: str = SOURCE_RULE_ENGINE,
    ) -> ActionLogEntry:
        """يضيف سجلًا من MoveResult (من safe_mover)"""
        return self.log(
            action_type="move",
            file_path=move_result.source,
            file_path_after=move_result.final_path,
            success=move_result.success,
            error_message=move_result.error or "",
            checksum_before=move_result.checksum_before,
            checksum_after=move_result.checksum_after,
            duration_ms=move_result.duration_ms,
            rule_name=rule_name,
            source=source,
        )

    def log_from_copy_result(
        self,
        copy_result,
        *,
        rule_name: str = "",
        source: str = SOURCE_RULE_ENGINE,
    ) -> ActionLogEntry:
        """يضيف سجلًا من CopyResult (من safe_mover)"""
        return self.log(
            action_type="copy",
            file_path=copy_result.source,
            file_path_after=copy_result.final_path,
            success=copy_result.success,
            error_message=copy_result.error or "",
            checksum_before=copy_result.checksum_before,
            checksum_after=copy_result.checksum_after,
            duration_ms=copy_result.duration_ms,
            rule_name=rule_name,
            source=source,
        )

    def log_rollback(
        self,
        undo_entry,
        *,
        success: bool = True,
        error_message: str = "",
    ) -> ActionLogEntry:
        """يسجّل عملية تراجع عن إجراء (للتتبّع الكامل)"""
        return self.log(
            action_type=f"undo:{undo_entry.action_type}",
            file_path=undo_entry.file_path_after or undo_entry.file_path,
            rule_name=undo_entry.rule_name,
            success=success,
            error_message=error_message,
            source=SOURCE_UNDO_ROLLBACK,
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )

    # ─── الاستعلام ───────────────────────────────────────────────────────

    def list_entries(
        self,
        *,
        action_type: Optional[str] = None,
        rule_name: Optional[str] = None,
        success: Optional[bool] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
        reverse: bool = True,
    ) -> List[ActionLogEntry]:
        """يستعلم عن السجلات مع تصفية اختيارية

        Args:
            action_type: تصفية حسب نوع الإجراء
            rule_name: تصفية حسب اسم القاعدة
            success: تصفية حسب النجاح/الفشل
            source: تصفية حسب المصدر
            limit: أقصى عدد نتائج
            reverse: لو True، الأحدث أولًا (افتراضيًا)
        """
        with self._lock:
            results = list(self._entries)

        if action_type is not None:
            results = [e for e in results if e.action_type == action_type]
        if rule_name is not None:
            results = [e for e in results if e.rule_name == rule_name]
        if success is not None:
            results = [e for e in results if e.success == success]
        if source is not None:
            results = [e for e in results if e.source == source]

        if reverse:
            results = list(reversed(results))

        if limit is not None:
            results = results[:limit]

        return results

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def __iter__(self):
        with self._lock:
            return iter(list(self._entries))

    def clear(self) -> None:
        """يفرّغ السجل"""
        with self._lock:
            self._entries = []
            self._next_id = 1

    def get_entry(self, entry_id: int) -> Optional[ActionLogEntry]:
        """يبحث عن entry بمعرّفه"""
        with self._lock:
            for e in self._entries:
                if e.entry_id == entry_id:
                    return e
        return None

    # ─── إحصائيات ────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """يُرجع إحصائيات ملخصة عن السجل"""
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return {
                "total": 0,
                "success_count": 0,
                "failure_count": 0,
                "success_rate": 0.0,
                "by_action_type": {},
                "by_source": {},
                "by_rule": {},
                "first_timestamp": None,
                "last_timestamp": None,
            }

        success_count = sum(1 for e in entries if e.success)
        by_action = Counter(e.action_type for e in entries)
        by_source = Counter(e.source for e in entries)
        by_rule = Counter(e.rule_name for e in entries if e.rule_name)
        timestamps = [e.timestamp for e in entries if e.timestamp]

        return {
            "total": len(entries),
            "success_count": success_count,
            "failure_count": len(entries) - success_count,
            "success_rate": round(success_count / len(entries) * 100, 2),
            "by_action_type": dict(by_action),
            "by_source": dict(by_source),
            "by_rule": dict(by_rule),
            "first_timestamp": min(timestamps) if timestamps else None,
            "last_timestamp": max(timestamps) if timestamps else None,
        }

    # ─── حفظ/تحميل ───────────────────────────────────────────────────────

    def save(self) -> None:
        """يحفظ السجل في ملف JSON"""
        if not self.path:
            return
        with self._lock:
            data = {
                "version": 1,
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "next_id": self._next_id,
                "entries": [e.to_dict() for e in self._entries],
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"فشل حفظ سجل الإجراءات {self.path}: {e}")

    def load(self) -> None:
        """يحمّل السجل من ملف JSON"""
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            with self._lock:
                self._entries = [
                    ActionLogEntry.from_dict(e) for e in data.get("entries", [])
                ]
                self._next_id = data.get("next_id", len(self._entries) + 1)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"فشل تحميل سجل الإجراءات {self.path}: {e}")
            with self._lock:
                self._entries = []
                self._next_id = 1

    # ─── تصدير ───────────────────────────────────────────────────────────

    def export_json(self, output_path: Union[str, Path]) -> str:
        """يصدّر السجل كاملاً إلى ملف JSON

        Returns:
            المسار النهائي للملف
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            entries_data = [e.to_dict() for e in self._entries]
        data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "stats": self.stats(),
            "entries": entries_data,
        }
        out.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return str(out)

    def export_html(
        self,
        output_path: Union[str, Path],
        *,
        title: str = "IntelliFile Manager — سجل الإجراءات",
        limit: Optional[int] = None,
        only_failures: bool = False,
    ) -> str:
        """يصدّر السجل إلى ملف HTML قابل للعرض في المتصفح

        Args:
            output_path: مسار ملف HTML
            title: عنوان الصفحة
            limit: أقصى عدد إدخالات للعرض (None = الكل)
            only_failures: لو True، يعرض الإجراءات الفاشلة فقط

        Returns:
            المسار النهائي للملف
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # جمع البيانات
        entries = self.list_entries(reverse=True, limit=limit)
        if only_failures:
            entries = [e for e in entries if not e.success]
        stats = self.stats()

        # بناء HTML
        html_content = _build_action_log_html(
            title=title,
            entries=entries,
            stats=stats,
            only_failures=only_failures,
        )
        out.write_text(html_content, encoding="utf-8")
        return str(out)

    def export_csv(self, output_path: Union[str, Path]) -> str:
        """يصدّر السجل إلى CSV (للاستيراد في Excel/Google Sheets)"""
        import csv
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "entry_id", "timestamp", "action_type", "rule_name",
                "file_path", "file_path_after", "success", "error_message",
                "tags_added", "tags_removed", "old_category", "new_category",
                "checksum_before", "checksum_after", "source", "duration_ms",
            ])
            for e in self.list_entries(reverse=True):
                writer.writerow([
                    e.entry_id, e.timestamp, e.action_type, e.rule_name,
                    e.file_path, e.file_path_after or "",
                    "yes" if e.success else "no",
                    e.error_message,
                    ";".join(e.tags_added), ";".join(e.tags_removed),
                    e.old_category, e.new_category,
                    e.checksum_before, e.checksum_after,
                    e.source, e.duration_ms,
                ])
        return str(out)


# ─── HTML Builder ───────────────────────────────────────────────────────────

_CSS = """
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --text: #1f2328;
  --muted: #656d76;
  --border: #d0d7de;
  --accent: #0969da;
  --warn: #d1242f;
  --ok: #1a7f37;
  --warn-bg: #ffebe9;
  --ok-bg: #dafbe1;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, "Segoe UI", "Noto Sans", "Noto Sans SC", sans-serif;
  background: var(--bg);
  color: var(--text);
  margin: 0;
  padding: 24px;
  line-height: 1.6;
  direction: rtl;
}
.container { max-width: 1280px; margin: 0 auto; }
h1, h2, h3 { color: var(--text); margin-top: 0; }
h1 { font-size: 24px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
h2 { font-size: 18px; margin-top: 28px; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 8px;
}
.stat {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 16px;
}
.stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat .value { font-size: 24px; font-weight: 600; color: var(--text); }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: var(--card);
  border-radius: 6px;
  overflow: hidden;
}
thead { background: #f6f8fa; }
th, td {
  padding: 8px 10px;
  text-align: right;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
th { font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f6f8fa; }
.status-ok { color: var(--ok); font-weight: 700; }
.status-fail { color: var(--warn); font-weight: 700; }
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  background: #ddf4ff;
  color: #0969da;
  margin: 0 4px 4px 0;
}
.tag-destr { background: var(--warn-bg); color: var(--warn); }
.tag-source { background: #fff8c5; color: #7d4e00; }
.tag-rule { background: #dafbe1; color: var(--ok); }
.mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: 12px; }
.muted { color: var(--muted); }
.checksum { color: var(--muted); font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }
.error-msg { color: var(--warn); font-size: 12px; }
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  align-items: center;
}
.filter-bar a {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 6px;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  text-decoration: none;
  font-size: 13px;
}
.filter-bar a:hover { background: #f6f8fa; }
.timestamp { color: var(--muted); font-size: 12px; }
.empty { padding: 32px; text-align: center; color: var(--muted); }
"""


def _build_action_log_html(
    *,
    title: str,
    entries: List[ActionLogEntry],
    stats: Dict[str, Any],
    only_failures: bool,
) -> str:
    """يبني محتوى HTML الكامل لسجل الإجراءات"""
    rows_html: List[str] = []
    if not entries:
        rows_html.append(
            '<tr><td colspan="8" class="empty">لا توجد إجراءات في السجل.</td></tr>'
        )
    else:
        for e in entries:
            rows_html.append(_render_entry_row(e))

    # أزرار التصفية (روابط فقط — لا JS)
    filter_bar = f"""
    <div class="filter-bar">
      <a href="#">الكُل ({stats["total"]})</a>
      <a href="#">الناجحة ({stats["success_count"]})</a>
      <a href="#">الفاشلة ({stats["failure_count"]})</a>
    </div>
    """

    by_action_html = " · ".join(
        f"{html.escape(k)}: {v}" for k, v in
        sorted(stats.get("by_action_type", {}).items())
    ) or "—"
    by_source_html = " · ".join(
        f"{html.escape(k)}: {v}" for k, v in
        sorted(stats.get("by_source", {}).items())
    ) or "—"
    by_rule_html = " · ".join(
        f"{html.escape(k)}: {v}" for k, v in
        sorted(stats.get("by_rule", {}).items())[:5]
    ) or "—"

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="container">
    <h1>{html.escape(title)}</h1>
    <p class="muted">أُنشئ في {html.escape(datetime.now().strftime(_DATE_FORMAT))}</p>

    <h2>ملخص الإحصائيات</h2>
    <div class="summary-grid">
      <div class="stat"><div class="label">إجمالي الإجراءات</div><div class="value">{stats["total"]}</div></div>
      <div class="stat"><div class="label">الناجحة</div><div class="value status-ok">{stats["success_count"]}</div></div>
      <div class="stat"><div class="label">الفاشلة</div><div class="value status-fail">{stats["failure_count"]}</div></div>
      <div class="stat"><div class="label">نسبة النجاح</div><div class="value">{stats["success_rate"]}%</div></div>
      <div class="stat"><div class="label">أول إجراء</div><div class="value" style="font-size:14px">{html.escape(stats.get("first_timestamp") or "—")}</div></div>
      <div class="stat"><div class="label">آخر إجراء</div><div class="value" style="font-size:14px">{html.escape(stats.get("last_timestamp") or "—")}</div></div>
    </div>

    <div class="card">
      <strong>حسب نوع الإجراء:</strong> {by_action_html}<br>
      <strong>حسب المصدر:</strong> {by_source_html}<br>
      <strong>أعلى القواعد:</strong> {by_rule_html}
    </div>

    <h2>{"الإجراءات الفاشلة" if only_failures else "جميع الإجراءات"} ({len(entries)})</h2>
    {filter_bar}

    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>الحالة</th>
          <th>الوقت</th>
          <th>النوع</th>
          <th>الملف</th>
          <th>القاعدة</th>
          <th>الوسوم</th>
          <th>ملاحظات</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


def _render_entry_row(e: ActionLogEntry) -> str:
    """يبني صفاً واحدًا في جدول HTML للسجل"""
    status_cls = "status-ok" if e.success else "status-fail"
    status_text = "✓ نجاح" if e.success else "✗ فشل"

    # الوسوم
    tags_html = ""
    for t in e.tags_added:
        tags_html += f'<span class="tag">+{html.escape(t)}</span>'
    for t in e.tags_removed:
        tags_html += f'<span class="tag tag-destr">−{html.escape(t)}</span>'
    if e.new_category:
        tags_html += f'<span class="tag tag-rule">{html.escape(e.new_category)}</span>'
    if e.is_destructive():
        tags_html += '<span class="tag tag-destr">تدميري</span>'
    if e.source:
        tags_html += f'<span class="tag tag-source">{html.escape(e.source)}</span>'

    # ملاحظات (error / checksum / duration)
    notes_parts = []
    if e.error_message:
        notes_parts.append(f'<div class="error-msg">⚠ {html.escape(e.error_message)}</div>')
    if e.checksum_before and e.checksum_after:
        if e.checksum_before == e.checksum_after:
            notes_parts.append(
                f'<div class="checksum">SHA-256 متطابق: {html.escape(e.checksum_before[:12])}…</div>'
            )
        else:
            notes_parts.append(
                f'<div class="checksum">⚠ SHA-256 غير متطابق!</div>'
            )
    if e.duration_ms > 0:
        notes_parts.append(
            f'<div class="muted" style="font-size:11px">المدة: {e.duration_ms:.1f} ms</div>'
        )

    # عرض الملف (المسار مختصر لتقليل العرض)
    file_display = html.escape(e.file_name())
    if e.file_path_after and e.action_type in ("move", "copy"):
        after_name = Path(e.file_path_after).name
        file_display += f' → <span class="mono">{html.escape(after_name)}</span>'

    return f"""<tr>
      <td class="muted">{e.entry_id}</td>
      <td class="{status_cls}">{status_text}</td>
      <td class="timestamp">{html.escape(e.timestamp)}</td>
      <td><strong>{html.escape(e.action_type)}</strong></td>
      <td class="mono">{file_display}</td>
      <td>{html.escape(e.rule_name) or "—"}</td>
      <td>{tags_html or "—"}</td>
      <td>{"".join(notes_parts) or "—"}</td>
    </tr>"""


# ─── Convenience ────────────────────────────────────────────────────────────

def format_action_log_summary(log: ActionLog, *, limit: int = 20) -> str:
    """يُرجع ملخصًا نصيًا للسجل (للعرض في CLI)

    Args:
        log: سجل الإجراءات
        limit: أقصى عدد إدخالات للعرض
    """
    stats = log.stats()
    if stats["total"] == 0:
        return "سجل الإجراءات فارغ."

    lines = [
        f"سجل الإجراءات ({stats['total']} إجمالي، "
        f"{stats['success_count']} ناجح، {stats['failure_count']} فاشل):",
        "",
    ]

    entries = log.list_entries(reverse=True, limit=limit)
    for e in entries:
        status = "✓" if e.success else "✗"
        rule_info = f"  [{e.rule_name}]" if e.rule_name else ""
        lines.append(
            f"  {e.entry_id:>4}. [{status}] {e.action_type:14s} "
            f"{e.file_name()}{rule_info}"
        )

    if len(log) > limit:
        lines.append(f"  ... و{len(log) - limit} إجراء آخر.")
    return "\n".join(lines)
