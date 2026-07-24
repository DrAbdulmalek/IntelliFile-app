"""DuplicateDetector — كشف التكرار والتشابه بين الملفات

يدعم مستويين من كشف التكرار:
  1. تكرار تام (exact) عبر SHA-256: ملفان بتشفير متطابق = مكرران حتمًا.
  2. تكرار قريب (near) عبر embedding (اختياري): ملفان بتضمين عالي التشابه
     (cosine similarity ≥ threshold) يُعتبران "متشابهين" — مفيد للصور المتكررة
     بدقات مختلفة أو المستندات المعدّلة قليلًا.

التصميم:
  - للقراءة فقط: لا يحذف ولا ينقل ولا يُعدّل أي ملف.
  - تكامل مع FileInventory: يأخذ Iterable[FileRecord] ويُنتج DuplicateReport.
  - تكامل مع RuleEngine: يمكن توليد Ruleset تلقائي يضع وسم "duplicate"
    على جميع الملفات المكررة (للاستخدام في dry-run لاحقًا).
  - استخدام embeddings اختياري: لو لم تكن متوفرة في FileRecord، يتم تخطّي
    كشف التشابه والاكتفاء بكشف التكرار التام.
  - متسامح: السجلات بلا hash أو بلا embedding صالحة تُتخطّى بأمان.

PR-06 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..db.schemas import FileRecord

logger = logging.getLogger(__name__)


# ─── ثوابت افتراضية ──────────────────────────────────────────────────────────
DEFAULT_SIMILARITY_THRESHOLD = 0.95  # cosine sim للصور/المستندات "المتشابهة جدًا"
MIN_FILES_FOR_NEAR_GROUP = 2         # لا تُنتج مجموعة تشابه أقل من ملفين
EMBEDDING_BATCH_SIZE = 256           # حد أقصى للمقارنات في الذاكرة دفعة واحدة


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass
class DuplicateGroup:
    """مجموعة ملفات مكررة (تامة أو متشابهة)

    Attributes:
        kind: "exact" أو "near"
        signature: بصمة المجموعة (SHA-256 للـ exact، أو مسار الملف الممثل للـ near)
        files: قائمة FileRecord في المجموعة
        similarity: متوسط التشابه الزوجي داخل المجموعة (1.0 للـ exact)
        reclaimable_bytes: الحجم القابل للاسترجاع لو احتفظنا بأكبر ملف فقط
                          = مجموع أحجام كل الملفات − حجم أكبر ملف
    """
    kind: str  # "exact" | "near"
    signature: str
    files: List[FileRecord] = field(default_factory=list)
    similarity: float = 1.0
    reclaimable_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "signature": self.signature,
            "files": [
                {
                    "file_path": f.metadata.file_path,
                    "file_name": f.metadata.file_name,
                    "file_size": f.metadata.file_size,
                    "sha256_hash": f.metadata.sha256_hash,
                    "has_embedding": f.has_embedding,
                }
                for f in self.files
            ],
            "similarity": round(self.similarity, 4),
            "reclaimable_bytes": self.reclaimable_bytes,
            "file_count": len(self.files),
        }

    @property
    def total_size_bytes(self) -> int:
        return sum(f.metadata.file_size for f in self.files)

    @property
    def suggested_keep(self) -> Optional[FileRecord]:
        """يقترح أي ملف يُحتفظ به (الأكبر حجمًا، ثم الأبجدية لكسر التعادل)"""
        if not self.files:
            return None
        return max(self.files, key=lambda f: (f.metadata.file_size, f.metadata.file_name))


@dataclass
class DuplicateReport:
    """تقرير كامل بكل مجموعات التكرار في مجلد ما

    Attributes:
        exact_groups: مجموعات التكرار التام (SHA-256 متطابق)
        near_groups: مجموعات التشابه (embedding cosine ≥ threshold)
        similarity_threshold: العتبة المستخدمة (للأرشفة)
        total_redundant_bytes: مجموع ما تستهلكه النسخ الزائدة (قابل للاسترجاع)
        scanned_files: عدد الملفات التي فُحصت
        files_with_hash: عدد الملفات التي لها SHA-256
        files_with_embedding: عدد الملفات التي لها embedding
    """
    exact_groups: List[DuplicateGroup] = field(default_factory=list)
    near_groups: List[DuplicateGroup] = field(default_factory=list)
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    scanned_files: int = 0
    files_with_hash: int = 0
    files_with_embedding: int = 0

    @property
    def total_reclaimable_bytes(self) -> int:
        return sum(g.reclaimable_bytes for g in self.exact_groups + self.near_groups)

    @property
    def total_duplicate_files(self) -> int:
        """عدد الملفات المكررة (لا يشمل النسخة الأصلية في كل مجموعة)"""
        return sum(len(g.files) - 1 for g in self.exact_groups + self.near_groups)

    @property
    def total_groups(self) -> int:
        return len(self.exact_groups) + len(self.near_groups)

    def to_dict(self) -> dict:
        return {
            "exact_groups": [g.to_dict() for g in self.exact_groups],
            "near_groups": [g.to_dict() for g in self.near_groups],
            "similarity_threshold": self.similarity_threshold,
            "scanned_files": self.scanned_files,
            "files_with_hash": self.files_with_hash,
            "files_with_embedding": self.files_with_embedding,
            "total_groups": self.total_groups,
            "total_duplicate_files": self.total_duplicate_files,
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
            "total_reclaimable_human": _format_size(self.total_reclaimable_bytes),
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        return {
            "exact_groups": len(self.exact_groups),
            "near_groups": len(self.near_groups),
            "total_groups": self.total_groups,
            "total_duplicate_files": self.total_duplicate_files,
            "reclaimable_bytes": self.total_reclaimable_bytes,
            "reclaimable_human": _format_size(self.total_reclaimable_bytes),
            "scanned_files": self.scanned_files,
            "coverage_hash_pct": round(
                100.0 * self.files_with_hash / max(1, self.scanned_files), 1
            ),
            "coverage_embedding_pct": round(
                100.0 * self.files_with_embedding / max(1, self.scanned_files), 1
            ),
        }


# ─── DuplicateDetector ──────────────────────────────────────────────────────

class DuplicateDetector:
    """كاشف التكرار والتشابه بين الملفات

    الاستخدام الأساسي:

        inventory = FileInventory()
        records = inventory.scan_directory("/data")
        detector = DuplicateDetector(similarity_threshold=0.92)
        report = detector.detect(records)
        print(report.summary())

    التكامل مع RuleEngine:

        ruleset = DuplicateDetector.build_duplicate_ruleset(report, tag="duplicate")
        engine = RuleEngine(ruleset)
        plan = engine.dry_run(records, base_dir="/data")
        # الخطة الآن تحتوي على إجراء tag "duplicate" لكل ملف مكرر
    """

    def __init__(
        self,
        *,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        use_embeddings: bool = True,
        min_files_for_near_group: int = MIN_FILES_FOR_NEAR_GROUP,
    ):
        """
        Args:
            similarity_threshold: عتبة cosine similarity لاعتبار ملفين "متشابهين"
                                  (0.0-1.0). الافتراضي 0.95.
            use_embeddings: هل يُحاول كشف التشابه عبر embeddings؟
                           إن False، يتم فقط كشف التكرار التام عبر SHA-256.
            min_files_for_near_group: الحد الأدنى لعدد الملفات لتكوين مجموعة تشابه.
        """
        if not 0.0 <= similarity_threshold <= 1.0:
            raise ValueError(
                f"similarity_threshold يجب أن تكون بين 0 و 1، لكنها {similarity_threshold}"
            )
        self.similarity_threshold = similarity_threshold
        self.use_embeddings = use_embeddings
        self.min_files_for_near_group = min_files_for_near_group

    def detect(self, records: Iterable[FileRecord]) -> DuplicateReport:
        """يكشف التكرار في مجموعة سجلات

        Args:
            records: سجلات الملفات (يفضّل من FileInventory.scan)

        Returns:
            DuplicateReport: تقرير بمجموعات التكرار التام والمتشابه
        """
        records_list = list(records)
        report = DuplicateReport(
            similarity_threshold=self.similarity_threshold,
            scanned_files=len(records_list),
        )

        # إحصائيات التغطية
        report.files_with_hash = sum(
            1 for r in records_list if r.metadata.sha256_hash
        )
        report.files_with_embedding = sum(
            1 for r in records_list if r.has_embedding
        )

        # 1) كشف التكرار التام عبر SHA-256
        report.exact_groups = self._detect_exact(records_list)

        # 2) كشف التشابه عبر embeddings (اختياري)
        if self.use_embeddings:
            # استبعاد الملفات التي وقعت بالفعل في مجموعة تكرار تام
            # (لا حاجة لإعادة اكتشافها كـ near)
            exact_paths = set()
            for g in report.exact_groups:
                for f in g.files:
                    exact_paths.add(f.metadata.file_path)
            candidates = [
                r for r in records_list
                if r.has_embedding and r.metadata.file_path not in exact_paths
            ]
            if len(candidates) >= self.min_files_for_near_group:
                report.near_groups = self._detect_near(candidates)

        logger.info(
            f"كشف التكرار: {len(report.exact_groups)} مجموعة تامة، "
            f"{len(report.near_groups)} مجموعة متشابهة، "
            f"{report.total_reclaimable_bytes} بايت قابلة للاسترجاع"
        )
        return report

    # ─── كشف التكرار التام ──────────────────────────────────────────────

    def _detect_exact(self, records: List[FileRecord]) -> List[DuplicateGroup]:
        """يجمع الملفات حسب SHA-256 ويعيد المجموعات التي بها أكثر من ملف"""
        groups: Dict[str, List[FileRecord]] = {}
        for r in records:
            h = r.metadata.sha256_hash
            if not h:
                continue
            groups.setdefault(h, []).append(r)

        result: List[DuplicateGroup] = []
        for h, files in groups.items():
            if len(files) < 2:
                continue
            # ترتيب الملفات داخل المجموعة (الأكبر أولًا ثم الأبجدية)
            files.sort(key=lambda f: (-f.metadata.file_size, f.metadata.file_path))
            reclaimable = sum(f.metadata.file_size for f in files) - files[0].metadata.file_size
            result.append(DuplicateGroup(
                kind="exact",
                signature=h,
                files=files,
                similarity=1.0,
                reclaimable_bytes=reclaimable,
            ))
        # ترتيب المجموعات: الأعلى استرجاعًا أولًا
        result.sort(key=lambda g: g.reclaimable_bytes, reverse=True)
        return result

    # ─── كشف التشابه عبر embeddings ──────────────────────────────────────

    def _detect_near(self, records: List[FileRecord]) -> List[DuplicateGroup]:
        """يكتشف التشابه بين الملفات عبر cosine similarity على embeddings

        الخوارزمية:
          - لكل زوج ملفات، احسب cosine similarity.
          - ابنِ graph: عقدة = ملف، حافة = تشابه ≥ threshold.
          - المكوّنات المتصلة (connected components) = مجموعات تشابه.
          - متوسط التشابه الزوجي داخل المجموعة = similarity group.
        """
        try:
            import numpy as np
        except ImportError:
            logger.warning("numpy غير مثبت — لا يمكن كشف التشابه عبر embeddings")
            return []

        if len(records) < self.min_files_for_near_group:
            return []

        # بناء مصفوفة embeddings (N × D)
        embeddings = []
        valid_records = []
        for r in records:
            if r.embedding is None or len(r.embedding) == 0:
                continue
            try:
                emb = np.asarray(r.embedding, dtype=np.float32)
            except (ValueError, TypeError):
                continue
            # تسوية L2 لتسهيل حساب cosine
            norm = np.linalg.norm(emb)
            if norm < 1e-9:
                continue
            embeddings.append(emb / norm)
            valid_records.append(r)

        if len(valid_records) < self.min_files_for_near_group:
            return []

        emb_matrix = np.vstack(embeddings)  # (N, D)
        # مصفوفة التشابه (N, N) = emb_matrix @ emb_matrix^T
        sim_matrix = emb_matrix @ emb_matrix.T

        # تجميع عبر connected components باستخدام Union-Find
        n = len(valid_records)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # حساب التشابه الزوجي (فوق القطر)
        pair_sims: Dict[Tuple[int, int], float] = {}
        for i in range(n):
            for j in range(i + 1, n):
                s = float(sim_matrix[i, j])
                # clip للتعامل مع أخطاء الفاصلة العائمة
                s = max(-1.0, min(1.0, s))
                if s >= self.similarity_threshold:
                    union(i, j)
                    pair_sims[(i, j)] = s

        # تجميع الفهارس حسب الجذر
        components: Dict[int, List[int]] = {}
        for i in range(n):
            root = find(i)
            components.setdefault(root, []).append(i)

        result: List[DuplicateGroup] = []
        for indices in components.values():
            if len(indices) < self.min_files_for_near_group:
                continue
            files = [valid_records[i] for i in indices]
            files.sort(key=lambda f: (-f.metadata.file_size, f.metadata.file_path))
            # متوسط التشابه الزوجي داخل المجموعة
            sims_in_group: List[float] = []
            for i_idx in range(len(indices)):
                for j_idx in range(i_idx + 1, len(indices)):
                    a, b = indices[i_idx], indices[j_idx]
                    key = (a, b) if a < b else (b, a)
                    s = pair_sims.get(key)
                    if s is None:
                        # لم يكن فوق العتبة بشكل مباشر، احسبه
                        s = float(sim_matrix[a, b])
                    sims_in_group.append(s)
            avg_sim = sum(sims_in_group) / len(sims_in_group) if sims_in_group else 1.0

            reclaimable = sum(f.metadata.file_size for f in files) - files[0].metadata.file_size
            # signature = مسار الملف الممثل (الأكبر) — بصمة فريدة لل مجموعة
            signature = files[0].metadata.file_path or f"near_group_{len(result)}"
            result.append(DuplicateGroup(
                kind="near",
                signature=signature,
                files=files,
                similarity=avg_sim,
                reclaimable_bytes=reclaimable,
            ))

        result.sort(key=lambda g: g.reclaimable_bytes, reverse=True)
        return result

    # ─── التكامل مع RuleEngine ────────────────────────────────────────────

    @staticmethod
    def build_duplicate_ruleset(
        report: DuplicateReport,
        *,
        tag: str = "duplicate",
        keep_strategy: str = "largest",
        flag_redundant: bool = False,
    ) -> "Ruleset":
        """يبني Ruleset يضع وسم "duplicate" على كل ملف مكرر

        القواعد المُولّدة:
          - لكل مجموعة تكرار، قاعدتان:
            a) قاعدة "keep" للملف المختار (tag "duplicate:keep")
            b) قاعدة "redundant" لبقية الملفات (tag "duplicate:redundant")
              وإن flag_redundant=True يُضاف إجراء delete_flag أيضًا.

        Args:
            report: تقرير التكرار من DuplicateDetector.detect()
            tag: اسم الوسم الأساسي (افتراضي "duplicate")
            keep_strategy: "largest" (الأكبر حجمًا) — استراتيجية الاحتفاظ
                          (حاليًا فقط "largest" مدعوم)
            flag_redundant: لو True، يُضاف delete_flag للملفات الزائدة

        Returns:
            Ruleset جاهز للاستخدام مع RuleEngine
        """
        from .rule_schemas import Rule, Condition, Action, ActionType

        if keep_strategy != "largest":
            raise ValueError(f"keep_strategy غير مدعوم: {keep_strategy}")

        rules: List[Rule] = []
        for group_idx, group in enumerate(report.exact_groups + report.near_groups):
            keep_file = group.suggested_keep
            if keep_file is None:
                continue
            keep_path = keep_file.metadata.file_path

            # قاعدة الاحتفاظ: شرط file_path == keep_path → tag "duplicate:keep"
            rules.append(Rule(
                name=f"duplicate-keep-{group_idx}",
                description=f"الإبقاء على {keep_file.metadata.file_name} كممثل للمجموعة {group_idx}",
                priority=100 - group_idx,  # الأولوية تتناقص مع رقم المجموعة
                conditions=[
                    Condition(field="file_path", op="eq", value=keep_path),
                ],
                actions=[
                    Action(type=ActionType.TAG.value, value=f"{tag}:keep"),
                ],
            ))

            # قاعدة الزائدة: شرط file_path in [paths] → tag "duplicate:redundant"
            redundant_paths = [
                f.metadata.file_path for f in group.files
                if f.metadata.file_path != keep_path
            ]
            if redundant_paths:
                actions = [Action(type=ActionType.TAG.value, value=f"{tag}:redundant")]
                if flag_redundant:
                    actions.append(Action(type=ActionType.DELETE_FLAG.value))
                rules.append(Rule(
                    name=f"duplicate-redundant-{group_idx}",
                    description=f"وسم {len(redundant_paths)} ملف كمكرر زائد",
                    priority=90 - group_idx,
                    conditions=[
                        Condition(field="file_path", op="in", value=redundant_paths),
                    ],
                    actions=actions,
                ))

        from .rule_schemas import Ruleset
        return Ruleset(
            name="Duplicate Detection Ruleset",
            description=(
                f"يوسم {report.total_duplicate_files} ملفًا مكررًا في "
                f"{report.total_groups} مجموعة. لا يحذف — يستخدم delete_flag فقط "
                f"لو flag_redundant=True."
            ),
            rules=rules,
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_size(size_bytes: int) -> str:
    """تنسيق الحجم بصيغة مقروءة"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """يحسب cosine similarity بين متجهين (للاستخدام الخارجي/الاختبارات)

    Returns:
        float في النطاق [-1, 1] (1 = متطابقان، 0 = مستقلان)
    """
    try:
        import numpy as np
        va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
        na, nb = np.linalg.norm(va), np.linalg.norm(vb)
        if na < 1e-9 or nb < 1e-9:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except ImportError:
        # fallback نقي Python (أبطأ لكنه يعمل بدون numpy)
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na < 1e-9 or nb < 1e-9:
            return 0.0
        return dot / (na * nb)
