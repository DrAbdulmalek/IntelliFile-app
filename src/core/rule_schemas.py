"""Rule schema — تعريف هياكل القواعد والمحاكاة (dry-run) والتراجع (undo)

هذا الملف يعرّف هياكل البيانات المستخدمة في:
  - قواعد التصنيف والتنظيم (YAML rules)
  - خطط المحاكاة (dry-run plans)
  - سجل التراجع (undo log entries)

التصميم:
  - كل القواعد serializable (to_dict / from_dict) لقابلية القراءة والكتابة YAML
  - أنواع الشروط (Condition) مدعومة: extension, category, size, name_contains,
    path_contains, mime_type_contains, has_tag, has_exif, is_duplicate
  - أنواع الإجراءات (Action): move, copy, tag, untag, set_category, delete_flag
  - لا توجد إجراءات تدميرية تلقائية — delete_flag فقط يضع وسم "to_delete"
    ويحتاج تأكيدًا صريحًا منفصلًا (out of scope لهذا PR)

PR-05 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# ─── Enums ─────────────────────────────────────────────────────────────────

class ConditionOp(str, Enum):
    """عوامل المقارنة المدعومة"""
    EQ = "eq"          # يساوي (string/number)
    NE = "ne"          # لا يساوي
    IN = "in"          # عضو في قائمة
    NOT_IN = "not_in"  # ليس عضوًا في قائمة
    CONTAINS = "contains"  # يحتوي على substring
    GT = "gt"          # أكبر من (number)
    GTE = "gte"        # أكبر من أو يساوي
    LT = "lt"          # أصغر من
    LTE = "lte"        # أصغر من أو يساوي
    EXISTS = "exists"  # الحقل موجود (ولو فارغ)


class ActionType(str, Enum):
    """أنواع الإجراءات المدعومة"""
    MOVE = "move"                # نقل الملف إلى مجلد
    COPY = "copy"                # نسخ الملف
    TAG = "tag"                  # إضافة وسم
    UNTAG = "untag"              # إزالة وسم
    SET_CATEGORY = "set_category"  # تعيين تصنيف
    DELETE_FLAG = "delete_flag"  # وسم "للحذف" (لا حذف فعلي)


class ConditionField(str, Enum):
    """حقول الشروط المدعومة — تُطابق حقول FileMetadata + extra_metadata"""
    EXTENSION = "extension"
    CATEGORY = "category"
    FILE_NAME = "file_name"
    FILE_PATH = "file_path"
    PARENT_DIR = "parent_dir"
    FILE_SIZE = "file_size"            # bytes
    MIME_TYPE = "mime_type"
    CONTENT_TYPE = "content_type"
    IS_DUPLICATE = "is_duplicate"
    HAS_TAG = "has_tag"
    HAS_EXIF = "has_exif"
    # شروط على extra_metadata (تُستخدم بناءً على نوع الوسيط)
    EXTRA = "extra"  # يتطلب مفتاحًا فرعيًا: extra:width


# ─── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class Condition:
    """شرط واحد على FileMetadata

    Examples:
        Condition(field="extension", op="in", value=["jpg", "png"])
        Condition(field="file_size", op="gt", value=10_000_000)  # > 10MB
        Condition(field="extra", op="gt", value=1920, key="width")
    """
    field: str
    op: str
    value: Any = None
    # مفتاح فرعي للحقول المتداخلة (مثل extra:width) — يستخدم مع field="extra"
    key: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"field": self.field, "op": self.op}
        if self.value is not None:
            d["value"] = self.value
        if self.key is not None:
            d["key"] = self.key
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        return cls(
            field=d["field"],
            op=d["op"],
            value=d.get("value"),
            key=d.get("key"),
        )

    def __str__(self) -> str:
        if self.field == "extra" and self.key:
            return f"extra.{self.key} {self.op} {self.value!r}"
        return f"{self.field} {self.op} {self.value!r}"


@dataclass
class Action:
    """إجراء واحد على ملف

    Examples:
        Action(type="move", target="Pictures/2026")
        Action(type="tag", value="large-photo")
        Action(type="set_category", value="صور")
    """
    type: str
    # target: مسار الوجهة (نسبي من قاعدة التنظيم) للنقل/النسخ
    target: Optional[str] = None
    # value: قيمة الوسم/التصنيف
    value: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"type": self.type}
        if self.target is not None:
            d["target"] = self.target
        if self.value is not None:
            d["value"] = self.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        return cls(
            type=d["type"],
            target=d.get("target"),
            value=d.get("value"),
        )

    def __str__(self) -> str:
        if self.type in ("move", "copy"):
            return f"{self.type} → {self.target}"
        if self.type in ("tag", "untag"):
            return f"{self.type} {self.value!r}"
        if self.type == "set_category":
            return f"set_category={self.value!r}"
        if self.type == "delete_flag":
            return "flag for deletion"
        return f"{self.type}({self.value!r})"


@dataclass
class Rule:
    """قاعدة كاملة: اسم + شروط (AND) + إجراءات

    مثال YAML:
        name: "Move large photos to Pictures/Large"
        description: "صور أكبر من 5MB"
        priority: 10
        conditions:
          - field: extension
            op: in
            value: [jpg, jpeg, png]
          - field: file_size
            op: gt
            value: 5242880  # 5MB
        actions:
          - type: move
            target: Pictures/Large
          - type: tag
            value: large-photo
    """
    name: str
    conditions: List[Condition] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    description: str = ""
    priority: int = 0  # الأعلى أولًا
    enabled: bool = True
    tags: List[str] = field(default_factory=list)  # وسوم وصفية للقاعدة نفسها

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "enabled": self.enabled,
            "tags": list(self.tags),
            "conditions": [c.to_dict() for c in self.conditions],
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            priority=d.get("priority", 0),
            enabled=d.get("enabled", True),
            tags=list(d.get("tags", [])),
            conditions=[Condition.from_dict(c) for c in d.get("conditions", [])],
            actions=[Action.from_dict(a) for a in d.get("actions", [])],
        )

    def matches_all_conditions(self, metadata_dict: dict) -> bool:
        """تتحقق من جميع الشروط (AND logic)

        Args:
            metadata_dict: قاموس FileMetadata.to_dict() مع extra_metadata مدموجة
        """
        for cond in self.conditions:
            if not _evaluate_condition(cond, metadata_dict):
                return False
        return True


# ─── تقييم الشرط ────────────────────────────────────────────────────────────

def _get_field_value(metadata: dict, field_name: str, key: Optional[str] = None) -> Any:
    """يستخرج قيمة الحقل من قاموس الميتاداتا

    يدعم:
      - الحقول المسطحة (file_name, extension, ...)
      - extra_metadata مع key فرعي
      - has_tag (يفحص وجود وسم في tags)
      - has_exif (يفحص وجود exif في extra_metadata)
    """
    if field_name == "extra" and key:
        # الحقل في extra_metadata
        extra = metadata.get("extra_metadata", {})
        return extra.get(key)
    if field_name == "has_tag":
        # قيمة الشرط = اسم الوسم المراد فحصه
        tags = metadata.get("tags", [])
        return metadata.get("_tag_to_check") in tags if "_tag_to_check" in metadata else None
    if field_name == "has_exif":
        extra = metadata.get("extra_metadata", {})
        # نُرجع True لو يوجد EXIF غير فارغ، None لو لا يوجد
        # (حتى يكون عامل "exists" دقيقًا: exists = EXIF موجود فعلًا)
        if "exif" in extra and bool(extra["exif"]):
            return True
        return None
    # حقل مسطح
    return metadata.get(field_name)


def _evaluate_condition(cond: Condition, metadata: dict) -> bool:
    """يقيّم شرطًا واحدًا ضد قاموس الميتاداتا"""
    field_value = _get_field_value(metadata, cond.field, cond.key)
    op = cond.op
    target = cond.value

    # EXISTS يفحص وجود الحقل فقط
    if op == ConditionOp.EXISTS.value:
        return field_value is not None

    # باقي العوامل تتطلب قيمة فعلية
    if field_value is None:
        return False

    if op == ConditionOp.EQ.value:
        return field_value == target
    if op == ConditionOp.NE.value:
        return field_value != target
    if op == ConditionOp.IN.value:
        if not isinstance(target, (list, tuple, set)):
            return False
        return field_value in target
    if op == ConditionOp.NOT_IN.value:
        if not isinstance(target, (list, tuple, set)):
            return False
        return field_value not in target
    if op == ConditionOp.CONTAINS.value:
        if not isinstance(field_value, str):
            return False
        return str(target) in field_value
    # عوامل رقمية
    try:
        fv = float(field_value)
        tv = float(target)
    except (TypeError, ValueError):
        return False
    if op == ConditionOp.GT.value:
        return fv > tv
    if op == ConditionOp.GTE.value:
        return fv >= tv
    if op == ConditionOp.LT.value:
        return fv < tv
    if op == ConditionOp.LTE.value:
        return fv <= tv

    return False  # عامل غير معروف


# ─── Dry-Run Plan ──────────────────────────────────────────────────────────

@dataclass
class PlannedAction:
    """إجراء مخطّط لملف واحد (نتيجة dry-run)

    يحتوي على المعلومات اللازمة لتنفيذ الإجراء أو التراجع عنه
    """
    rule_name: str
    file_path: str
    file_name: str
    action: Action
    # معلومات إضافية للعرض في التقرير
    matched_conditions: List[str] = field(default_factory=list)
    # الحالة قبل التنفيذ (يملأها المنفّذ)
    original_category: str = ""
    original_tags: List[str] = field(default_factory=list)
    # مسار الوجهة بعد التنفيذ (للنقل/النسخ)
    target_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "action": self.action.to_dict(),
            "matched_conditions": list(self.matched_conditions),
            "original_category": self.original_category,
            "original_tags": list(self.original_tags),
            "target_path": self.target_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlannedAction":
        return cls(
            rule_name=d["rule_name"],
            file_path=d["file_path"],
            file_name=d["file_name"],
            action=Action.from_dict(d["action"]),
            matched_conditions=list(d.get("matched_conditions", [])),
            original_category=d.get("original_category", ""),
            original_tags=list(d.get("original_tags", [])),
            target_path=d.get("target_path"),
        )


@dataclass
class DryRunPlan:
    """خطة محاكاة كاملة لمجلد واحد"""
    ruleset_name: str = ""
    base_dir: str = ""
    planned_actions: List[PlannedAction] = field(default_factory=list)
    skipped_files: List[Dict[str, str]] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ruleset_name": self.ruleset_name,
            "base_dir": self.base_dir,
            "planned_actions": [a.to_dict() for a in self.planned_actions],
            "skipped_files": list(self.skipped_files),
            "summary": dict(self.summary),
        }

    @property
    def total_actions(self) -> int:
        return len(self.planned_actions)

    @property
    def files_affected(self) -> int:
        return len({a.file_path for a in self.planned_actions})

    def action_type_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for a in self.planned_actions:
            t = a.action.type
            counts[t] = counts.get(t, 0) + 1
        return counts


# ─── Undo Log Entry ────────────────────────────────────────────────────────

@dataclass
class UndoEntry:
    """سجل تراجع عن إجراء واحد منفّذ

    يخزّن معلومات كافية لعكس الإجراء:
      - move: source + destination (reverse = move destination → source)
      - copy: destination (reverse = delete destination)
      - tag: file + tag added (reverse = remove tag)
      - untag: file + tag removed (reverse = re-add tag)
      - set_category: file + old_category + new_category (reverse = restore)
      - delete_flag: file (reverse = remove flag — just a tag)
    """
    action_type: str
    file_path: str              # المسار الأصلي قبل أي نقل
    file_path_after: Optional[str] = None  # المسار بعد النقل/النسخ
    rule_name: str = ""
    old_category: str = ""
    new_category: str = ""
    tags_added: List[str] = field(default_factory=list)
    tags_removed: List[str] = field(default_factory=list)
    timestamp: str = ""
    success: bool = True
    error_message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UndoEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─── Ruleset (ملف قواعد كامل) ──────────────────────────────────────────────

@dataclass
class Ruleset:
    """مجموعة قواعد كاملة محمّلة من YAML

    مثال YAML:
        name: "Default Organization Rules"
        description: "قواعد افتراضية لتنظيم الملفات"
        rules:
          - name: "..."
            conditions: [...]
            actions: [...]
    """
    name: str = ""
    description: str = ""
    rules: List[Rule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Ruleset":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            rules=[Rule.from_dict(r) for r in d.get("rules", [])],
        )

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "Ruleset":
        """يحمّل قواعد من ملف YAML"""
        import yaml
        with open(str(path), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"ملف YAML غير صالح: {path}")
        return cls.from_dict(data)

    def to_yaml(self, path: Union[str, Path]) -> None:
        """يكتب القواعد إلى ملف YAML"""
        import yaml
        with open(str(path), "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)

    @property
    def enabled_rules(self) -> List[Rule]:
        """القواعد المفعّلة مرتّبة حسب الأولوية (الأعلى أولًا)"""
        return sorted(
            [r for r in self.rules if r.enabled],
            key=lambda r: r.priority,
            reverse=True,
        )
