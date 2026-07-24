"""اختبارات تكامل: SafeMover + ActionLog + RuleEngine + Watcher

هذا الملف يغطي:
  - SafeMover: نقل/نسخ آمن مع checksum + sidecar + تضارب + rollback
  - ActionLog: تسجيل/استعلام/إحصائيات/تصدير JSON/HTML/CSV
  - تكامل RuleEngine مع SafeMover (use_safe_mover=True)
  - تكامل RuleEngine مع ActionLog
  - تكامل Watcher مع ActionLog
  - تكامل UndoLog مع ActionLog (log_rollback)
  - edge cases: ملف مفقود، وجهة غير موجودة، تضارب أسماء، sidecar مفقود

PR-07 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path

import pytest

from src.core.safe_mover import (
    SafeMover,
    MoveResult,
    CopyResult,
    compute_sha256,
    safe_move_for_rule_engine,
    safe_copy_for_rule_engine,
    _sidecar_path,
    _resolve_collision,
)
from src.core.action_log import (
    ActionLog,
    ActionLogEntry,
    SOURCE_RULE_ENGINE,
    SOURCE_WATCHER,
    SOURCE_MANUAL,
    SOURCE_UNDO_ROLLBACK,
    format_action_log_summary,
)
from src.core.rule_schemas import (
    Action, ActionType, Condition, DryRunPlan, PlannedAction, Rule, Ruleset,
    UndoEntry,
)
from src.core.rule_engine import RuleEngine
from src.core.undo_log import UndoLog
from src.core.file_inventory import FileInventory


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """مجلد عمل مؤقت مع ملفات اختبار"""
    # إنشاء ملفات اختبار
    (tmp_path / "src").mkdir()
    (tmp_path / "dst").mkdir()
    (tmp_path / "src" / "file1.txt").write_text("محتوى ملف 1", encoding="utf-8")
    (tmp_path / "src" / "file2.txt").write_text("محتوى ملف 2", encoding="utf-8")
    (tmp_path / "src" / "binary.bin").write_bytes(bytes(range(256)) * 4)
    # sidecar لملف 1
    sc1 = _sidecar_path(str(tmp_path / "src" / "file1.txt"))
    sc1.write_text(
        json.dumps({"tags": ["important", "work"], "category": "مستندات"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def safe_mover() -> SafeMover:
    """SafeMover افتراضي مع checksum + sidecar"""
    return SafeMover(verify_checksum=True, move_sidecar=True)


@pytest.fixture
def action_log(tmp_path: Path) -> ActionLog:
    """ActionLog مع ملف JSON للسجل"""
    return ActionLog(tmp_path / "action_log.json", max_entries=1000)


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: SafeMover — Basic Move
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverBasicMove:
    """اختبارات النقل الآمن الأساسي"""

    def test_move_basic_success(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف بسيط ناجح"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        original_sha = compute_sha256(src)

        result = safe_mover.move(src, dst)

        assert result.success
        assert not src.exists()  # الملف المصدر اختفى
        assert dst.exists()      # الوجهة موجودة
        assert result.checksum_before == original_sha
        assert result.checksum_after == original_sha
        assert result.checksum_before == result.checksum_after
        assert result.final_path == str(dst)
        assert result.duration_ms > 0

    def test_move_preserves_content(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل يحافظ على المحتوى"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        original_content = src.read_text(encoding="utf-8")

        safe_mover.move(src, dst)

        assert dst.read_text(encoding="utf-8") == original_content

    def test_move_creates_destination_dir(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل ينشئ مجلد الوجهة إن لم يكن موجودًا"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "deep" / "nested" / "path" / "file1.txt"

        result = safe_mover.move(src, dst)

        assert result.success
        assert dst.exists()
        assert dst.parent.exists()

    def test_move_with_sidecar(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل ينقل ملف sidecar مع الملف"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        src_sidecar = _sidecar_path(str(src))

        assert src_sidecar.exists()  # التحقق من وجوده قبل النقل

        result = safe_mover.move(src, dst)

        assert result.success
        assert result.sidecar_moved
        assert not src_sidecar.exists()  # الـ sidecar الأصلي اختفى
        dst_sidecar = _sidecar_path(str(dst))
        assert dst_sidecar.exists()
        # التحقق من المحتوى
        sc_data = json.loads(dst_sidecar.read_text(encoding="utf-8"))
        assert "important" in sc_data["tags"]

    def test_move_without_sidecar(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل لملف بدون sidecar — sidecar_moved=False"""
        src = tmp_workspace / "src" / "file2.txt"  # بدون sidecar
        dst = tmp_workspace / "dst" / "file2.txt"
        src_sidecar = _sidecar_path(str(src))
        assert not src_sidecar.exists()

        result = safe_mover.move(src, dst)

        assert result.success
        assert not result.sidecar_moved

    def test_move_source_not_found(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف غير موجود — فشل مع رسالة واضحة"""
        src = tmp_workspace / "nonexistent.txt"
        dst = tmp_workspace / "dst" / "nonexistent.txt"

        result = safe_mover.move(src, dst)

        assert not result.success
        assert "غير موجود" in result.error
        assert result.duration_ms > 0

    def test_move_returns_move_result(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل يُرجع MoveResult"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        result = safe_mover.move(src, dst)

        assert isinstance(result, MoveResult)
        assert result.source == str(src)
        assert result.destination == str(dst)

    def test_move_idempotent_to_same_path(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل الملف إلى نفس موضعه لا يفشل"""
        src = tmp_workspace / "src" / "file1.txt"
        # نسخ الملف أولاً للوجهة لنحاكي نفس الموضع
        dst = src  # نفس المسار

        result = safe_mover.move(src, dst)

        # لو الوجهة هي نفسها المصدر، يجب أن ينجح (no-op)
        assert result.success
        assert src.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: SafeMover — Basic Copy
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverBasicCopy:
    """اختبارات النسخ الآمن الأساسي"""

    def test_copy_basic_success(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نسخ ملف بسيط ناجح"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        original_sha = compute_sha256(src)

        result = safe_mover.copy(src, dst)

        assert result.success
        assert src.exists()   # المصدر لا يزال موجودًا (نسخ وليس نقل)
        assert dst.exists()   # الوجهة موجودة
        assert result.checksum_before == original_sha
        assert result.checksum_after == original_sha

    def test_copy_preserves_content(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النسخ يحافظ على المحتوى"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        original_content = src.read_text(encoding="utf-8")

        safe_mover.copy(src, dst)

        assert src.read_text(encoding="utf-8") == original_content
        assert dst.read_text(encoding="utf-8") == original_content

    def test_copy_with_sidecar(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النسخ ينسخ sidecar أيضًا"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        result = safe_mover.copy(src, dst)

        assert result.success
        assert result.sidecar_copied
        # sidecar المصدر لا يزال موجودًا (نسخ)
        assert _sidecar_path(str(src)).exists()
        # sidecar الوجهة موجود
        assert _sidecar_path(str(dst)).exists()

    def test_copy_creates_destination_dir(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النسخ ينشئ مجلد الوجهة"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "new_dir" / "file1.txt"

        result = safe_mover.copy(src, dst)

        assert result.success
        assert dst.parent.exists()

    def test_copy_binary_file(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نسخ ملف ثنائي يُحافظ على البايتات"""
        src = tmp_workspace / "src" / "binary.bin"
        dst = tmp_workspace / "dst" / "binary.bin"
        original_bytes = src.read_bytes()

        result = safe_mover.copy(src, dst)

        assert result.success
        assert dst.read_bytes() == original_bytes

    def test_copy_returns_copy_result(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النسخ يُرجع CopyResult"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        result = safe_mover.copy(src, dst)

        assert isinstance(result, CopyResult)

    def test_copy_source_not_found(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نسخ ملف غير موجود"""
        src = tmp_workspace / "nonexistent.txt"
        dst = tmp_workspace / "dst" / "nonexistent.txt"

        result = safe_mover.copy(src, dst)

        assert not result.success
        assert "غير موجود" in result.error


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: SafeMover — Collision Resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverCollision:
    """اختبارات حل تضارب الأسماء"""

    def test_move_collision_adds_suffix(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل لملف موجود في الوجهة — يُضاف _1"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        # إنشاء ملف في الوجهة أولًا
        dst.write_text("existing", encoding="utf-8")

        result = safe_mover.move(src, dst)

        assert result.success
        assert result.renamed_due_to_collision
        # final_path يجب أن يكون file1_1.txt
        assert "file1_1.txt" in result.final_path
        assert Path(result.final_path).exists()
        # الملف الأصلي في الوجهة لا يزال موجودًا
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == "existing"

    def test_move_collision_multiple_suffixes(self, safe_mover: SafeMover, tmp_workspace: Path):
        """تضارب مع _1 و _2 موجودين — يُضاف _2"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("existing", encoding="utf-8")
        (tmp_workspace / "dst" / "file1_1.txt").write_text("first", encoding="utf-8")

        result = safe_mover.move(src, dst)

        assert result.success
        assert "file1_2.txt" in result.final_path

    def test_copy_collision_adds_suffix(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نسخ لملف موجود في الوجهة — يُضاف _1"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("existing", encoding="utf-8")

        result = safe_mover.copy(src, dst)

        assert result.success
        assert result.renamed_due_to_collision
        assert "file1_1.txt" in result.final_path
        # المصدر لا يزال موجودًا
        assert src.exists()

    def test_move_overwrite_true_replaces_destination(
        self, tmp_workspace: Path
    ):
        """نقل مع overwrite=True يستبدل الوجهة"""
        mover = SafeMover(overwrite=True)
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("old content", encoding="utf-8")

        result = mover.move(src, dst)

        assert result.success
        assert not result.renamed_due_to_collision
        assert dst.read_text(encoding="utf-8") == "محتوى ملف 1"

    def test_copy_overwrite_true_replaces_destination(
        self, tmp_workspace: Path
    ):
        """نسخ مع overwrite=True يستبدل الوجهة"""
        mover = SafeMover(overwrite=True)
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("old content", encoding="utf-8")

        result = mover.copy(src, dst)

        assert result.success
        assert dst.read_text(encoding="utf-8") == "محتوى ملف 1"
        # المصدر لا يزال موجودًا
        assert src.exists()

    def test_resolve_collision_no_conflict(self, tmp_workspace: Path):
        """_resolve_collision بدون تضارب"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "newfile.txt"

        final, renamed = _resolve_collision(dst, src)

        assert final == dst
        assert not renamed

    def test_resolve_collision_with_conflict(self, tmp_workspace: Path):
        """_resolve_collision مع تضارب"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("existing", encoding="utf-8")

        final, renamed = _resolve_collision(dst, src)

        assert final != dst
        assert renamed
        assert "file1_1.txt" in final.name


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: SafeMover — Checksum Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverChecksum:
    """اختبارات التحقّق من checksum"""

    def test_compute_sha256_existing_file(self, tmp_workspace: Path):
        """compute_sha256 لملف موجود"""
        p = tmp_workspace / "src" / "file1.txt"
        h = compute_sha256(p)
        assert len(h) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_sha256_missing_file(self, tmp_workspace: Path):
        """compute_sha256 لملف غير موجود يُرجع سلسلة فارغة"""
        p = tmp_workspace / "nonexistent.txt"
        h = compute_sha256(p)
        assert h == ""

    def test_compute_sha256_consistent(self, tmp_workspace: Path):
        """compute_sha256 يُرجع نفس القيمة لنفس المحتوى"""
        p1 = tmp_workspace / "src" / "file1.txt"
        p2 = tmp_workspace / "src" / "file1.txt"  # نفس الملف
        assert compute_sha256(p1) == compute_sha256(p2)

    def test_compute_sha256_different_for_different_content(self, tmp_workspace: Path):
        """compute_sha256 يُرجع قيمًا مختلفة لمحتوى مختلف"""
        p1 = tmp_workspace / "src" / "file1.txt"
        p2 = tmp_workspace / "src" / "file2.txt"
        assert compute_sha256(p1) != compute_sha256(p2)

    def test_move_no_checksum_when_disabled(self, tmp_workspace: Path):
        """النقل مع verify_checksum=False لا يحسب checksum"""
        mover = SafeMover(verify_checksum=False)
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        result = mover.move(src, dst)

        assert result.success
        assert result.checksum_before == ""
        assert result.checksum_after == ""

    def test_move_checksums_match(self, safe_mover: SafeMover, tmp_workspace: Path):
        """النقل ينتج checksums متطابقة"""
        src = tmp_workspace / "src" / "binary.bin"
        dst = tmp_workspace / "dst" / "binary.bin"

        result = safe_mover.move(src, dst)

        assert result.success
        assert result.checksum_before == result.checksum_after
        assert len(result.checksum_before) == 64


# ─────────────────────────────────────────────────────────────────────────────
# Part 5: SafeMover — Batch Operations
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverBatch:
    """اختبارات العمليات الدفعية"""

    def test_move_many_all_success(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل عدة ملفات دفعة واحدة"""
        pairs = [
            (tmp_workspace / "src" / "file1.txt", tmp_workspace / "dst" / "file1.txt"),
            (tmp_workspace / "src" / "file2.txt", tmp_workspace / "dst" / "file2.txt"),
        ]

        results = safe_mover.move_many(pairs)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert not (tmp_workspace / "src" / "file1.txt").exists()
        assert not (tmp_workspace / "src" / "file2.txt").exists()

    def test_copy_many_all_success(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نسخ عدة ملفات دفعة واحدة"""
        pairs = [
            (tmp_workspace / "src" / "file1.txt", tmp_workspace / "dst" / "file1.txt"),
            (tmp_workspace / "src" / "file2.txt", tmp_workspace / "dst" / "file2.txt"),
        ]

        results = safe_mover.copy_many(pairs)

        assert len(results) == 2
        assert all(r.success for r in results)
        # المصادر لا تزال موجودة
        assert (tmp_workspace / "src" / "file1.txt").exists()

    def test_move_many_with_partial_failure(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل دفعي مع فشل جزئي — لا يتوقف"""
        pairs = [
            (tmp_workspace / "src" / "file1.txt", tmp_workspace / "dst" / "file1.txt"),
            (tmp_workspace / "nonexistent.txt", tmp_workspace / "dst" / "x.txt"),
            (tmp_workspace / "src" / "file2.txt", tmp_workspace / "dst" / "file2.txt"),
        ]

        results = safe_mover.move_many(pairs)

        assert len(results) == 3
        assert results[0].success
        assert not results[1].success
        assert results[2].success

    def test_move_many_stop_on_error(self, safe_mover: SafeMover, tmp_workspace: Path):
        """move_many مع stop_on_error=True"""
        pairs = [
            (tmp_workspace / "src" / "file1.txt", tmp_workspace / "dst" / "file1.txt"),
            (tmp_workspace / "nonexistent.txt", tmp_workspace / "dst" / "x.txt"),
            (tmp_workspace / "src" / "file2.txt", tmp_workspace / "dst" / "file2.txt"),
        ]

        results = safe_mover.move_many(pairs, stop_on_error=True)

        assert len(results) == 2  # توقف بعد الفشل
        assert results[0].success
        assert not results[1].success


# ─────────────────────────────────────────────────────────────────────────────
# Part 6: SafeMover — Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMoverConvenience:
    """اختبارات الدوال المساعدة لواجهة RuleEngine"""

    def test_safe_move_for_rule_engine_success(self, tmp_workspace: Path):
        """safe_move_for_rule_engine ناجح"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        success, final, err = safe_move_for_rule_engine(src, dst)

        assert success
        assert final == str(dst)
        assert err == ""
        assert not src.exists()
        assert dst.exists()

    def test_safe_move_for_rule_engine_failure(self, tmp_workspace: Path):
        """safe_move_for_rule_engine فاشل"""
        src = tmp_workspace / "nonexistent.txt"
        dst = tmp_workspace / "dst" / "x.txt"

        success, final, err = safe_move_for_rule_engine(src, dst)

        assert not success
        assert "غير موجود" in err

    def test_safe_copy_for_rule_engine_success(self, tmp_workspace: Path):
        """safe_copy_for_rule_engine ناجح"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"

        success, final, err = safe_copy_for_rule_engine(src, dst)

        assert success
        assert src.exists()  # المصدر لا يزال موجودًا
        assert dst.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Part 7: ActionLog — Basic Logging
# ─────────────────────────────────────────────────────────────────────────────

class TestActionLogBasic:
    """اختبارات التسجيل الأساسي في ActionLog"""

    def test_log_basic_entry(self, action_log: ActionLog):
        """تسجيل إدخال أساسي"""
        entry = action_log.log(
            action_type="move",
            file_path="/test/file.txt",
            file_path_after="/test/dst/file.txt",
            rule_name="test-rule",
            success=True,
        )

        assert entry.entry_id == 1
        assert entry.action_type == "move"
        assert entry.success
        assert len(action_log) == 1

    def test_log_assigns_sequential_ids(self, action_log: ActionLog):
        """الإدخالات تأخذ IDs متسلسلة"""
        for i in range(5):
            action_log.log(action_type="tag", file_path=f"/test/{i}.txt")

        entries = action_log.list_entries(reverse=False)
        assert [e.entry_id for e in entries] == [1, 2, 3, 4, 5]

    def test_log_with_all_fields(self, action_log: ActionLog):
        """تسجيل إدخال بكل الحقول"""
        entry = action_log.log(
            action_type="move",
            file_path="/src.txt",
            file_path_after="/dst.txt",
            rule_name="my-rule",
            success=True,
            tags_added=["new-tag"],
            tags_removed=["old-tag"],
            old_category="صور",
            new_category="مستندات",
            checksum_before="abc123",
            checksum_after="abc123",
            source=SOURCE_RULE_ENGINE,
            duration_ms=42.5,
        )

        assert entry.tags_added == ["new-tag"]
        assert entry.tags_removed == ["old-tag"]
        assert entry.old_category == "صور"
        assert entry.new_category == "مستندات"
        assert entry.duration_ms == 42.5

    def test_log_from_undo_entry(self, action_log: ActionLog):
        """تسجيل من UndoEntry"""
        undo = UndoEntry(
            action_type="move",
            file_path="/src.txt",
            file_path_after="/dst.txt",
            rule_name="r1",
            timestamp="2026-07-25T10:00:00",
            success=True,
        )

        entry = action_log.log_from_undo_entry(undo, source=SOURCE_RULE_ENGINE)

        assert entry.action_type == "move"
        assert entry.rule_name == "r1"
        assert entry.source == SOURCE_RULE_ENGINE

    def test_log_from_move_result(self, action_log: ActionLog, tmp_workspace: Path):
        """تسجيل من MoveResult"""
        mover = SafeMover()
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        result = mover.move(src, dst)

        entry = action_log.log_from_move_result(result, rule_name="test")

        assert entry.action_type == "move"
        assert entry.success
        assert entry.checksum_before == result.checksum_before
        assert entry.duration_ms > 0

    def test_log_from_copy_result(self, action_log: ActionLog, tmp_workspace: Path):
        """تسجيل من CopyResult"""
        mover = SafeMover()
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        result = mover.copy(src, dst)

        entry = action_log.log_from_copy_result(result, rule_name="test")

        assert entry.action_type == "copy"
        assert entry.success

    def test_log_rollback(self, action_log: ActionLog):
        """تسجيل عملية تراجع"""
        undo = UndoEntry(
            action_type="move",
            file_path="/src.txt",
            file_path_after="/dst.txt",
            rule_name="r1",
            success=True,
        )
        entry = action_log.log_rollback(undo, success=True)

        assert entry.action_type == "undo:move"
        assert entry.source == SOURCE_UNDO_ROLLBACK
        assert entry.success


# ─────────────────────────────────────────────────────────────────────────────
# Part 8: ActionLog — Querying & Stats
# ─────────────────────────────────────────────────────────────────────────────

class TestActionLogQuery:
    """اختبارات الاستعلام والإحصائيات"""

    def test_list_entries_no_filter(self, action_log: ActionLog):
        """list_entries بدون فلتر"""
        for i in range(5):
            action_log.log(action_type="move", file_path=f"/test/{i}.txt")

        entries = action_log.list_entries()

        assert len(entries) == 5

    def test_list_entries_reverse(self, action_log: ActionLog):
        """list_entries مع reverse=True (الأحدث أولًا)"""
        for i in range(3):
            action_log.log(action_type="move", file_path=f"/test/{i}.txt")

        entries = action_log.list_entries(reverse=True)

        assert entries[0].entry_id == 3  # الأحدث أولًا
        assert entries[2].entry_id == 1

    def test_list_entries_filter_action_type(self, action_log: ActionLog):
        """list_entries فلتر حسب نوع الإجراء"""
        action_log.log(action_type="move", file_path="/a.txt")
        action_log.log(action_type="tag", file_path="/b.txt")
        action_log.log(action_type="move", file_path="/c.txt")

        moves = action_log.list_entries(action_type="move")

        assert len(moves) == 2
        assert all(e.action_type == "move" for e in moves)

    def test_list_entries_filter_success(self, action_log: ActionLog):
        """list_entries فلتر حسب النجاح/الفشل"""
        action_log.log(action_type="move", file_path="/a.txt", success=True)
        action_log.log(action_type="move", file_path="/b.txt", success=False)

        failures = action_log.list_entries(success=False)

        assert len(failures) == 1
        assert not failures[0].success

    def test_list_entries_filter_source(self, action_log: ActionLog):
        """list_entries فلتر حسب المصدر"""
        action_log.log(action_type="move", file_path="/a.txt", source=SOURCE_RULE_ENGINE)
        action_log.log(action_type="move", file_path="/b.txt", source=SOURCE_WATCHER)

        watcher_entries = action_log.list_entries(source=SOURCE_WATCHER)

        assert len(watcher_entries) == 1
        assert watcher_entries[0].source == SOURCE_WATCHER

    def test_list_entries_with_limit(self, action_log: ActionLog):
        """list_entries مع limit"""
        for i in range(10):
            action_log.log(action_type="move", file_path=f"/test/{i}.txt")

        entries = action_log.list_entries(limit=3)

        assert len(entries) == 3

    def test_stats_empty_log(self, action_log: ActionLog):
        """stats لسجل فارغ"""
        stats = action_log.stats()

        assert stats["total"] == 0
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0
        assert stats["success_rate"] == 0.0

    def test_stats_with_entries(self, action_log: ActionLog):
        """stats مع إدخالات"""
        action_log.log(action_type="move", file_path="/a.txt", success=True)
        action_log.log(action_type="move", file_path="/b.txt", success=True)
        action_log.log(action_type="tag", file_path="/c.txt", success=False)

        stats = action_log.stats()

        assert stats["total"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == pytest.approx(66.67, abs=0.1)
        assert stats["by_action_type"]["move"] == 2
        assert stats["by_action_type"]["tag"] == 1

    def test_stats_by_source(self, action_log: ActionLog):
        """stats تُصنّف حسب المصدر"""
        action_log.log(action_type="move", file_path="/a.txt", source=SOURCE_RULE_ENGINE)
        action_log.log(action_type="move", file_path="/b.txt", source=SOURCE_WATCHER)
        action_log.log(action_type="move", file_path="/c.txt", source=SOURCE_RULE_ENGINE)

        stats = action_log.stats()

        assert stats["by_source"][SOURCE_RULE_ENGINE] == 2
        assert stats["by_source"][SOURCE_WATCHER] == 1

    def test_get_entry_by_id(self, action_log: ActionLog):
        """get_entry بمعرّف محدد"""
        action_log.log(action_type="move", file_path="/a.txt")
        e2 = action_log.log(action_type="tag", file_path="/b.txt")

        found = action_log.get_entry(e2.entry_id)
        assert found is not None
        assert found.action_type == "tag"

    def test_get_entry_not_found(self, action_log: ActionLog):
        """get_entry بمعرّف غير موجود"""
        assert action_log.get_entry(999) is None


# ─────────────────────────────────────────────────────────────────────────────
# Part 9: ActionLog — FIFO + Persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestActionLogPersistence:
    """اختبارات الحد الأقصى والحفظ/التحميل"""

    def test_max_entries_fifo(self, tmp_path: Path):
        """ActionLog يحترم max_entries (FIFO)"""
        log = ActionLog(tmp_path / "log.json", max_entries=10)
        for i in range(15):
            log.log(action_type="move", file_path=f"/test/{i}.txt")

        # يجب أن يكون العدد <= max_entries
        assert len(log) <= 10
        # أحدث الإدخالات محفوظة
        entries = log.list_entries(reverse=False)
        # entry_id الأولى يجب أن تكون > 1 (تم حذف الإدخالات القديمة)
        assert entries[0].entry_id > 1

    def test_save_and_load(self, tmp_path: Path):
        """save ثم load"""
        log_path = tmp_path / "log.json"
        log1 = ActionLog(log_path)
        log1.log(action_type="move", file_path="/a.txt")
        log1.log(action_type="tag", file_path="/b.txt")
        log1.save()

        # تحميل في نسخة جديدة
        log2 = ActionLog(log_path)

        assert len(log2) == 2
        entries = log2.list_entries(reverse=False)
        assert entries[0].action_type == "move"
        assert entries[1].action_type == "tag"
        # next_id مستمر
        log2.log(action_type="move", file_path="/c.txt")
        assert log2.list_entries(reverse=False)[-1].entry_id == 3

    def test_clear(self, action_log: ActionLog):
        """clear يفرّغ السجل"""
        action_log.log(action_type="move", file_path="/a.txt")
        action_log.log(action_type="tag", file_path="/b.txt")

        action_log.clear()

        assert len(action_log) == 0

    def test_no_path_in_memory_only(self):
        """ActionLog بدون path يعمل في الذاكرة فقط"""
        log = ActionLog()
        log.log(action_type="move", file_path="/a.txt")
        # save() لا تفعل شيئًا
        log.save()
        assert len(log) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Part 10: ActionLog — Export
# ─────────────────────────────────────────────────────────────────────────────

class TestActionLogExport:
    """اختبارات التصدير JSON/HTML/CSV"""

    def test_export_json(self, action_log: ActionLog, tmp_path: Path):
        """تصدير JSON"""
        action_log.log(action_type="move", file_path="/a.txt", rule_name="r1")
        action_log.log(action_type="tag", file_path="/b.txt", rule_name="r2")

        out_path = tmp_path / "export.json"
        result_path = action_log.export_json(out_path)

        assert Path(result_path) == out_path
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert len(data["entries"]) == 2
        assert "stats" in data

    def test_export_html(self, action_log: ActionLog, tmp_path: Path):
        """تصدير HTML"""
        action_log.log(action_type="move", file_path="/a.txt", rule_name="r1")
        action_log.log(action_type="tag", file_path="/b.txt", rule_name="r2", success=False)

        out_path = tmp_path / "export.html"
        result_path = action_log.export_html(out_path)

        assert Path(result_path) == out_path
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "move" in content
        assert "tag" in content
        assert "ملخص الإحصائيات" in content  # عنوان عربي

    def test_export_html_empty_log(self, action_log: ActionLog, tmp_path: Path):
        """تصدير HTML لسجل فارغ"""
        out_path = tmp_path / "empty.html"
        result_path = action_log.export_html(out_path)

        assert Path(result_path) == out_path
        content = out_path.read_text(encoding="utf-8")
        assert "لا توجد إجراءات" in content

    def test_export_html_only_failures(self, action_log: ActionLog, tmp_path: Path):
        """تصدير HTML للإجراءات الفاشلة فقط"""
        action_log.log(action_type="move", file_path="/a.txt", success=True)
        action_log.log(action_type="move", file_path="/b.txt", success=False)

        out_path = tmp_path / "failures.html"
        action_log.export_html(out_path, only_failures=True)

        content = out_path.read_text(encoding="utf-8")
        # يجب أن يحتوي على الإجراء الفاشل فقط
        # ملاحظة: HTML يعرض اسم الملف فقط (Path.name)، ليس المسار الكامل
        assert "b.txt" in content
        assert "a.txt" not in content

    def test_export_csv(self, action_log: ActionLog, tmp_path: Path):
        """تصدير CSV"""
        action_log.log(action_type="move", file_path="/a.txt", rule_name="r1")
        action_log.log(action_type="tag", file_path="/b.txt", rule_name="r2")

        out_path = tmp_path / "export.csv"
        result_path = action_log.export_csv(out_path)

        assert Path(result_path) == out_path
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "entry_id" in content  # header
        assert "move" in content
        assert "tag" in content


# ─────────────────────────────────────────────────────────────────────────────
# Part 11: ActionLogEntry — Helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestActionLogEntry:
    """اختبارات ActionLogEntry helpers"""

    def test_to_dict_and_from_dict(self):
        """serialization صحيح"""
        e = ActionLogEntry(
            entry_id=1,
            action_type="move",
            file_path="/a.txt",
            rule_name="r1",
            success=True,
        )
        d = e.to_dict()
        e2 = ActionLogEntry.from_dict(d)
        assert e2.action_type == "move"
        assert e2.entry_id == 1

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict يتجاهل المفاتيح غير المعروفة"""
        d = {
            "action_type": "move",
            "file_path": "/a.txt",
            "unknown_key": "value",
        }
        e = ActionLogEntry.from_dict(d)
        assert e.action_type == "move"

    def test_file_name(self):
        """file_name يستخرج الاسم"""
        e = ActionLogEntry(file_path="/path/to/file.txt")
        assert e.file_name() == "file.txt"

    def test_file_name_empty(self):
        """file_name لملف فارغ"""
        e = ActionLogEntry(file_path="")
        assert e.file_name() == ""

    def test_status_icon(self):
        """status_icon"""
        ok = ActionLogEntry(success=True)
        fail = ActionLogEntry(success=False)
        assert ok.status_icon() == "✓"
        assert fail.status_icon() == "✗"

    def test_is_destructive(self):
        """is_destructive"""
        move = ActionLogEntry(action_type="move")
        tag = ActionLogEntry(action_type="tag")
        delete = ActionLogEntry(action_type="delete_flag")
        assert move.is_destructive()
        assert delete.is_destructive()
        assert not tag.is_destructive()


# ─────────────────────────────────────────────────────────────────────────────
# Part 12: RuleEngine + SafeMover Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestRuleEngineSafeMoverIntegration:
    """اختبارات تكامل RuleEngine مع SafeMover"""

    def _build_ruleset(self) -> Ruleset:
        """قواعد اختبار: نقل ملفات txt إلى Documents"""
        rule = Rule(
            name="move-txt-to-documents",
            conditions=[
                Condition(field="extension", op="eq", value="txt"),
            ],
            actions=[
                Action(type="move", target="Documents"),
            ],
            priority=10,
        )
        return Ruleset(name="test-ruleset", rules=[rule])

    def test_execute_uses_safe_mover_by_default(self, tmp_workspace: Path):
        """execute يستخدم SafeMover افتراضيًا"""
        ruleset = self._build_ruleset()
        engine = RuleEngine(ruleset)
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        entries = engine.execute(plan, undo_log_path=str(tmp_workspace / "undo.json"))

        # 2 ملفات txt في src (file1.txt, file2.txt) — binary.bin لا يطابق
        assert len(entries) == 2
        assert all(e.success for e in entries)
        # التحقق من النقل
        assert not (tmp_workspace / "src" / "file1.txt").exists()
        assert (tmp_workspace / "Documents" / "file1.txt").exists()

    def test_execute_with_action_log(self, tmp_workspace: Path):
        """execute مع action_log يُسجّل كل إجراء"""
        ruleset = self._build_ruleset()
        engine = RuleEngine(ruleset)
        action_log = ActionLog(tmp_workspace / "action_log.json")
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        entries = engine.execute(
            plan,
            undo_log_path=str(tmp_workspace / "undo.json"),
            action_log=action_log,
        )

        assert len(entries) >= 2
        # action_log يجب أن يحتوي على نفس عدد الإجراءات الناجحة
        assert len(action_log) == len(entries)
        # الإدخالات مصدرها rule_engine
        for entry in action_log:
            assert entry.source == SOURCE_RULE_ENGINE

    def test_execute_with_action_log_persists(self, tmp_workspace: Path):
        """execute مع action_log.path يحفظ السجل تلقائيًا"""
        ruleset = self._build_ruleset()
        engine = RuleEngine(ruleset)
        log_path = tmp_workspace / "action_log.json"
        action_log = ActionLog(log_path)
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        engine.execute(
            plan,
            undo_log_path=str(tmp_workspace / "undo.json"),
            action_log=action_log,
        )

        # الملف يجب أن يكون موجودًا بعد execute
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data["entries"]) >= 2

    def test_execute_use_safe_mover_false_uses_legacy(self, tmp_workspace: Path):
        """execute مع use_safe_mover=False يستخدم shutil مباشرة"""
        ruleset = self._build_ruleset()
        engine = RuleEngine(ruleset)
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        entries = engine.execute(
            plan,
            undo_log_path=str(tmp_workspace / "undo.json"),
            use_safe_mover=False,
        )

        assert all(e.success for e in entries)
        assert (tmp_workspace / "Documents" / "file1.txt").exists()

    def test_execute_move_failure_logged_in_action_log(self, tmp_workspace: Path):
        """execute مع فشل نقل يُسجّل في action_log"""
        # قاعدة تحاول نقل ملف محذوف
        rule = Rule(
            name="move-missing",
            conditions=[Condition(field="extension", op="eq", value="txt")],
            actions=[Action(type="move", target="Documents")],
        )
        ruleset = Ruleset(name="test", rules=[rule])
        engine = RuleEngine(ruleset)

        # إنشاء planned action لملف غير موجود
        plan = DryRunPlan(
            ruleset_name="test",
            base_dir=str(tmp_workspace),
            planned_actions=[
                PlannedAction(
                    rule_name="move-missing",
                    file_path=str(tmp_workspace / "nonexistent.txt"),
                    file_name="nonexistent.txt",
                    action=Action(type="move", target="Documents"),
                    target_path=str(tmp_workspace / "Documents" / "nonexistent.txt"),
                ),
            ],
        )
        action_log = ActionLog()
        entries = engine.execute(plan, action_log=action_log)

        # يجب أن يكون هناك إدخال واحد فاشل
        assert len(entries) == 1
        assert not entries[0].success
        # action_log يحتوي على الفشل
        assert len(action_log) == 1
        assert not action_log.list_entries()[0].success

    def test_move_with_sidecar_via_safe_mover(self, tmp_workspace: Path):
        """النقل عبر SafeMover يحترم sidecar"""
        ruleset = self._build_ruleset()
        engine = RuleEngine(ruleset)
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        engine.execute(plan, undo_log_path=str(tmp_workspace / "undo.json"))

        # التحقق من نقل sidecar لـ file1.txt (كان له sidecar)
        dst = tmp_workspace / "Documents" / "file1.txt"
        dst_sidecar = _sidecar_path(str(dst))
        assert dst_sidecar.exists()
        sc_data = json.loads(dst_sidecar.read_text(encoding="utf-8"))
        assert "important" in sc_data["tags"]


# ─────────────────────────────────────────────────────────────────────────────
# Part 13: UndoLog + ActionLog Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestUndoLogActionLogIntegration:
    """اختبارات تكامل UndoLog مع ActionLog"""

    def test_log_rollback_after_undo(self, tmp_workspace: Path):
        """تسجيل rollback بعد UndoLog.rollback_last()"""
        # تنفيذ نقل
        ruleset = Ruleset(
            name="test",
            rules=[
                Rule(
                    name="move-rule",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type="move", target="dst")],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        action_log = ActionLog(tmp_workspace / "action.json")
        undo_log = UndoLog(tmp_workspace / "undo.json")
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        engine.execute(plan, action_log=action_log, undo_log_path=str(tmp_workspace / "undo.json"))

        # الآن undo_log محفوظ على القرص — نحمّله ونتراجع
        undo_log2 = UndoLog(tmp_workspace / "undo.json")
        assert len(undo_log2) > 0
        rolled_back = undo_log2.rollback_last()
        assert rolled_back is not None

        # تسجيل التراجع في action_log
        action_log.log_rollback(rolled_back, success=True)

        # التحقق من تسجيل undo:move في السجل
        undo_entries = action_log.list_entries(source=SOURCE_UNDO_ROLLBACK)
        assert len(undo_entries) == 1
        assert undo_entries[0].action_type.startswith("undo:")

    def test_log_rollback_failure(self, action_log: ActionLog):
        """تسجيل rollback فاشل"""
        undo = UndoEntry(action_type="move", file_path="/a.txt", file_path_after="/b.txt")
        action_log.log_rollback(undo, success=False, error_message="file not found")

        entries = action_log.list_entries(source=SOURCE_UNDO_ROLLBACK)
        assert len(entries) == 1
        assert not entries[0].success
        assert "file not found" in entries[0].error_message


# ─────────────────────────────────────────────────────────────────────────────
# Part 14: Watcher + ActionLog Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestWatcherActionLogIntegration:
    """اختبارات تكامل Watcher مع ActionLog"""

    def test_watcher_logs_to_action_log(self, tmp_path: Path):
        """Watcher يسجّل الدفعات في ActionLog"""
        from src.core.watcher import FileWatcher, WatcherConfig

        # إعداد قواعد
        ruleset = Ruleset(
            name="test",
            rules=[
                Rule(
                    name="tag-txt",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type="tag", value="auto-tagged")],
                ),
            ],
        )
        action_log = ActionLog()
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "output"

        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            ruleset=ruleset,
            base_dir=str(tmp_path),
            output_dir=str(out_dir),
            action_log=action_log,
            debounce_seconds=0.3,
            batch_interval=0.5,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            # إنشاء ملف جديد
            (watch_dir / "test1.txt").write_text("test", encoding="utf-8")
            # انتظار معالجة الدفعة
            import time
            time.sleep(2.0)
            # flush يدوي لو لزم
            watcher.flush_now()
            time.sleep(0.5)
        finally:
            watcher.stop(timeout=2.0)

        # ActionLog يجب أن يحتوي على إدخالات من watcher
        watcher_entries = action_log.list_entries(source=SOURCE_WATCHER)
        assert len(watcher_entries) > 0
        assert all(e.source == SOURCE_WATCHER for e in watcher_entries)

    def test_watcher_without_action_log_works(self, tmp_path: Path):
        """Watcher بدون action_log يعمل كالسابق"""
        from src.core.watcher import FileWatcher, WatcherConfig

        ruleset = Ruleset(
            name="test",
            rules=[
                Rule(
                    name="tag-txt",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[Action(type="tag", value="auto")],
                ),
            ],
        )
        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()
        out_dir = tmp_path / "output"

        config = WatcherConfig(
            watch_paths=[str(watch_dir)],
            ruleset=ruleset,
            base_dir=str(tmp_path),
            output_dir=str(out_dir),
            debounce_seconds=0.3,
            batch_interval=0.5,
        )
        watcher = FileWatcher(config)
        watcher.start()
        try:
            (watch_dir / "test.txt").write_text("x", encoding="utf-8")
            import time
            time.sleep(1.5)
            watcher.flush_now()
            time.sleep(0.3)
        finally:
            watcher.stop(timeout=2.0)

        # التحقق من إنشاء تقارير
        history = watcher.get_history()
        assert len(history) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Part 15: ActionLog — Format Summary
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatSummary:
    """اختبارات format_action_log_summary"""

    def test_summary_empty_log(self):
        """ملخص لسجل فارغ"""
        log = ActionLog()
        summary = format_action_log_summary(log)
        assert "فارغ" in summary

    def test_summary_with_entries(self):
        """ملخص لسجل مع إدخالات"""
        log = ActionLog()
        log.log(action_type="move", file_path="/a.txt", rule_name="r1")
        log.log(action_type="tag", file_path="/b.txt", rule_name="r2", success=False)

        summary = format_action_log_summary(log)

        assert "2" in summary  # إجمالي
        assert "1" in summary  # فاشل
        assert "move" in summary
        assert "tag" in summary

    def test_summary_with_limit(self):
        """ملخص مع limit"""
        log = ActionLog()
        for i in range(10):
            log.log(action_type="move", file_path=f"/test/{i}.txt")

        summary = format_action_log_summary(log, limit=3)

        assert "10" in summary  # الإجمالي
        assert "و7 إجراء آخر" in summary  # الـ 7 المتبقية


# ─────────────────────────────────────────────────────────────────────────────
# Part 16: Edge Cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """اختبارات الحالات الحدية"""

    def test_move_empty_file(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف فارغ"""
        src = tmp_workspace / "src" / "empty.txt"
        src.write_text("", encoding="utf-8")
        dst = tmp_workspace / "dst" / "empty.txt"

        result = safe_mover.move(src, dst)

        assert result.success
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == ""
        # SHA-256 لملف فارغ معروف
        assert result.checksum_after == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_copy_to_same_directory_different_name(
        self, safe_mover: SafeMover, tmp_workspace: Path
    ):
        """نسخ في نفس المجلد باسم مختلف"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "src" / "file1_copy.txt"

        result = safe_mover.copy(src, dst)

        assert result.success
        assert src.exists()
        assert dst.exists()

    def test_move_to_same_path_idempotent(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف إلى نفس موضعه"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = src  # نفس المسار

        result = safe_mover.move(src, dst)

        # يجب أن ينجح (no-op) — لا تضارب مع نفسه
        assert result.success

    def test_move_unicode_filename(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف باسم unicode"""
        src = tmp_workspace / "src" / "ملف.txt"
        src.write_text("محتوى عربي", encoding="utf-8")
        dst = tmp_workspace / "dst" / "ملف.txt"

        result = safe_mover.move(src, dst)

        assert result.success
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == "محتوى عربي"

    def test_move_large_file(self, safe_mover: SafeMover, tmp_workspace: Path):
        """نقل ملف كبير نسبيًا"""
        src = tmp_workspace / "src" / "large.bin"
        # 1 MB
        src.write_bytes(os.urandom(1024 * 1024))
        dst = tmp_workspace / "dst" / "large.bin"
        original_sha = compute_sha256(src)

        result = safe_mover.move(src, dst)

        assert result.success
        assert result.checksum_before == original_sha
        assert result.checksum_after == original_sha

    def test_action_log_thread_safety(self, action_log: ActionLog):
        """ActionLog thread-safe"""
        results = []
        errors = []

        def worker(tid: int):
            try:
                for i in range(50):
                    action_log.log(
                        action_type="move",
                        file_path=f"/test/{tid}_{i}.txt",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 4 threads × 50 = 200
        assert len(action_log) == 200
        # IDs فريدة
        ids = [e.entry_id for e in action_log]
        assert len(set(ids)) == 200

    def test_safe_mover_no_overwrite_with_existing_destination(
        self, safe_mover: SafeMover, tmp_workspace: Path
    ):
        """نقل بدون overwrite لوجهة موجودة — يحل التضارب"""
        src = tmp_workspace / "src" / "file1.txt"
        dst = tmp_workspace / "dst" / "file1.txt"
        dst.write_text("existing content", encoding="utf-8")

        result = safe_mover.move(src, dst)

        assert result.success
        assert result.renamed_due_to_collision
        # المحتوى الأصلي في الوجهة محفوظ
        assert dst.read_text(encoding="utf-8") == "existing content"
        # الملف الجديد له اسم مختلف
        assert Path(result.final_path).read_text(encoding="utf-8") == "محتوى ملف 1"


# ─────────────────────────────────────────────────────────────────────────────
# Part 17: End-to-End Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestEndToEnd:
    """اختبارات شاملة من البداية للنهاية"""

    def test_full_pipeline_move_with_action_log_and_undo(
        self, tmp_workspace: Path
    ):
        """خط أنابيب كامل: مسح → قواعد → تنفيذ (SafeMover) → سجل → تراجع"""
        # إعداد
        ruleset = Ruleset(
            name="organize-documents",
            rules=[
                Rule(
                    name="move-txt-to-documents",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[
                        Action(type="move", target="Documents"),
                        Action(type="tag", value="organized"),
                    ],
                    priority=10,
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        action_log = ActionLog(tmp_workspace / "action_log.json")
        undo_log_path = tmp_workspace / "undo.json"
        inventory = FileInventory()

        # مسح
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))

        # dry-run
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))
        assert plan.total_actions > 0

        # تنفيذ
        entries = engine.execute(
            plan,
            undo_log_path=str(undo_log_path),
            action_log=action_log,
        )

        # التحقق
        assert all(e.success for e in entries)
        assert len(action_log) == len(entries)

        # تصدير HTML
        html_path = action_log.export_html(tmp_workspace / "report.html")
        assert Path(html_path).exists()

        # تراجع عن آخر إجراء
        undo_log = UndoLog(undo_log_path)
        rolled_back = undo_log.rollback_last()
        assert rolled_back is not None
        action_log.log_rollback(rolled_back, success=True)

        # التحقق من وجود إدخال undo في السجل
        undo_entries = action_log.list_entries(source=SOURCE_UNDO_ROLLBACK)
        assert len(undo_entries) == 1

    def test_action_log_stats_after_mixed_operations(
        self, tmp_workspace: Path
    ):
        """إحصائيات ActionLog بعد عمليات متنوعة"""
        ruleset = Ruleset(
            name="mixed",
            rules=[
                Rule(
                    name="move-txt",
                    conditions=[Condition(field="extension", op="eq", value="txt")],
                    actions=[
                        Action(type="move", target="Documents"),
                        Action(type="tag", value="txt-file"),
                    ],
                ),
                Rule(
                    name="move-bin",
                    conditions=[Condition(field="extension", op="eq", value="bin")],
                    actions=[
                        Action(type="copy", target="Archive"),
                    ],
                ),
            ],
        )
        engine = RuleEngine(ruleset)
        action_log = ActionLog()
        inventory = FileInventory()
        records = list(inventory.scan_directory(str(tmp_workspace / "src")))
        plan = engine.dry_run(records, base_dir=str(tmp_workspace))

        engine.execute(plan, action_log=action_log)

        stats = action_log.stats()
        # على الأقل: 2 move + 2 tag + 1 copy = 5 إجراءات
        assert stats["total"] >= 5
        assert "move" in stats["by_action_type"]
        assert "tag" in stats["by_action_type"]
        assert "copy" in stats["by_action_type"]
        assert stats["success_count"] == stats["total"]  # كلها ناجحة
        assert stats["success_rate"] == 100.0
