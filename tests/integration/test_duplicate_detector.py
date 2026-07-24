"""اختبارات تكامل لكاشف التكرار (DuplicateDetector)

يغطي:
  - كشف التكرار التام عبر SHA-256
  - كشف التشابه عبر embeddings (cosine similarity)
  - حساب reclaimable_bytes
  - بناء Ruleset تلقائي من تقرير التكرار
  - التكامل مع FileInventory (ملفات حقيقية على القرص)
  - حالات حدية: إدخال فارغ، ملف واحد، بدون hash، بدون embedding
  - عتبة تشابه قابلة للضبط
  - serialization (to_dict / from_dict)

PR-06 من development-roadmap-v1.0
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from src.core.duplicate_detector import (
    DEFAULT_SIMILARITY_THRESHOLD,
    DuplicateDetector,
    DuplicateGroup,
    DuplicateReport,
    cosine_similarity,
)
from src.core.file_inventory import FileInventory
from src.core.rule_engine import RuleEngine
from src.core.rule_schemas import (
    Action, ActionType, Condition, Rule, Ruleset,
)
from src.db.schemas import FileMetadata, FileRecord


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_record(
    name: str,
    path: str,
    size: int = 100,
    sha256: str = "",
    embedding=None,
) -> FileRecord:
    """يبني FileRecord للاختبار"""
    return FileRecord(
        metadata=FileMetadata(
            file_name=name,
            file_path=path,
            file_size=size,
            sha256_hash=sha256,
        ),
        embedding=embedding,
    )


def _make_real_file(path: Path, content: bytes = b"hello world") -> None:
    """يكتب ملفًا حقيقيًا على القرص للاختبارات"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ─── كشف التكرار التام (exact via SHA-256) ──────────────────────────────────

class TestExactDuplicateDetection:
    """كشف التكرار التام عبر SHA-256"""

    def test_two_files_same_hash_form_one_group(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="hash1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=100, sha256="hash1")
        r3 = _make_record("c.txt", "/tmp/c.txt", size=50, sha256="hash2")

        report = DuplicateDetector().detect([r1, r2, r3])

        assert len(report.exact_groups) == 1
        g = report.exact_groups[0]
        assert g.kind == "exact"
        assert g.signature == "hash1"
        assert len(g.files) == 2
        assert g.similarity == 1.0
        assert g.reclaimable_bytes == 100  # 100 + 100 - 100 (الأكبر)

    def test_three_files_same_hash(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=300, sha256="hash1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=200, sha256="hash1")
        r3 = _make_record("c.txt", "/tmp/c.txt", size=100, sha256="hash1")

        report = DuplicateDetector().detect([r1, r2, r3])

        assert len(report.exact_groups) == 1
        g = report.exact_groups[0]
        assert len(g.files) == 3
        assert g.reclaimable_bytes == 300  # 600 - 300 (الأكبر)
        # suggested_keep = الأكبر حجمًا
        assert g.suggested_keep.metadata.file_name == "a.txt"

    def test_multiple_distinct_groups(self):
        records = [
            _make_record("a1.txt", "/tmp/a1.txt", sha256="h1"),
            _make_record("a2.txt", "/tmp/a2.txt", sha256="h1"),
            _make_record("b1.txt", "/tmp/b1.txt", sha256="h2"),
            _make_record("b2.txt", "/tmp/b2.txt", sha256="h2"),
            _make_record("b3.txt", "/tmp/b3.txt", sha256="h2"),
        ]
        report = DuplicateDetector().detect(records)
        assert len(report.exact_groups) == 2

    def test_no_duplicates_returns_empty_report(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", sha256="h2")
        r3 = _make_record("c.txt", "/tmp/c.txt", sha256="h3")

        report = DuplicateDetector().detect([r1, r2, r3])
        assert len(report.exact_groups) == 0
        assert report.total_duplicate_files == 0
        assert report.total_reclaimable_bytes == 0

    def test_files_without_hash_are_ignored(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", sha256="")
        r2 = _make_record("b.txt", "/tmp/b.txt", sha256="")

        report = DuplicateDetector().detect([r1, r2])
        assert len(report.exact_groups) == 0
        assert report.files_with_hash == 0

    def test_groups_sorted_by_reclaimable_bytes_desc(self):
        r1 = _make_record("a1.txt", "/tmp/a1.txt", size=1000, sha256="h1")
        r2 = _make_record("a2.txt", "/tmp/a2.txt", size=1000, sha256="h1")
        r3 = _make_record("b1.txt", "/tmp/b1.txt", size=100, sha256="h2")
        r4 = _make_record("b2.txt", "/tmp/b2.txt", size=100, sha256="h2")

        report = DuplicateDetector().detect([r1, r2, r3, r4])
        assert len(report.exact_groups) == 2
        # المجموعة الأولى يجب أن تكون الأعلى استرجاعًا
        assert report.exact_groups[0].reclaimable_bytes >= report.exact_groups[1].reclaimable_bytes


# ─── كشف التشابه (near via embeddings) ──────────────────────────────────────

class TestNearDuplicateDetection:
    """كشف التشابه عبر embeddings"""

    def test_three_similar_files_form_one_near_group(self):
        r1 = _make_record("img1.jpg", "/tmp/img1.jpg", size=1000, sha256="h1",
                          embedding=[1.0, 0.0, 0.0])
        r2 = _make_record("img2.jpg", "/tmp/img2.jpg", size=900, sha256="h2",
                          embedding=[0.99, 0.01, 0.0])
        r3 = _make_record("img3.jpg", "/tmp/img3.jpg", size=800, sha256="h3",
                          embedding=[0.98, 0.02, 0.0])

        report = DuplicateDetector(similarity_threshold=0.95).detect([r1, r2, r3])
        assert len(report.near_groups) == 1
        g = report.near_groups[0]
        assert g.kind == "near"
        assert len(g.files) == 3
        assert g.similarity > 0.95
        assert g.suggested_keep.metadata.file_name == "img1.jpg"  # الأكبر

    def test_distinct_embeddings_no_near_group(self):
        r1 = _make_record("a.jpg", "/tmp/a.jpg", embedding=[1.0, 0.0, 0.0])
        r2 = _make_record("b.jpg", "/tmp/b.jpg", embedding=[0.0, 1.0, 0.0])
        r3 = _make_record("c.jpg", "/tmp/c.jpg", embedding=[0.0, 0.0, 1.0])

        report = DuplicateDetector(similarity_threshold=0.95).detect([r1, r2, r3])
        assert len(report.near_groups) == 0

    def test_threshold_tuning(self):
        # نفس مجموعة الملفات لكن بعتبة أعلى — يجب أن تنخفض المجموعات
        r1 = _make_record("a.jpg", "/tmp/a.jpg", embedding=[1.0, 0.0])
        r2 = _make_record("b.jpg", "/tmp/b.jpg", embedding=[0.9, 0.4])  # sim ≈ 0.91

        # عتبة 0.85 → مجموعة
        report_low = DuplicateDetector(similarity_threshold=0.85).detect([r1, r2])
        assert len(report_low.near_groups) == 1

        # عتبة 0.95 → لا مجموعة
        report_high = DuplicateDetector(similarity_threshold=0.95).detect([r1, r2])
        assert len(report_high.near_groups) == 0

    def test_use_embeddings_false_disables_near(self):
        r1 = _make_record("a.jpg", "/tmp/a.jpg", embedding=[1.0, 0.0])
        r2 = _make_record("b.jpg", "/tmp/b.jpg", embedding=[0.99, 0.01])

        report = DuplicateDetector(use_embeddings=False).detect([r1, r2])
        assert len(report.near_groups) == 0

    def test_files_without_embedding_excluded_from_near(self):
        r1 = _make_record("a.jpg", "/tmp/a.jpg", sha256="h1", embedding=[1.0, 0.0])
        r2 = _make_record("b.jpg", "/tmp/b.jpg", sha256="h2", embedding=None)
        r3 = _make_record("c.jpg", "/tmp/c.jpg", sha256="h3", embedding=[])

        report = DuplicateDetector().detect([r1, r2, r3])
        assert len(report.near_groups) == 0
        assert report.files_with_embedding == 1

    def test_exact_dups_not_redetected_as_near(self):
        """ملفان بنفس SHA-256 يجب ألا يظهرا في near_groups أيضًا"""
        r1 = _make_record("a.txt", "/tmp/a.txt", sha256="same_hash",
                          embedding=[1.0, 0.0])
        r2 = _make_record("b.txt", "/tmp/b.txt", sha256="same_hash",
                          embedding=[1.0, 0.0])

        report = DuplicateDetector().detect([r1, r2])
        assert len(report.exact_groups) == 1
        assert len(report.near_groups) == 0  # لا تكرار في near

    def test_two_near_groups(self):
        # مجموعتان متشابهتان داخليًا، لكنهما مختلفتان عن بعضهما
        r1 = _make_record("a1.jpg", "/tmp/a1.jpg", embedding=[1.0, 0.0, 0.0])
        r2 = _make_record("a2.jpg", "/tmp/a2.jpg", embedding=[0.99, 0.0, 0.0])
        r3 = _make_record("b1.jpg", "/tmp/b1.jpg", embedding=[0.0, 1.0, 0.0])
        r4 = _make_record("b2.jpg", "/tmp/b2.jpg", embedding=[0.0, 0.99, 0.0])

        report = DuplicateDetector(similarity_threshold=0.95).detect([r1, r2, r3, r4])
        assert len(report.near_groups) == 2


# ─── Reclaimable bytes & summary ─────────────────────────────────────────────

class TestReclaimableBytes:
    """حساب الحجم القابل للاسترجاع"""

    def test_exact_group_reclaimable(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=500, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=300, sha256="h1")
        r3 = _make_record("c.txt", "/tmp/c.txt", size=200, sha256="h1")

        report = DuplicateDetector().detect([r1, r2, r3])
        # 500 + 300 + 200 - 500 (الأكبر) = 500
        assert report.exact_groups[0].reclaimable_bytes == 500
        assert report.total_reclaimable_bytes == 500

    def test_summary_dict(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=100, sha256="h1")

        report = DuplicateDetector().detect([r1, r2])
        s = report.summary()
        assert s["exact_groups"] == 1
        assert s["total_duplicate_files"] == 1
        assert s["reclaimable_bytes"] == 100
        assert s["scanned_files"] == 2

    def test_to_dict_serialization(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=100, sha256="h1")

        report = DuplicateDetector().detect([r1, r2])
        d = report.to_dict()
        assert "exact_groups" in d
        assert "near_groups" in d
        assert d["total_groups"] == 1
        assert d["total_duplicate_files"] == 1
        # ملف واحد على الأقل في المجموعة
        assert len(d["exact_groups"][0]["files"]) == 2
        assert d["exact_groups"][0]["files"][0]["sha256_hash"] == "h1"


# ─── تكامل مع FileInventory (ملفات حقيقية) ──────────────────────────────────

class TestFileInventoryIntegration:
    """التكامل مع FileInventory على ملفات حقيقية"""

    def test_real_duplicate_files_detected(self, tmp_path):
        # إنشاء ملفات حقيقية: ملفان متطابقان + ملف مختلف
        content = b"this is duplicate content"
        _make_real_file(tmp_path / "original.txt", content)
        _make_real_file(tmp_path / "copy.txt", content)
        _make_real_file(tmp_path / "different.txt", b"different content")

        inventory = FileInventory(include_content=False)
        records = inventory.scan_directory(str(tmp_path))

        detector = DuplicateDetector()
        report = detector.detect(records)

        assert len(report.exact_groups) == 1
        g = report.exact_groups[0]
        assert len(g.files) == 2
        # الأسماء المتوقعة
        names = {f.metadata.file_name for f in g.files}
        assert names == {"original.txt", "copy.txt"}
        assert g.reclaimable_bytes > 0

    def test_three_copies_of_same_file(self, tmp_path):
        content = b"identical binary content for three files" * 10
        _make_real_file(tmp_path / "a.bin", content)
        _make_real_file(tmp_path / "b.bin", content)
        _make_real_file(tmp_path / "c.bin", content)

        inventory = FileInventory(include_content=False)
        records = inventory.scan_directory(str(tmp_path))

        report = DuplicateDetector().detect(records)
        assert len(report.exact_groups) == 1
        assert len(report.exact_groups[0].files) == 3
        assert report.total_duplicate_files == 2

    def test_no_duplicates_in_unique_directory(self, tmp_path):
        _make_real_file(tmp_path / "a.txt", b"content a")
        _make_real_file(tmp_path / "b.txt", b"content b")
        _make_real_file(tmp_path / "c.txt", b"content c")

        inventory = FileInventory(include_content=False)
        records = inventory.scan_directory(str(tmp_path))

        report = DuplicateDetector().detect(records)
        assert len(report.exact_groups) == 0
        assert report.total_reclaimable_bytes == 0

    def test_nested_directories_duplicates(self, tmp_path):
        """ملفات مكررة في مجلدات فرعية مختلفة"""
        content = b"same content in different folders"
        _make_real_file(tmp_path / "sub1" / "file.txt", content)
        _make_real_file(tmp_path / "sub2" / "file.txt", content)

        inventory = FileInventory(include_content=False)
        records = inventory.scan_directory(str(tmp_path))

        report = DuplicateDetector().detect(records)
        assert len(report.exact_groups) == 1
        assert len(report.exact_groups[0].files) == 2


# ─── التكامل مع RuleEngine ──────────────────────────────────────────────────

class TestRuleEngineIntegration:
    """التكامل مع RuleEngine عبر build_duplicate_ruleset"""

    def test_build_duplicate_ruleset_tags_duplicates(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=500, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=300, sha256="h1")
        r3 = _make_record("c.txt", "/tmp/c.txt", size=200, sha256="h1")

        detector = DuplicateDetector()
        report = detector.detect([r1, r2, r3])
        ruleset = DuplicateDetector.build_duplicate_ruleset(report)

        engine = RuleEngine(ruleset)
        plan = engine.dry_run([r1, r2, r3], base_dir="/tmp")

        # قاعدتان لكل مجموعة: keep (يطابق 1) + redundant (يطابق 2) = 3 إجراءات tag
        assert plan.total_actions == 3

        # التحقق من الوسوم
        tags = {p.action.value for p in plan.planned_actions}
        assert "duplicate:keep" in tags
        assert "duplicate:redundant" in tags

    def test_build_duplicate_ruleset_with_flag_redundant(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=500, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=300, sha256="h1")

        detector = DuplicateDetector()
        report = detector.detect([r1, r2])
        ruleset = DuplicateDetector.build_duplicate_ruleset(report, flag_redundant=True)

        engine = RuleEngine(ruleset)
        plan = engine.dry_run([r1, r2], base_dir="/tmp")

        # إجراء tag للملف المُبقى + إجراءين للملف الزائد (tag + delete_flag)
        # = 1 + 2 = 3 إجراءات
        assert plan.total_actions == 3

        # التحقق من وجود delete_flag على الملف الزائد
        types = [p.action.type for p in plan.planned_actions]
        assert ActionType.DELETE_FLAG.value in types

    def test_custom_tag_name_in_ruleset(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", sha256="h1")

        report = DuplicateDetector().detect([r1, r2])
        ruleset = DuplicateDetector.build_duplicate_ruleset(report, tag="dup")

        engine = RuleEngine(ruleset)
        plan = engine.dry_run([r1, r2], base_dir="/tmp")
        tags = {p.action.value for p in plan.planned_actions}
        assert "dup:keep" in tags
        assert "dup:redundant" in tags

    def test_end_to_end_scan_detect_plan(self, tmp_path):
        """اختبار شامل: مسح → كشف → خطة"""
        content = b"hello world duplicate"
        _make_real_file(tmp_path / "a.txt", content)
        _make_real_file(tmp_path / "b.txt", content)

        # 1) مسح
        inventory = FileInventory(include_content=False)
        records = inventory.scan_directory(str(tmp_path))
        assert len(records) == 2

        # 2) كشف التكرار
        detector = DuplicateDetector()
        report = detector.detect(records)
        assert len(report.exact_groups) == 1

        # 3) بناء خطة من Ruleset
        ruleset = DuplicateDetector.build_duplicate_ruleset(report)
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir=str(tmp_path))

        assert plan.total_actions == 2  # keep + redundant
        assert plan.files_affected == 2


# ─── حالات حدية ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    """حالات حدية"""

    def test_empty_input(self):
        report = DuplicateDetector().detect([])
        assert len(report.exact_groups) == 0
        assert len(report.near_groups) == 0
        assert report.scanned_files == 0

    def test_single_file_no_groups(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", sha256="h1")
        report = DuplicateDetector().detect([r1])
        assert len(report.exact_groups) == 0
        assert report.total_duplicate_files == 0

    def test_invalid_similarity_threshold_raises(self):
        with pytest.raises(ValueError):
            DuplicateDetector(similarity_threshold=1.5)
        with pytest.raises(ValueError):
            DuplicateDetector(similarity_threshold=-0.1)

    def test_zero_norm_embedding_excluded(self):
        """embedding بصفر norm يجب استبعاده"""
        r1 = _make_record("a.jpg", "/tmp/a.jpg", embedding=[0.0, 0.0, 0.0])
        r2 = _make_record("b.jpg", "/tmp/b.jpg", embedding=[0.0, 0.0, 0.0])

        report = DuplicateDetector().detect([r1, r2])
        assert len(report.near_groups) == 0


# ─── cosine_similarity helper ─────────────────────────────────────────────────

class TestCosineSimilarity:
    """دالة cosine_similarity المستقلة"""

    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_three_dim(self):
        # cosine sim of [1,1,0] and [1,0,0] = 1/sqrt(2)
        s = cosine_similarity([1.0, 1.0, 0.0], [1.0, 0.0, 0.0])
        assert s == pytest.approx(0.7071, abs=0.001)


# ─── DuplicateGroup properties ────────────────────────────────────────────────

class TestDuplicateGroupProperties:
    """خصائص DuplicateGroup"""

    def test_total_size_bytes(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=200, sha256="h1")
        g = DuplicateGroup(kind="exact", signature="h1", files=[r1, r2])
        assert g.total_size_bytes == 300

    def test_suggested_keep_is_largest(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=500, sha256="h1")
        r3 = _make_record("c.txt", "/tmp/c.txt", size=200, sha256="h1")
        g = DuplicateGroup(kind="exact", signature="h1", files=[r1, r2, r3])
        assert g.suggested_keep.metadata.file_name == "b.txt"

    def test_suggested_keep_empty_returns_none(self):
        g = DuplicateGroup(kind="exact", signature="h1", files=[])
        assert g.suggested_keep is None

    def test_to_dict_structure(self):
        r1 = _make_record("a.txt", "/tmp/a.txt", size=100, sha256="h1")
        r2 = _make_record("b.txt", "/tmp/b.txt", size=200, sha256="h1")
        g = DuplicateGroup(
            kind="exact", signature="h1", files=[r1, r2],
            similarity=1.0, reclaimable_bytes=200,
        )
        d = g.to_dict()
        assert d["kind"] == "exact"
        assert d["signature"] == "h1"
        assert d["file_count"] == 2
        assert d["reclaimable_bytes"] == 200
        assert d["similarity"] == 1.0
        assert len(d["files"]) == 2
        assert d["files"][0]["sha256_hash"] == "h1"
