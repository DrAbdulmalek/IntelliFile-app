"""RuleEngine — محرّك قواعد التصنيف والتنظيم

هذا الملف ينفّذ:
  - تحميل قواعد YAML (Ruleset)
  - تقييم القواعد على FileRecord (من FileInventory)
  - dry-run: إنتاج خطة PlannedAction[] بدون تنفيذ فعلي
  - execute: تنفيذ الإجراءات مع تسجيل UndoEntry لكل إجراء
  - تكامل مع FileInventory (سلسلة: مسح → تطابق قواعد → تنفيذ/محاكاة)

التصميم:
  - لا إجراءات تدميرية: delete_flag فقط يضع وسم "to_delete"
  - كل نقل/نسخ يُسجَّل في undo_log للتراجع
  - عمليات tag/untag/set_category تُطبَّق على FileMetadata.tags/category
    (الـ metadata تُعاد إلى الحالة الأصلية عند التراجع)
  - النقل/النسخ الفعلي للملف يحدث على القرص + يُحدَّث file_path في metadata

PR-05 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Union

from ..db.schemas import FileRecord, FileMetadata
from .rule_schemas import (
    Action, ActionType, Condition, DryRunPlan, PlannedAction, Rule, Ruleset,
    UndoEntry,
)
from .file_inventory import FileInventory

logger = logging.getLogger(__name__)


class RuleEngine:
    """محرّك قواعد التصنيف والتنظيم

    الاستخدام الأساسي:

        engine = RuleEngine(ruleset)
        # محاكاة (لا تغييرات على القرص)
        plan = engine.dry_run(records, base_dir="/data")
        # تنفيذ (تطبيق الإجراءات + تسجيل undo entries)
        entries = engine.execute(plan, undo_log_path="/data/.ifm_undo.json")

    أو دمج المسح مع المحاكاة:

        inventory = FileInventory()
        records = inventory.scan_directory("/data")
        plan = engine.dry_run(records, base_dir="/data")
    """

    def __init__(self, ruleset: Ruleset):
        self.ruleset = ruleset

    # ─── Dry-Run ────────────────────────────────────────────────────────

    def dry_run(
        self,
        records: Iterable[FileRecord],
        *,
        base_dir: str = "",
    ) -> DryRunPlan:
        """ينتج خطة محاكاة بدون تعديل أي ملف

        Args:
            records: سجلات الملفات (من FileInventory.scan)
            base_dir: المجلد الأساسي (لحساب المسارات النسبية في الأهداف)

        Returns:
            DryRunPlan: خطة تحتوي على PlannedAction لكل ملف مطابق
        """
        plan = DryRunPlan(
            ruleset_name=self.ruleset.name,
            base_dir=str(base_dir),
        )

        rules = self.ruleset.enabled_rules
        if not rules:
            plan.summary = {"error": "no enabled rules"}
            return plan

        for record in records:
            metadata_dict = self._record_to_eval_dict(record)
            matched_rule: Optional[Rule] = None

            # أول قاعدة مطابقة فقط (first-match-wins) — ترتيب الأولوية
            for rule in rules:
                if rule.matches_all_conditions(metadata_dict):
                    matched_rule = rule
                    break

            if matched_rule is None:
                plan.skipped_files.append({
                    "file_path": record.metadata.file_path,
                    "file_name": record.metadata.file_name,
                    "reason": "no rule matched",
                })
                continue

            # بناء PlannedAction لكل إجراء في القاعدة
            for action in matched_rule.actions:
                planned = self._build_planned_action(
                    matched_rule, action, record, base_dir
                )
                if planned is not None:
                    plan.planned_actions.append(planned)

        plan.summary = self._build_summary(plan)
        return plan

    # ─── Execute ────────────────────────────────────────────────────────

    def execute(
        self,
        plan: DryRunPlan,
        *,
        undo_log_path: Optional[Union[str, Path]] = None,
        confirm_destructive: bool = False,
    ) -> List[UndoEntry]:
        """ينفّذ خطة محاكاة مع تسجيل كل إجراء للتراجع

        Args:
            plan: خطة من dry_run()
            undo_log_path: مسار ملف سجل التراجع (JSON). إن لم يُمرّر،
                          لا تُكتب السجلات على القرص (تُرجع فقط).
            confirm_destructive: تأكيد صريح للإجراءات التدميرية (delete_flag).
                                افتراضيًا False — لا تُنفَّذ الإجراءات التدميرية.

        Returns:
            List[UndoEntry]: سجل التراجع لكل إجراء نُفّذ
        """
        from .undo_log import UndoLog

        entries: List[UndoEntry] = []
        undo_log = UndoLog(undo_log_path) if undo_log_path else UndoLog(None)

        # تتبّع المسار الحالي لكل ملف بعد النقل/النسخ (لو نُقل ملف ثم وُسم بعد ذلك)
        # الخريطة: original_path → current_path
        path_remap: dict[str, str] = {}

        for planned in plan.planned_actions:
            # تخطّي الإجراءات التدميرية بدون تأكيد
            if (planned.action.type == ActionType.DELETE_FLAG.value
                    and not confirm_destructive):
                logger.info(
                    f"تخطّي إجراء تدميري على {planned.file_name} "
                    f"(يحتاج confirm_destructive=True)"
                )
                continue

            # إنشاء نسخة من planned بمسار محدَّث لو كان الملف نُقل سابقًا
            effective_planned = planned
            current_path = path_remap.get(planned.file_path, planned.file_path)
            if current_path != planned.file_path:
                effective_planned = PlannedAction(
                    rule_name=planned.rule_name,
                    file_path=current_path,
                    file_name=Path(current_path).name,
                    action=planned.action,
                    matched_conditions=planned.matched_conditions,
                    original_category=planned.original_category,
                    original_tags=planned.original_tags,
                    target_path=planned.target_path,
                )

            try:
                entry = self._execute_single(effective_planned, undo_log)
                # تحديث خريطة المسار بعد النقل/النسخ الناجح
                if entry.success and entry.file_path_after:
                    if entry.action_type in (ActionType.MOVE.value,):
                        path_remap[planned.file_path] = entry.file_path_after
                entries.append(entry)
            except Exception as e:
                logger.error(f"فشل تنفيذ {planned.action.type} على {planned.file_name}: {e}")
                entry = UndoEntry(
                    action_type=planned.action.type,
                    file_path=planned.file_path,
                    rule_name=planned.rule_name,
                    timestamp=datetime.now().isoformat(),
                    success=False,
                    error_message=str(e)[:200],
                )
                entries.append(entry)
                undo_log.append(entry)

        # حفظ السجل على القرص
        if undo_log_path:
            undo_log.save()

        return entries

    # ─── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _record_to_eval_dict(record: FileRecord) -> dict:
        """يحوّل FileRecord إلى قاموس مسطّح للتقييم"""
        m = record.metadata
        d = m.to_dict()
        # دمج extra_metadata للوصول إلى حقول مثل extra:width
        d["extra_metadata"] = m.extra_metadata
        # has_tag يحتاج tags في الميتاداتا
        d["tags"] = list(m.tags)
        return d

    @staticmethod
    def _build_planned_action(
        rule: Rule,
        action: Action,
        record: FileRecord,
        base_dir: str,
    ) -> Optional[PlannedAction]:
        """يبني PlannedAction واحدًا"""
        m = record.metadata

        # حساب target_path للنقل/النسخ
        target_path = None
        if action.type in (ActionType.MOVE.value, ActionType.COPY.value):
            if not action.target:
                logger.warning(f"قاعدة {rule.name}: إجراء {action.type} بدون target")
                return None
            # الهدف قد يكون مسارًا نسبيًا من base_dir أو مطلقًا
            if os.path.isabs(action.target):
                target_dir = Path(action.target)
            else:
                target_dir = Path(base_dir) / action.target
            target_path = str(target_dir / m.file_name)

        return PlannedAction(
            rule_name=rule.name,
            file_path=m.file_path,
            file_name=m.file_name,
            action=action,
            matched_conditions=[str(c) for c in rule.conditions],
            original_category=m.category,
            original_tags=list(m.tags),
            target_path=target_path,
        )

    @staticmethod
    def _build_summary(plan: DryRunPlan) -> dict:
        """يبني ملخصًا إحصائيًا للخطة"""
        return {
            "total_actions": plan.total_actions,
            "files_affected": plan.files_affected,
            "files_skipped": len(plan.skipped_files),
            "action_type_counts": plan.action_type_counts(),
            "ruleset_name": plan.ruleset_name,
            "base_dir": plan.base_dir,
        }

    def _execute_single(
        self,
        planned: PlannedAction,
        undo_log: "UndoLog",
    ) -> UndoEntry:
        """ينفّذ إجراءًا واحدًا ويسجّله في undo_log"""
        action_type = planned.action.type
        timestamp = datetime.now().isoformat()

        if action_type == ActionType.MOVE.value:
            return self._exec_move(planned, undo_log, timestamp)
        if action_type == ActionType.COPY.value:
            return self._exec_copy(planned, undo_log, timestamp)
        if action_type == ActionType.TAG.value:
            return self._exec_tag(planned, undo_log, timestamp)
        if action_type == ActionType.UNTAG.value:
            return self._exec_untag(planned, undo_log, timestamp)
        if action_type == ActionType.SET_CATEGORY.value:
            return self._exec_set_category(planned, undo_log, timestamp)
        if action_type == ActionType.DELETE_FLAG.value:
            return self._exec_delete_flag(planned, undo_log, timestamp)

        raise ValueError(f"نوع إجراء غير معروف: {action_type}")

    # ─── منفّذو الإجراءات ────────────────────────────────────────────────

    def _exec_move(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """ينفّذ نقل ملف على القرص (مع نقل ملف sidecar إن وُجد)"""
        if not planned.target_path:
            raise ValueError("target_path مفقود لعملية move")
        src = Path(planned.file_path)
        dst = Path(planned.target_path)

        if not src.exists():
            raise FileNotFoundError(f"الملف المصدر غير موجود: {src}")

        # إنشاء المجلد الوجهة إن لم يكن موجودًا
        dst.parent.mkdir(parents=True, exist_ok=True)

        # لو الوجهة موجودة، نضيف لاحقة للاسم
        if dst.exists() and src.resolve() != dst.resolve():
            stem = dst.stem
            suffix = dst.suffix
            counter = 1
            while dst.exists():
                dst = dst.with_name(f"{stem}_{counter}{suffix}")
                counter += 1

        # نقل الملف + sidecar (إن وُجد)
        src_sidecar = _sidecar_path(str(src))
        shutil.move(str(src), str(dst))
        if src_sidecar.exists():
            dst_sidecar = _sidecar_path(str(dst))
            # لو الوجهة موجودة (نادر)، ندمج
            if dst_sidecar.exists():
                _merge_sidecar(str(dst), src_sidecar)
                src_sidecar.unlink()
            else:
                shutil.move(str(src_sidecar), str(dst_sidecar))

        entry = UndoEntry(
            action_type=ActionType.MOVE.value,
            file_path=str(src),
            file_path_after=str(dst),
            rule_name=planned.rule_name,
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry

    def _exec_copy(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """ينفّذ نسخ ملف على القرص (مع نسخ sidecar إن وُجد)"""
        if not planned.target_path:
            raise ValueError("target_path مفقود لعملية copy")
        src = Path(planned.file_path)
        dst = Path(planned.target_path)

        if not src.exists():
            raise FileNotFoundError(f"الملف المصدر غير موجود: {src}")

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists() and src.resolve() != dst.resolve():
            stem = dst.stem
            suffix = dst.suffix
            counter = 1
            while dst.exists():
                dst = dst.with_name(f"{stem}_{counter}{suffix}")
                counter += 1

        shutil.copy2(str(src), str(dst))

        # نسخ sidecar إن وُجد (الوسوم الحالية للملف المنسوخ)
        src_sidecar = _sidecar_path(str(src))
        if src_sidecar.exists():
            dst_sidecar = _sidecar_path(str(dst))
            if dst_sidecar.exists():
                _merge_sidecar(str(dst), src_sidecar)
            else:
                shutil.copy2(str(src_sidecar), str(dst_sidecar))

        entry = UndoEntry(
            action_type=ActionType.COPY.value,
            file_path=str(src),
            file_path_after=str(dst),
            rule_name=planned.rule_name,
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry

    def _exec_tag(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """يضيف وسمًا (هذا تغيير منطقي على metadata فقط — لا يغيّر الملف على القرص)

        ملاحظة: بما أن FileRecord في الذاكرة فقط، فإن الإضافة هنا تُسجَّل
        في undo_log فقط. التطبيق الفعلي على قاعدة بيانات الواجهة يحدث في طبقة
        أعلى (خارج نطاق هذا PR). نُسجّل أيضًا في ملف جانبي .ifm_tags.json
        في نفس مجلد الملف لتتبع العلامات عبر الجلسات.
        """
        tag = planned.action.value
        if not tag:
            raise ValueError("value مفقود لإجراء tag")

        # تحميل الوسوم الحالية من ملف جانبي
        tags = _load_sidecar_tags(planned.file_path)
        if tag not in tags:
            tags.append(tag)
            _save_sidecar_tags(planned.file_path, tags)

        entry = UndoEntry(
            action_type=ActionType.TAG.value,
            file_path=planned.file_path,
            rule_name=planned.rule_name,
            tags_added=[tag],
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry

    def _exec_untag(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """يزيل وسمًا من ملف"""
        tag = planned.action.value
        if not tag:
            raise ValueError("value مفقود لإجراء untag")

        tags = _load_sidecar_tags(planned.file_path)
        removed = tag in tags
        if removed:
            tags = [t for t in tags if t != tag]
            _save_sidecar_tags(planned.file_path, tags)

        entry = UndoEntry(
            action_type=ActionType.UNTAG.value,
            file_path=planned.file_path,
            rule_name=planned.rule_name,
            tags_removed=[tag] if removed else [],
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry

    def _exec_set_category(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """يضبط التصنيف — يُسجّل في ملف sidecar أيضًا

        ملاحظة: old_category يخزّن القيمة الفعلية من sidecar (إن وُجدت) أو
        سلسلة فارغة لو لم يكن للـ sidecar تصنيف سابق. هذا يضمن أن rollback
        يعيد الحالة الفعلية (وليس قيمة FileMetadata المشتقة من الامتداد).
        """
        new_cat = planned.action.value
        if not new_cat:
            raise ValueError("value مفقود لإجراء set_category")

        sidecar = _load_sidecar(planned.file_path)
        # نُفضّل القيمة الفعلية من sidecar (قد تكون فارغة)، وليس planned.original_category
        old_cat = sidecar.get("category", "")
        sidecar["category"] = new_cat
        _save_sidecar(planned.file_path, sidecar)

        entry = UndoEntry(
            action_type=ActionType.SET_CATEGORY.value,
            file_path=planned.file_path,
            rule_name=planned.rule_name,
            old_category=old_cat,
            new_category=new_cat,
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry

    def _exec_delete_flag(
        self, planned: PlannedAction, undo_log: "UndoLog", timestamp: str
    ) -> UndoEntry:
        """يضع وسم 'to_delete' (لا حذف فعلي)"""
        tags = _load_sidecar_tags(planned.file_path)
        if "to_delete" not in tags:
            tags.append("to_delete")
            _save_sidecar_tags(planned.file_path, tags)

        entry = UndoEntry(
            action_type=ActionType.DELETE_FLAG.value,
            file_path=planned.file_path,
            rule_name=planned.rule_name,
            tags_added=["to_delete"],
            timestamp=timestamp,
            success=True,
        )
        undo_log.append(entry)
        return entry


# ─── Sidecar helpers (ملفات JSON بجانب كل ملف) ─────────────────────────────

def _sidecar_path(file_path: str) -> Path:
    """يُرجع مسار ملف sidecar (.ifm_meta.json) بجانب الملف"""
    p = Path(file_path)
    return p.parent / f".ifm_meta_{p.name}.json"


def _load_sidecar(file_path: str) -> dict:
    """يحمّل ملف sidecar (أو يُرجع {} إذا لم يكن موجودًا)"""
    import json
    sc = _sidecar_path(file_path)
    if not sc.exists():
        return {}
    try:
        return json.loads(sc.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sidecar(file_path: str, data: dict) -> None:
    """يكتب ملف sidecar"""
    import json
    sc = _sidecar_path(file_path)
    sc.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_sidecar_tags(file_path: str) -> List[str]:
    """يحمّل الوسوم من sidecar"""
    return list(_load_sidecar(file_path).get("tags", []))


def _save_sidecar_tags(file_path: str, tags: List[str]) -> None:
    """يحدّث الوسوم في sidecar (مع الحفاظ على الحقول الأخرى)"""
    data = _load_sidecar(file_path)
    data["tags"] = list(tags)
    _save_sidecar(file_path, data)


def _merge_sidecar(target_path: str, source_sidecar: Path) -> None:
    """يدمج محتوى sidecar مصدر في sidecar هدف (للنسخ/النقل عند تضارب الأسماء)

    الوسوم: اتحاد القائمتين (deduped)
    التصنيف: يُحتفظ بقيمة الهدف إن وُجدت، وإلا يؤخذ من المصدر
    """
    target_data = _load_sidecar(target_path)
    try:
        source_data = json.loads(source_sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        source_data = {}

    merged_tags = list(set(target_data.get("tags", []) + source_data.get("tags", [])))
    target_data["tags"] = merged_tags
    if "category" not in target_data and "category" in source_data:
        target_data["category"] = source_data["category"]
    _save_sidecar(target_path, target_data)
