"""UndoLog — سجل التراجع عن الإجراءات

يخزّن UndoEntry لكل إجراء نُفّذ. يدعم:
  - append(entry): إضافة سجل جديد
  - rollback_last(): تراجع عن آخر إجراء (يرجع الملف/الوسوم لحالتها الأصلية)
  - rollback_all(): تراجع عن كل الإجراءات (بترتيب عكسي)
  - save() / load(): حفظ/تحميل JSON
  - list_entries(): عرض السجلات

ملاحظات:
  - rollback ينفّذ العملية العكسية فعليًا على القرص + يحذف الـ entry من السجل
  - rollback_last يُرجع UndoEntry الذي تراجع عنه (أو None لو السجل فارغ)
  - لا تراجع عن rollback (مقصود — rollback نهائي)

PR-05 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from .rule_schemas import UndoEntry, ActionType

logger = logging.getLogger(__name__)


class UndoLog:
    """سجل التراجع عن الإجراءات

    الاستخدام:
        log = UndoLog("/data/.ifm_undo.json")
        # (تنفيذ إجراءات — تُضاف تلقائيًا عبر RuleEngine)
        log.save()
        # لاحقًا:
        log.load()
        log.rollback_last()
    """

    def __init__(self, path: Optional[Union[str, Path]] = None):
        """
        Args:
            path: مسار ملف JSON لحفظ السجل. إن None، السجل في الذاكرة فقط.
        """
        self.path = Path(path) if path else None
        self.entries: List[UndoEntry] = []
        if self.path and self.path.exists():
            self.load()

    # ─── الواجهة الأساسية ───────────────────────────────────────────────

    def append(self, entry: UndoEntry) -> None:
        """يضيف سجل تراجع جديدًا (دون حفظ تلقائي على القرص)"""
        self.entries.append(entry)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def list_entries(self) -> List[UndoEntry]:
        """يُرجع نسخة من قائمة السجلات"""
        return list(self.entries)

    def clear(self) -> None:
        """يفرّغ السجل (دون حذف الملف)"""
        self.entries = []

    # ─── حفظ/تحميل ───────────────────────────────────────────────────────

    def save(self) -> None:
        """يحفظ السجل في ملف JSON"""
        if not self.path:
            return
        data = {
            "version": 1,
            "saved_at": datetime.now().isoformat(),
            "entries": [e.to_dict() for e in self.entries],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> None:
        """يحمّل السجل من ملف JSON"""
        if not self.path or not self.path.exists():
            self.entries = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = [UndoEntry.from_dict(e) for e in data.get("entries", [])]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"فشل تحميل سجل التراجع {self.path}: {e}")
            self.entries = []

    # ─── التراجع ─────────────────────────────────────────────────────────

    def rollback_last(self) -> Optional[UndoEntry]:
        """يرجع آخر إجراء منفّذ (FIFO reversal)

        Returns:
            UndoEntry الذي تم التراجع عنه، أو None لو السجل فارغ
        """
        if not self.entries:
            return None
        entry = self.entries.pop()
        try:
            self._rollback_entry(entry)
        except Exception as e:
            logger.error(f"فشل التراجع عن {entry.action_type} على {entry.file_path}: {e}")
            entry.success = False
            entry.error_message = str(e)[:200]
        # حفظ تلقائي لو path محدد
        if self.path:
            self.save()
        return entry

    def rollback_all(self) -> List[UndoEntry]:
        """يرجع كل الإجراءات بترتيب عكسي (LIFO)

        Returns:
            قائمة UndoEntry التي تم التراجع عنها (بنفس ترتيب التراجع)
        """
        rolled_back: List[UndoEntry] = []
        while self.entries:
            entry = self.rollback_last()
            if entry is not None:
                rolled_back.append(entry)
        return rolled_back

    def rollback_n(self, n: int) -> List[UndoEntry]:
        """يرجع آخر n إجراءات"""
        rolled_back: List[UndoEntry] = []
        for _ in range(min(n, len(self.entries))):
            entry = self.rollback_last()
            if entry is not None:
                rolled_back.append(entry)
        return rolled_back

    # ─── منطق التراجع لكل نوع ────────────────────────────────────────────

    def _rollback_entry(self, entry: UndoEntry) -> None:
        """ينفّذ العملية العكسية لإجراء واحد"""
        if not entry.success:
            logger.warning(
                f"محاولة التراجع عن إجراء فاشل أصلاً ({entry.action_type} على "
                f"{entry.file_path}) — قد لا يكون آمنًا"
            )

        action_type = entry.action_type

        if action_type == ActionType.MOVE.value:
            self._rollback_move(entry)
        elif action_type == ActionType.COPY.value:
            self._rollback_copy(entry)
        elif action_type == ActionType.TAG.value:
            self._rollback_tag(entry)
        elif action_type == ActionType.UNTAG.value:
            self._rollback_untag(entry)
        elif action_type == ActionType.SET_CATEGORY.value:
            self._rollback_set_category(entry)
        elif action_type == ActionType.DELETE_FLAG.value:
            self._rollback_delete_flag(entry)
        else:
            raise ValueError(f"لا يمكن التراجع عن نوع إجراء: {action_type}")

    def _rollback_move(self, entry: UndoEntry) -> None:
        """عكس النقل: نقل الملف من الوجهة إلى المصدر (مع sidecar)"""
        if not entry.file_path_after:
            raise ValueError("file_path_after مفقود لعملية move")
        src = Path(entry.file_path_after)
        dst = Path(entry.file_path)

        if not src.exists():
            logger.warning(f"ملف الوجهة غير موجود للتراجع: {src}")
            return

        dst.parent.mkdir(parents=True, exist_ok=True)

        # نقل الملف + sidecar (إن وُجد في الوجهة)
        from .rule_engine import _sidecar_path
        src_sidecar = _sidecar_path(str(src))
        shutil.move(str(src), str(dst))
        if src_sidecar.exists():
            dst_sidecar = _sidecar_path(str(dst))
            if dst_sidecar.exists():
                # دمج (نادر)
                dst_sidecar.unlink()
            shutil.move(str(src_sidecar), str(dst_sidecar))

    def _rollback_copy(self, entry: UndoEntry) -> None:
        """عكس النسخ: حذف النسخة المنشأة (مع sidecar)"""
        if not entry.file_path_after:
            raise ValueError("file_path_after مفقود لعملية copy")
        copied = Path(entry.file_path_after)
        if copied.exists():
            copied.unlink()
        else:
            logger.warning(f"النسخة المنسوخة غير موجودة: {copied}")
        # حذف sidecar المنسوخ إن وُجد
        from .rule_engine import _sidecar_path
        copied_sidecar = _sidecar_path(str(copied))
        if copied_sidecar.exists():
            copied_sidecar.unlink()

    def _rollback_tag(self, entry: UndoEntry) -> None:
        """عكس إضافة وسم: إزالة الوسم"""
        from .rule_engine import _load_sidecar_tags, _save_sidecar_tags
        for tag in entry.tags_added:
            tags = _load_sidecar_tags(entry.file_path)
            if tag in tags:
                tags = [t for t in tags if t != tag]
                _save_sidecar_tags(entry.file_path, tags)

    def _rollback_untag(self, entry: UndoEntry) -> None:
        """عكس إزالة وسم: إعادة الوسم"""
        from .rule_engine import _load_sidecar_tags, _save_sidecar_tags
        for tag in entry.tags_removed:
            tags = _load_sidecar_tags(entry.file_path)
            if tag not in tags:
                tags.append(tag)
                _save_sidecar_tags(entry.file_path, tags)

    def _rollback_set_category(self, entry: UndoEntry) -> None:
        """عكس ضبط التصنيف: استعادة التصنيف الأصلي

        لو old_category كان فارغًا (لم يكن للـ sidecar تصنيف سابق)،
        نحذف مفتاح category بالكامل بدلًا من ترك قيمة فارغة.
        """
        from .rule_engine import _load_sidecar, _save_sidecar
        sidecar = _load_sidecar(entry.file_path)
        if entry.old_category:
            sidecar["category"] = entry.old_category
        else:
            # إزالة المفتاح لو كان فارغًا أصلاً
            sidecar.pop("category", None)
        _save_sidecar(entry.file_path, sidecar)

    def _rollback_delete_flag(self, entry: UndoEntry) -> None:
        """عكس وسم الحذف: إزالة وسم to_delete"""
        from .rule_engine import _load_sidecar_tags, _save_sidecar_tags
        tags = _load_sidecar_tags(entry.file_path)
        if "to_delete" in tags:
            tags = [t for t in tags if t != "to_delete"]
            _save_sidecar_tags(entry.file_path, tags)


# ─── Utility: عرض السجل ─────────────────────────────────────────────────────

def format_undo_log_summary(log: UndoLog) -> str:
    """يُرجع ملخصًا نصيًا للسجل (للعرض في CLI)"""
    if not log.entries:
        return "سجل التراجع فارغ."
    lines = [f"سجل التراجع ({len(log.entries)} إجراء):"]
    for i, e in enumerate(log.entries, start=1):
        status = "✓" if e.success else "✗"
        lines.append(
            f"  {i}. [{status}] {e.action_type:14s} {e.file_name() if hasattr(e, 'file_name') else Path(e.file_path).name}  ({e.rule_name})"
        )
    return "\n".join(lines)
