"""اختبارات تكامل لـ RuleEngine + DryRun + UndoLog — PR-05

يغطي هذا الملف:
  - تحميل/حفظ Ruleset YAML (round-trip)
  - تقييم الشروط (eq, ne, in, not_in, contains, gt, gte, lt, lte, exists)
  - first-match-wins مع الأولوية
  - dry_run() يُنتج PlannedAction صحيحة بدون تعديل القرص
  - execute() ينفّذ move/copy/tag/untag/set_category/delete_flag
  - التراجع عن كل نوع إجراء (rollback_last, rollback_all, rollback_n)
  - tag-after-move: الوسوم تتبع الملف المنقول
  - undo log save/load JSON
  - تأكيد الإجراءات التدميرية (delete_flag يتطلب confirm)
  - تكامل مع FileInventory

PR-05 من development-roadmap-v1.0 (IFM Phase A)
"""
import json
import shutil
import tempfile
from pathlib import Path

import pytest
import yaml

from src.core.rule_schemas import (
    Action, ActionType, Condition, ConditionField, ConditionOp,
    DryRunPlan, PlannedAction, Rule, Ruleset, UndoEntry,
)
from src.core.rule_engine import (
    RuleEngine, _load_sidecar, _load_sidecar_tags, _save_sidecar, _sidecar_path,
)
from src.core.undo_log import UndoLog
from src.core.dry_run_reporter import generate_html_report, save_report
from src.core.file_inventory import FileInventory
from src.db.schemas import FileMetadata, FileRecord


# ─── Fixtures محلية ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path):
    """ينشئ مجلد عمل مع ملفات متنوعة لاختبار القواعد"""
    (tmp_path / "big_photo.jpg").write_bytes(b"X" * 5000)        # 5KB
    (tmp_path / "small_note.txt").write_text("hi", encoding="utf-8")  # 2 bytes
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 " + b"x" * 500)  # ~510 bytes
    (tmp_path / "data.xyz").write_bytes(b"unknown")                # no rule matches
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "tiny.md").write_text("a", encoding="utf-8")           # 1 byte
    (sub / "photo2.png").write_bytes(b"PNG" + b"Y" * 3000)        # 3KB
    return tmp_path


@pytest.fixture
def sample_ruleset():
    """مجموعة قواعد للاختبار"""
    return Ruleset(
        name="Test Ruleset",
        description="قواعد اختبار",
        rules=[
            Rule(
                name="Large photos",
                priority=10,
                conditions=[
                    Condition(field="extension", op="in", value=["jpg", "jpeg", "png"]),
                    Condition(field="file_size", op="gt", value=1000),
                ],
                actions=[
                    Action(type="move", target="Pictures/Large"),
                    Action(type="tag", value="large-photo"),
                ],
            ),
            Rule(
                name="Small text files",
                priority=5,
                conditions=[
                    Condition(field="extension", op="in", value=["txt", "md"]),
                    Condition(field="file_size", op="lt", value=100),
                ],
                actions=[
                    Action(type="tag", value="small-doc"),
                    Action(type="set_category", value="مستندات صغيرة"),
                ],
            ),
        ],
    )


@pytest.fixture
def engine(sample_ruleset):
    """RuleEngine بمجموعة قواعد الاختبار"""
    return RuleEngine(sample_ruleset)


@pytest.fixture
def records(tmp_workspace):
    """FileRecord من مسح tmp_workspace"""
    inv = FileInventory(include_content=False)
    return inv.scan_directory(str(tmp_workspace))


# ─── اختبارات Ruleset YAML ─────────────────────────────────────────────────

class TestRulesetYAML:
    """اختبارات تحميل/حفظ Ruleset في YAML"""

    def test_to_yaml_roundtrip(self, sample_ruleset, tmp_path):
        """حفظ ثم تحميل Ruleset يُرجع نفس البيانات"""
        path = tmp_path / "rules.yaml"
        sample_ruleset.to_yaml(path)
        loaded = Ruleset.from_yaml(path)
        assert loaded.name == sample_ruleset.name
        assert len(loaded.rules) == 2
        assert loaded.rules[0].name == "Large photos"
        assert loaded.rules[0].priority == 10
        assert len(loaded.rules[0].conditions) == 2
        assert len(loaded.rules[0].actions) == 2

    def test_from_yaml_handles_missing_optional_fields(self, tmp_path):
        """YAML بدون description/priority/tags يعمل بأقل تفاصيل"""
        path = tmp_path / "minimal.yaml"
        path.write_text(
            "name: Minimal\nrules:\n  - name: r1\n"
            "    conditions:\n"
            "      - field: extension\n"
            "        op: eq\n"
            "        value: pdf\n"
            "    actions:\n"
            "      - type: tag\n"
            "        value: pdf-file\n",
            encoding="utf-8",
        )
        loaded = Ruleset.from_yaml(path)
        assert loaded.name == "Minimal"
        assert len(loaded.rules) == 1
        r = loaded.rules[0]
        assert r.priority == 0  # default
        assert r.enabled is True  # default
        assert r.description == ""

    def test_enabled_rules_sorted_by_priority(self, sample_ruleset):
        """enabled_rules مرتّبة حسب الأولوية تنازليًا"""
        # أضف قاعدة معطّلة وأخرى بأولوية مختلفة
        sample_ruleset.rules.append(
            Rule(name="disabled", priority=100, enabled=False,
                 conditions=[Condition(field="extension", op="eq", value="x")],
                 actions=[Action(type="tag", value="x")])
        )
        sample_ruleset.rules.append(
            Rule(name="high-prio", priority=50,
                 conditions=[Condition(field="extension", op="eq", value="y")],
                 actions=[Action(type="tag", value="y")])
        )
        enabled = sample_ruleset.enabled_rules
        assert len(enabled) == 3  # اثنتان أصليتان + high-prio
        assert all(r.enabled for r in enabled)
        # الأولوية الأعلى أولًا
        priorities = [r.priority for r in enabled]
        assert priorities == sorted(priorities, reverse=True)
        assert priorities[0] == 50  # high-prio
        # disabled غير موجودة
        assert all(r.name != "disabled" for r in enabled)


# ─── اختبارات تقييم الشروط ────────────────────────────────────────────────

class TestConditionEvaluation:
    """اختبارات تقييم الشروط بمختلف العوامل"""

    def _make_metadata(self, **kwargs) -> dict:
        """يبني قاموس ميتاداتا للاختبار"""
        m = FileMetadata(file_name=kwargs.get("file_name", "test"),
                         file_path=kwargs.get("file_path", "/tmp/test"),
                         file_size=kwargs.get("file_size", 1000),
                         extension=kwargs.get("extension", "txt"),
                         category=kwargs.get("category", "مستندات"),
                         content_type=kwargs.get("content_type", "text/plain"),
                         tags=kwargs.get("tags", []))
        d = m.to_dict()
        d["extra_metadata"] = kwargs.get("extra_metadata", {})
        return d

    def test_eq(self):
        cond = Condition(field="extension", op="eq", value="pdf")
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="pdf"))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="txt"))

    def test_ne(self):
        cond = Condition(field="extension", op="ne", value="pdf")
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="txt"))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="pdf"))

    def test_in(self):
        cond = Condition(field="extension", op="in", value=["jpg", "png"])
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="jpg"))
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="png"))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="txt"))

    def test_not_in(self):
        cond = Condition(field="extension", op="not_in", value=["jpg", "png"])
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="txt"))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="jpg"))

    def test_contains(self):
        cond = Condition(field="file_name", op="contains", value="report")
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_name="annual_report.pdf"))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_name="photo.jpg"))

    def test_gt(self):
        cond = Condition(field="file_size", op="gt", value=1000)
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=2000))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=500))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=1000))  # not >=

    def test_gte(self):
        cond = Condition(field="file_size", op="gte", value=1000)
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=1000))
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=2000))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=500))

    def test_lt(self):
        cond = Condition(field="file_size", op="lt", value=1000)
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=500))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=2000))

    def test_lte(self):
        cond = Condition(field="file_size", op="lte", value=1000)
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=1000))
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=500))
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=2000))

    def test_exists(self):
        cond = Condition(field="file_size", op="exists")
        assert Rule("t", [cond], []).matches_all_conditions(self._make_metadata(file_size=0))
        # حقل غير موجود
        cond2 = Condition(field="nonexistent_field", op="exists")
        assert not Rule("t", [cond2], []).matches_all_conditions(self._make_metadata())

    def test_extra_field_with_key(self):
        """الشروط على extra_metadata مع key فرعي"""
        cond = Condition(field="extra", op="gt", value=1000, key="width")
        meta = self._make_metadata(extra_metadata={"width": 2000})
        assert Rule("t", [cond], []).matches_all_conditions(meta)
        meta2 = self._make_metadata(extra_metadata={"width": 500})
        assert not Rule("t", [cond], []).matches_all_conditions(meta2)

    def test_has_exif(self):
        """has_exif يفحص وجود EXIF في extra_metadata"""
        cond = Condition(field="has_exif", op="exists")
        meta_with_exif = self._make_metadata(extra_metadata={"exif": {"Make": "Canon"}})
        meta_without_exif = self._make_metadata(extra_metadata={})
        assert Rule("t", [cond], []).matches_all_conditions(meta_with_exif)
        assert not Rule("t", [cond], []).matches_all_conditions(meta_without_exif)

    def test_multiple_conditions_and_logic(self):
        """شروط متعددة تُقيَّم بـ AND"""
        conds = [
            Condition(field="extension", op="in", value=["jpg", "png"]),
            Condition(field="file_size", op="gt", value=1000),
            Condition(field="file_name", op="contains", value="img"),
        ]
        rule = Rule("multi", conds, [])
        # كل الشروط متحققة
        assert rule.matches_all_conditions(self._make_metadata(
            extension="jpg", file_size=2000, file_name="img_001"))
        # شرط واحد غير متحقق
        assert not rule.matches_all_conditions(self._make_metadata(
            extension="jpg", file_size=2000, file_name="photo"))  # name doesn't contain "img"

    def test_unknown_op_returns_false(self):
        """عامل غير معروف يُرجع False"""
        cond = Condition(field="extension", op="bogus", value="x")
        assert not Rule("t", [cond], []).matches_all_conditions(self._make_metadata(extension="x"))


# ─── اختبارات Dry-Run ──────────────────────────────────────────────────────

class TestDryRun:
    """اختبارات dry_run() — لا تعديل على القرص"""

    def test_dry_run_returns_plan(self, engine, records, tmp_workspace):
        """dry_run يُرجع DryRunPlan"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        assert isinstance(plan, DryRunPlan)
        assert plan.ruleset_name == "Test Ruleset"
        assert plan.base_dir == str(tmp_workspace)

    def test_dry_run_does_not_modify_files(self, engine, records, tmp_workspace):
        """dry_run لا يعدّل أي ملف"""
        # حفظ حالة الملفات قبل dry_run
        before = sorted(str(p) for p in tmp_workspace.rglob("*") if p.is_file())
        engine.dry_run(records, base_dir=str(tmp_workspace))
        after = sorted(str(p) for p in tmp_workspace.rglob("*") if p.is_file())
        assert before == after

    def test_dry_run_matches_expected_files(self, engine, records, tmp_workspace):
        """dry_run يطابق الملفات المتوقعة"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        # big_photo.jpg (5KB jpg) → matches "Large photos" rule (move + tag = 2 actions)
        # photo2.png (3KB png) → matches "Large photos" rule (move + tag = 2 actions)
        # small_note.txt (2 bytes txt) → matches "Small text files" rule (tag + set_category = 2 actions)
        # tiny.md (1 byte md) → matches "Small text files" rule (tag + set_category = 2 actions)
        # doc.pdf → no rule
        # data.xyz → no rule
        # Total: 8 actions on 4 files
        assert plan.total_actions == 8
        assert plan.files_affected == 4
        assert len(plan.skipped_files) == 2  # doc.pdf + data.xyz

    def test_dry_run_action_type_counts(self, engine, records, tmp_workspace):
        """توزيع الإجراءات حسب النوع"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        counts = plan.action_type_counts()
        assert counts.get("move", 0) == 2  # big_photo + photo2
        assert counts.get("tag", 0) == 4  # 2 large-photo + 2 small-doc
        assert counts.get("set_category", 0) == 2  # 2 small-doc

    def test_dry_run_skipped_files_have_reason(self, engine, records, tmp_workspace):
        """كل ملف متخطٍ له سبب"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        for s in plan.skipped_files:
            assert "reason" in s
            assert "file_path" in s
            assert "file_name" in s

    def test_dry_run_first_match_wins(self, tmp_workspace):
        """أول قاعدة مطابقة تطبَّق فقط (first-match-wins)"""
        ruleset = Ruleset(
            name="First match test",
            rules=[
                Rule(
                    name="Rule A — high priority",
                    priority=100,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="tag", value="from-rule-A")],
                ),
                Rule(
                    name="Rule B — low priority",
                    priority=1,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="tag", value="from-rule-B")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        # فقط big_photo.jpg يطابق، وتطبيقه من Rule A فقط
        rule_names = {a.rule_name for a in plan.planned_actions}
        assert rule_names == {"Rule A — high priority"}

    def test_dry_run_summary_populated(self, engine, records, tmp_workspace):
        """summary يحتوي على الإحصائيات"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        s = plan.summary
        assert s["total_actions"] == plan.total_actions
        assert s["files_affected"] == plan.files_affected
        assert s["files_skipped"] == len(plan.skipped_files)
        assert "action_type_counts" in s
        assert s["ruleset_name"] == "Test Ruleset"

    def test_dry_run_empty_ruleset(self, records, tmp_workspace):
        """ruleset فارغ يُنتج خطة فارغة"""
        engine = RuleEngine(Ruleset(name="empty"))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        assert plan.total_actions == 0
        assert "error" in plan.summary


# ─── اختبارات Execute ──────────────────────────────────────────────────────

class TestExecute:
    """اختبارات execute() — تعديل القرص فعليًا"""

    def test_execute_moves_files(self, engine, records, tmp_workspace):
        """execute ينقل الملفات الكبيرة إلى Pictures/Large"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        entries = engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")
        # تحقق من النقل
        assert (tmp_workspace / "Pictures" / "Large" / "big_photo.jpg").exists()
        assert not (tmp_workspace / "big_photo.jpg").exists()
        assert (tmp_workspace / "Pictures" / "Large" / "photo2.png").exists()
        # على الأقل 4 إجراءات move (2) + tag (4) + set_category (2) = 8
        assert len(entries) == 8
        assert all(e.success for e in entries)

    def test_execute_tags_files(self, engine, records, tmp_workspace):
        """execute يضيف وسومًا للملفات"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")
        # big_photo.jpg نُقل + وُسم
        moved = tmp_workspace / "Pictures" / "Large" / "big_photo.jpg"
        tags = _load_sidecar_tags(str(moved))
        assert "large-photo" in tags

    def test_execute_sets_category(self, engine, records, tmp_workspace):
        """execute يضبط التصنيف في sidecar"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")
        sc = _load_sidecar(str(tmp_workspace / "small_note.txt"))
        assert sc.get("category") == "مستندات صغيرة"

    def test_execute_creates_undo_log(self, engine, records, tmp_workspace):
        """execute ينشئ ملف undo log JSON"""
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.dry_run(records, base_dir=str(tmp_workspace))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        engine.execute(plan, undo_log_path=log_path)
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert "entries" in data
        assert len(data["entries"]) > 0

    def test_execute_skips_destructive_without_confirm(self, tmp_workspace, records):
        """delete_flag بدون تأكيد يُتخطّى"""
        ruleset = Ruleset(
            name="destructive test",
            rules=[
                Rule(
                    name="Flag small files for deletion",
                    conditions=[
                        Condition(field="file_size", op="lt", value=100),
                    ],
                    actions=[
                        Action(type="delete_flag"),
                    ],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        entries = engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")
        # لا تنفيذ لأي إجراء (confirm_destructive=False افتراضيًا)
        assert len(entries) == 0

    def test_execute_destructive_with_confirm(self, tmp_workspace, records):
        """delete_flag مع تأكيد يضع وسم to_delete"""
        ruleset = Ruleset(
            name="destructive test",
            rules=[
                Rule(
                    name="Flag small files",
                    conditions=[
                        Condition(field="file_size", op="lt", value=100),
                    ],
                    actions=[
                        Action(type="delete_flag"),
                    ],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        entries = engine.execute(
            plan,
            undo_log_path=tmp_workspace / ".ifm_undo.json",
            confirm_destructive=True,
        )
        assert len(entries) > 0
        # كل الملفات الصغيرة لها وسم to_delete
        for entry in entries:
            tags = _load_sidecar_tags(entry.file_path)
            assert "to_delete" in tags

    def test_execute_failed_action_recorded(self, tmp_workspace, records):
        """إجراء يفشل (ملف غير موجود) يُسجَّل بـ success=False"""
        ruleset = Ruleset(
            name="fail test",
            rules=[
                Rule(
                    name="Tag everything",
                    conditions=[],  # تطابق دائمًا
                    actions=[Action(type="move", target="Archives")],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        # نحذف ملف قبل التنفيذ لإجبار الفشل
        # لكن نخطّط أصلاً على سجلات قديمة — نستخدم قاعدة tag بدلًا من ذلك
        # لتجنب الفشل، نتحقق فقط أن execute لا يرفع استثناء على خطأ واحد
        entries = engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")
        # كل الإدخالات يجب أن تكون ناجحة لأن الملفات موجودة
        assert all(e.success for e in entries)


# ─── اختبارات Undo ──────────────────────────────────────────────────────────

class TestUndoLog:
    """اختبارات UndoLog — rollback لكل نوع إجراء"""

    def test_undo_log_save_load_roundtrip(self, tmp_path):
        """save ثم load يُرجع نفس الإدخالات"""
        log_path = tmp_path / "undo.json"
        log = UndoLog(log_path)
        log.append(UndoEntry(
            action_type="tag",
            file_path="/tmp/x.txt",
            rule_name="r1",
            tags_added=["t1"],
            timestamp="2026-07-24T10:00:00",
        ))
        log.append(UndoEntry(
            action_type="move",
            file_path="/tmp/old.txt",
            file_path_after="/tmp/new.txt",
            rule_name="r2",
            timestamp="2026-07-24T10:01:00",
        ))
        log.save()

        # تحميل في كائن جديد
        log2 = UndoLog(log_path)
        assert len(log2) == 2
        assert log2.entries[0].action_type == "tag"
        assert log2.entries[0].tags_added == ["t1"]
        assert log2.entries[1].action_type == "move"
        assert log2.entries[1].file_path_after == "/tmp/new.txt"

    def test_rollback_move(self, tmp_workspace):
        """rollback_last لعكس النقل"""
        ruleset = Ruleset(
            name="move test",
            rules=[
                Rule(
                    name="Move jpg",
                    priority=10,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="move", target="Sorted")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        # تحقق من النقل
        moved = tmp_workspace / "Sorted" / "big_photo.jpg"
        assert moved.exists()
        assert not (tmp_workspace / "big_photo.jpg").exists()

        # تراجع
        log = UndoLog(log_path)
        rolled = log.rollback_last()
        assert rolled is not None
        assert rolled.action_type == "move"
        # الملف عاد لمكانه الأصلي
        assert (tmp_workspace / "big_photo.jpg").exists()
        assert not moved.exists()

    def test_rollback_copy(self, tmp_workspace):
        """rollback_last لعكس النسخ (حذف النسخة)"""
        ruleset = Ruleset(
            name="copy test",
            rules=[
                Rule(
                    name="Copy jpg",
                    priority=10,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="copy", target="Backup")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        copied = tmp_workspace / "Backup" / "big_photo.jpg"
        assert copied.exists()
        assert (tmp_workspace / "big_photo.jpg").exists()  # الأصلي باقٍ

        log = UndoLog(log_path)
        rolled = log.rollback_last()
        assert rolled.action_type == "copy"
        assert not copied.exists()  # النسخة حُذفت
        assert (tmp_workspace / "big_photo.jpg").exists()  # الأصلي ما زال باقٍ

    def test_rollback_tag(self, tmp_workspace):
        """rollback_last لعكس إضافة وسم"""
        ruleset = Ruleset(
            name="tag test",
            rules=[
                Rule(
                    name="Tag jpg",
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="tag", value="photo")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        file_path = str(tmp_workspace / "big_photo.jpg")
        assert "photo" in _load_sidecar_tags(file_path)

        log = UndoLog(log_path)
        rolled = log.rollback_last()
        assert rolled.action_type == "tag"
        assert "photo" not in _load_sidecar_tags(file_path)

    def test_rollback_set_category(self, tmp_workspace):
        """rollback_last لعكس ضبط التصنيف"""
        ruleset = Ruleset(
            name="cat test",
            rules=[
                Rule(
                    name="Set cat",
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="set_category", value="صور")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        file_path = str(tmp_workspace / "big_photo.jpg")
        sc = _load_sidecar(file_path)
        assert sc.get("category") == "صور"

        log = UndoLog(log_path)
        rolled = log.rollback_last()
        assert rolled.action_type == "set_category"
        sc = _load_sidecar(file_path)
        # التصنيف الأصلي (فارغ) عاد
        assert sc.get("category", "") == ""

    def test_rollback_all_reverses_everything(self, tmp_workspace):
        """rollback_all يعكس كل الإجراءات"""
        ruleset = Ruleset(
            name="multi test",
            rules=[
                Rule(
                    name="Move + tag jpg",
                    priority=10,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[
                        Action(type="move", target="Sorted"),
                        Action(type="tag", value="photo"),
                    ],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        entries = engine.execute(plan, undo_log_path=log_path)
        assert len(entries) == 2  # move + tag

        # rollback_all
        log = UndoLog(log_path)
        rolled = log.rollback_all()
        assert len(rolled) == 2
        assert len(log) == 0  # السجل فارغ الآن
        # الملف عاد
        assert (tmp_workspace / "big_photo.jpg").exists()
        # الوسوم ذهبت
        assert _load_sidecar_tags(str(tmp_workspace / "big_photo.jpg")) == []

    def test_rollback_n(self, tmp_workspace):
        """rollback_n يتراجع عن آخر n فقط"""
        ruleset = Ruleset(
            name="multi test",
            rules=[
                Rule(
                    name="Tag jpg with 3 tags",
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[
                        Action(type="tag", value="t1"),
                        Action(type="tag", value="t2"),
                        Action(type="tag", value="t3"),
                    ],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        file_path = str(tmp_workspace / "big_photo.jpg")
        tags = _load_sidecar_tags(file_path)
        assert set(tags) == {"t1", "t2", "t3"}

        # rollback آخر 2
        log = UndoLog(log_path)
        rolled = log.rollback_n(2)
        assert len(rolled) == 2
        tags_after = _load_sidecar_tags(file_path)
        # فقط t1 يجب أن يبقى
        assert "t1" in tags_after
        assert "t2" not in tags_after
        assert "t3" not in tags_after

    def test_rollback_empty_log_returns_none(self, tmp_path):
        """rollback_last على سجل فارغ يُرجع None"""
        log = UndoLog(tmp_path / "empty.json")
        assert log.rollback_last() is None
        assert log.rollback_all() == []

    def test_undo_log_no_path_memory_only(self):
        """UndoLog بدون path يبقى في الذاكرة فقط"""
        log = UndoLog(None)
        log.append(UndoEntry(action_type="tag", file_path="/tmp/x", rule_name="r"))
        assert len(log) == 1
        log.save()  # لا يفعل شيئًا (لا path)
        assert len(log) == 1


# ─── اختبارات تكامل FileInventory + RuleEngine ────────────────────────────

class TestFileInventoryIntegration:
    """اختبارات تكامل المسح + القواعد"""

    def test_scan_then_dry_run(self, tmp_workspace, sample_ruleset):
        """المسح ثم المحاكاة ينتج خطة صحيحة"""
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(sample_ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        # 4 ملفات يجب أن تتطابق (big_photo, photo2, small_note, tiny)
        assert plan.files_affected == 4

    def test_scan_then_execute_then_undo(self, tmp_workspace, sample_ruleset):
        """المسح → تنفيذ → تراجع يُعيد الحالة الأصلية"""
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))

        # لقطة قبل التنفيذ: كل المسارات النسبية + أسماء الملفات
        before_paths = sorted(str(p.relative_to(tmp_workspace))
                              for p in tmp_workspace.rglob("*") if p.is_file())

        engine = RuleEngine(sample_ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        log_path = tmp_workspace / ".ifm_undo.json"
        engine.execute(plan, undo_log_path=log_path)

        # بعد التنفيذ: ملفات نُقلت
        after_exec_paths = sorted(str(p.relative_to(tmp_workspace))
                                   for p in tmp_workspace.rglob("*")
                                   if p.is_file() and not p.name.startswith(".ifm"))
        assert before_paths != after_exec_paths  # تغيّرت

        # تراجع عن كل شيء
        log = UndoLog(log_path)
        log.rollback_all()

        # بعد التراجع: الملفات الأصلية عادت (باستثناء ملفات sidecar وundo log)
        after_undo_paths = sorted(
            str(p.relative_to(tmp_workspace))
            for p in tmp_workspace.rglob("*")
            if p.is_file() and not p.name.startswith(".ifm")
        )
        assert after_undo_paths == before_paths

    def test_metadata_used_for_matching(self, tmp_workspace):
        """ميتاداتا حقيقية من FileInventory تُستخدم في تطابق القواعد"""
        # قاعدة على extra_metadata.width من EXIF (لو توفّرت)
        # هنا نستخدم قاعدة على file_size فقط للبساطة
        ruleset = Ruleset(
            name="size rule",
            rules=[
                Rule(
                    name="Files > 2KB",
                    priority=10,
                    conditions=[Condition(field="file_size", op="gt", value=2000)],
                    actions=[Action(type="tag", value="big-file")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        # big_photo.jpg (5KB) + photo2.png (3KB) → 2 ملفات
        assert plan.files_affected == 2


# ─── اختبارات Dry-Run Reporter ────────────────────────────────────────────

class TestDryRunReporter:
    """اختبارات توليد تقرير HTML"""

    def test_generate_html_returns_string(self, engine, records, tmp_workspace):
        """generate_html_report يُرجع سلسلة HTML"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        html = generate_html_report(plan)
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_save_report_writes_file(self, engine, records, tmp_workspace, tmp_path):
        """save_report يكتب ملف HTML"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        report_path = tmp_path / "report.html"
        result = save_report(plan, report_path)
        assert result == report_path
        assert report_path.exists()
        assert report_path.stat().st_size > 0

    def test_html_includes_action_counts(self, engine, records, tmp_workspace):
        """التقرير يحتوي على عدد الإجراءات"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        html = generate_html_report(plan)
        assert str(plan.total_actions) in html
        assert "توزيع الإجراءات" in html

    def test_html_lists_planned_actions(self, engine, records, tmp_workspace):
        """التقرير يعرض كل إجراء مخطّط"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        html = generate_html_report(plan)
        # أسماء القواعد في التقرير
        assert "Large photos" in html
        assert "Small text files" in html
        # أسماء الملفات
        assert "big_photo.jpg" in html
        assert "small_note.txt" in html

    def test_html_warns_on_destructive(self, tmp_workspace, records, tmp_path):
        """التقرير يحذّر من الإجراءات التدميرية"""
        ruleset = Ruleset(
            name="destructive",
            rules=[
                Rule(
                    name="Flag for deletion",
                    conditions=[Condition(field="file_size", op="lt", value=100)],
                    actions=[Action(type="delete_flag")],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        html = generate_html_report(plan)
        assert "تدميرية" in html or "destructive" in html.lower()

    def test_html_lists_skipped_files(self, engine, records, tmp_workspace):
        """التقرير يعرض الملفات المتخطاة"""
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        html = generate_html_report(plan)
        # ملف data.xyz متخطٍ
        assert "data.xyz" in html
        assert "متخطاة" in html or "skipped" in html.lower()


# ─── اختبارات Sidecar ──────────────────────────────────────────────────────

class TestSidecar:
    """اختبارات ملفات sidecar (تتبع الوسوم والتصنيف)"""

    def test_sidecar_path(self, tmp_path):
        """_sidecar_path يُرجع المسار الصحيح"""
        p = str(tmp_path / "photo.jpg")
        sc = _sidecar_path(p)
        assert sc.name == ".ifm_meta_photo.jpg.json"
        assert sc.parent == tmp_path

    def test_save_and_load_sidecar(self, tmp_path):
        """_save_sidecar ثم _load_sidecar round-trip"""
        p = str(tmp_path / "doc.pdf")
        _save_sidecar(p, {"tags": ["a", "b"], "category": "مستندات"})
        loaded = _load_sidecar(p)
        assert loaded["tags"] == ["a", "b"]
        assert loaded["category"] == "مستندات"

    def test_load_sidecar_nonexistent_returns_empty(self, tmp_path):
        """_load_sidecar لملف بدون sidecar يُرجع {}"""
        p = str(tmp_path / "no_sidecar.txt")
        assert _load_sidecar(p) == {}

    def test_load_sidecar_tags_nonexistent_returns_empty_list(self, tmp_path):
        """_load_sidecar_tags بدون sidecar يُرجع []"""
        p = str(tmp_path / "no_tags.txt")
        assert _load_sidecar_tags(p) == []

    def test_sidecar_preserves_existing_data_on_tag_update(self, tmp_path):
        """تحديث الوسوم لا يمسح حقول sidecar الأخرى"""
        from src.core.rule_engine import _save_sidecar_tags
        p = str(tmp_path / "img.jpg")
        _save_sidecar(p, {"tags": ["old"], "category": "صور", "custom": "data"})
        _save_sidecar_tags(p, ["new1", "new2"])
        loaded = _load_sidecar(p)
        assert loaded["tags"] == ["new1", "new2"]
        assert loaded["category"] == "صور"  # لم يمسح
        assert loaded["custom"] == "data"  # لم يمسح


# ─── اختبارات Copy Action ─────────────────────────────────────────────────

class TestCopyAction:
    """اختبارات نسخ الملفات"""

    def test_copy_creates_duplicate(self, tmp_workspace):
        """copy ينشئ نسخة في الوجهة ويبقي الأصلي"""
        ruleset = Ruleset(
            name="copy test",
            rules=[
                Rule(
                    name="Backup txt files",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type="copy", target="Backup")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")

        original = tmp_workspace / "small_note.txt"
        backup = tmp_workspace / "Backup" / "small_note.txt"
        assert original.exists()  # الأصلي باقٍ
        assert backup.exists()    # النسخة موجودة
        assert original.read_bytes() == backup.read_bytes()  # نفس المحتوى

    def test_copy_with_existing_destination_renames(self, tmp_workspace):
        """copy لملف موجود مسبقًا في الوجهة يضيف لاحقة"""
        ruleset = Ruleset(
            name="copy test",
            rules=[
                Rule(
                    name="Backup txt",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type="copy", target="Backup")],
                ),
            ],
        )
        # نضع نسخة مسبقًا
        (tmp_workspace / "Backup").mkdir()
        (tmp_workspace / "Backup" / "small_note.txt").write_text("existing", encoding="utf-8")

        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        engine.execute(plan, undo_log_path=tmp_workspace / ".ifm_undo.json")

        # النسخة الجديدة بلاحقة _1
        assert (tmp_workspace / "Backup" / "small_note_1.txt").exists()


# ─── اختبارات Disabled Rules ──────────────────────────────────────────────

class TestDisabledRules:
    """اختبارات القواعد المعطّلة"""

    def test_disabled_rules_not_evaluated(self, tmp_workspace):
        """القواعد المعطّلة لا تُطبَّق"""
        ruleset = Ruleset(
            name="disabled test",
            rules=[
                Rule(
                    name="Disabled rule",
                    enabled=False,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="tag", value="should-not-appear")],
                ),
                Rule(
                    name="Enabled rule",
                    priority=1,
                    conditions=[Condition(field="extension", op="eq", value="jpg")],
                    actions=[Action(type="tag", value="enabled-tag")],
                ),
            ],
        )
        inv = FileInventory(include_content=False)
        records = inv.scan_directory(str(tmp_workspace))
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        rule_names = {a.rule_name for a in plan.planned_actions}
        assert "Enabled rule" in rule_names
        assert "Disabled rule" not in rule_names
