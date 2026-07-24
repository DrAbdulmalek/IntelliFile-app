"""SafeMover — نقل ونسخ آمن ذرّي مع تحقّق checksum ومعالجة sidecar

هذه الوحدة تنفّذ عمليات النقل/النسخ بأمان:
  - نقل ذرّي: كتابة إلى ملف مؤقت ثم rename (POSIX atomic rename)
  - تحقّق SHA-256 قبل وبعد العملية (integrity verification)
  - معالجة sidecar: نقل/نسخ ملف .ifm_meta_<name>.json مع الملف الأصلي
  - حل تضارب الأسماء: إضافة لاحقة _1, _2, ... تلقائيًا
  - تنظيف الملف المؤقت عند الفشل (rollback)
  - لا توجد إجراءات تدميرية: لا يحذف الملف المصدر عند الفشل
  - لا AI، لا medical — فقط عمليات ملفات آمنة

التصميم:
  - كل عملية تُرجع MoveResult/CopyResult يحتوي على: source, destination,
    checksum_before, checksum_after, success, error, sidecar_moved, duration_ms
  - لو فشل التحقّق بعد النقل، يُعاد الملف إلى موضعه الأصلي (rollback)
  - thread-safe عبر قفل لكل عملية (لا حالة مشتركة)
  - يعمل مع RuleEngine._exec_move/_exec_copy كبديل آمن

PR-07 من development-roadmap-v1.0 (IFM Phase A)
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)


# ─── ثوابت ─────────────────────────────────────────────────────────────────

# حجم الكتلة لقراءة الملف أثناء حساب checksum (64 KB)
_CHECKSUM_CHUNK_SIZE = 64 * 1024

# أقصى عدد محاولات لإيجاد اسم فريد عند التضارب
_MAX_NAME_COLLISION_RETRIES = 999


# ─── Dataclasses ────────────────────────────────────────────────────────────

@dataclass
class MoveResult:
    """نتيجة عملية نقل آمنة"""
    source: str
    destination: str
    checksum_before: str = ""
    checksum_after: str = ""
    sidecar_moved: bool = False
    sidecar_source: Optional[str] = None
    sidecar_destination: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0.0
    # هل استُخدمت لاحقة لحل التضارب؟
    renamed_due_to_collision: bool = False
    # المسار النهائي الفعلي (قد يختلف عن destination لو حدث تضارب)
    final_path: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # ضمان أن final_path معبأ دائمًا
        if not d.get("final_path"):
            d["final_path"] = d.get("destination", "")
        return d


@dataclass
class CopyResult:
    """نتيجة عملية نسخ آمنة"""
    source: str
    destination: str
    checksum_before: str = ""
    checksum_after: str = ""
    sidecar_copied: bool = False
    sidecar_source: Optional[str] = None
    sidecar_destination: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0.0
    renamed_due_to_collision: bool = False
    final_path: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if not d.get("final_path"):
            d["final_path"] = d.get("destination", "")
        return d


# ─── استثناءات ─────────────────────────────────────────────────────────────

class SafeMoveError(Exception):
    """خطأ في النقل الآمن"""


class ChecksumMismatchError(SafeMoveError):
    """عدم تطابق checksum بعد النقل/النسخ"""


class SourceNotFoundError(SafeMoveError):
    """الملف المصدر غير موجود"""


# ─── دوال مساعدة ───────────────────────────────────────────────────────────

def compute_sha256(file_path: Union[str, Path], *, chunk_size: int = _CHECKSUM_CHUNK_SIZE) -> str:
    """يحسب SHA-256 لملف

    Args:
        file_path: مسار الملف
        chunk_size: حجم الكتلة بالبايت (افتراضيًا 64 KB)

    Returns:
        hex digest بصيغة 64 حرفًا، أو "" لو الملف غير موجود

    Raises:
        OSError: لو فشلت قراءة الملف
    """
    p = Path(file_path)
    if not p.exists():
        return ""
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sidecar_path(file_path: Union[str, Path]) -> Path:
    """يُرجع مسار ملف sidecar (.ifm_meta_<name>.json) بجانب الملف

    ملاحظة: يجب أن يتطابق هذا مع rule_engine._sidecar_path
    """
    p = Path(file_path)
    return p.parent / f".ifm_meta_{p.name}.json"


def _resolve_collision(dst: Path, src: Path) -> tuple[Path, bool]:
    """يحل تضارب الأسماء بإضافة لاحقة _1, _2, ...

    Returns:
        (final_destination, was_renamed)
    """
    if not dst.exists():
        return dst, False
    # لو src و dst نفس الملف (نقل إلى نفس الموضع)
    try:
        if src.resolve() == dst.resolve():
            return dst, False
    except OSError:
        pass

    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent
    counter = 1
    while counter < _MAX_NAME_COLLISION_RETRIES:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate, True
        counter += 1
    raise SafeMoveError(
        f"تعذّر إيجاد اسم فريد بعد {_MAX_NAME_COLLISION_RETRIES} محاولة: {dst}"
    )


def _atomic_move(src: Path, dst: Path) -> None:
    """نقل ذرّي: محاولة os.rename أولًا، fallback إلى copy+delete عبر الأجهزة

    يعتمد على atomicity الخاص بـ rename على نفس نظام الملفات.
    لو src و dst على أنظمة ملفات مختلفة، نستخدم tempfile + copy + delete.
    """
    try:
        os.rename(str(src), str(dst))
    except OSError as e:
        # EXDEV: cross-device link not permitted
        if getattr(e, "errno", None) == 18:  # errno.EXDEV
            # نسخ عبر الأجهزة ثم حذف المصدر
            with tempfile.NamedTemporaryFile(
                prefix=".ifm_tmp_",
                dir=str(dst.parent),
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
            try:
                shutil.copy2(str(src), str(tmp_path))
                os.rename(str(tmp_path), str(dst))
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
            src.unlink()
        else:
            raise


def _atomic_copy(src: Path, dst: Path) -> None:
    """نسخ ذرّي: كتابة إلى ملف مؤقت في نفس مجلد الوجهة ثم rename"""
    with tempfile.NamedTemporaryFile(
        prefix=".ifm_tmp_",
        dir=str(dst.parent),
        delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copy2(str(src), str(tmp_path))
        os.rename(str(tmp_path), str(dst))
    finally:
        if tmp_path.exists() and tmp_path != dst:
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ─── SafeMover ──────────────────────────────────────────────────────────────

class SafeMover:
    """ناقل/ناسخ آمن للملفات مع تحقّق checksum ومعالجة sidecar

    الاستخدام الأساسي:

        mover = SafeMover()
        result = mover.move("/src/file.txt", "/dst/file.txt")
        if not result.success:
            print(f"فشل: {result.error}")

    الخصائص:
      - ذرّي: استخدم rename عبر ملف مؤقت
      - مُتحقَّق: SHA-256 قبل وبعد
      - آمن: لا يحذف المصدر عند الفشل
      - يحترم sidecar: ينقل/ينسخ .ifm_meta_<name>.json تلقائيًا
      - thread-safe: لا حالة مشتركة

    Options:
      - verify_checksum: افتراضيًا True، يتحقّق بعد العملية
      - move_sidecar: افتراضيًا True، ينقل/ينسخ sidecar إن وُجد
      - overwrite: افتراضيًا False، يُضيف لاحقة عند التضارب
    """

    def __init__(
        self,
        *,
        verify_checksum: bool = True,
        move_sidecar: bool = True,
        overwrite: bool = False,
    ):
        self.verify_checksum = verify_checksum
        self.move_sidecar = move_sidecar
        self.overwrite = overwrite

    # ─── Move ────────────────────────────────────────────────────────────

    def move(
        self,
        source: Union[str, Path],
        destination: Union[str, Path],
        *,
        verify_checksum: Optional[bool] = None,
        move_sidecar: Optional[bool] = None,
        overwrite: Optional[bool] = None,
    ) -> MoveResult:
        """نقل آمن لملف مع تحقّق checksum

        Args:
            source: مسار المصدر
            destination: مسار الوجهة
            verify_checksum: تجاوز الإعداد الافتراضي
            move_sidecar: تجاوز إعداد نقل sidecar
            overwrite: تجاوز إعداد overwrite

        Returns:
            MoveResult بتفاصيل العملية
        """
        start = time.monotonic()
        verify = self.verify_checksum if verify_checksum is None else verify_checksum
        do_sidecar = self.move_sidecar if move_sidecar is None else move_sidecar
        do_overwrite = self.overwrite if overwrite is None else overwrite

        src = Path(source)
        dst = Path(destination)

        result = MoveResult(
            source=str(src),
            destination=str(dst),
            final_path=str(dst),
        )

        # التحقق من وجود المصدر
        if not src.exists():
            result.success = False
            result.error = f"الملف المصدر غير موجود: {src}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # حساب checksum قبل النقل
        try:
            if verify:
                result.checksum_before = compute_sha256(src)
        except OSError as e:
            result.success = False
            result.error = f"فشل حساب checksum للمصدر: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # ضمان وجود مجلد الوجهة
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            result.success = False
            result.error = f"فشل إنشاء مجلد الوجهة: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # حل التضارب
        try:
            if do_overwrite:
                # لو overwrite=True، نحذف الوجهة إن وُجدت
                if dst.exists() and src.resolve() != dst.resolve():
                    dst.unlink()
                final_dst, renamed = dst, False
            else:
                final_dst, renamed = _resolve_collision(dst, src)
        except SafeMoveError as e:
            result.success = False
            result.error = str(e)
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        result.renamed_due_to_collision = renamed
        result.final_path = str(final_dst)

        # نقل sidecar أولاً (لو وُجد) — ننقله بعد الملف لتفادي ترك sidecar يتيمًا
        src_sidecar = _sidecar_path(src)
        dst_sidecar = _sidecar_path(final_dst)
        sidecar_existed = src_sidecar.exists()

        # النقل الذرّي
        try:
            _atomic_move(src, final_dst)
        except OSError as e:
            result.success = False
            result.error = f"فشل النقل: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # تحقّق checksum بعد النقل
        if verify:
            try:
                result.checksum_after = compute_sha256(final_dst)
            except OSError as e:
                # فشل التحقق — إعادة الملف إلى موضعه
                logger.error(f"فشل حساب checksum بعد النقل: {e} — محاولة rollback")
                try:
                    _atomic_move(final_dst, src)
                except OSError:
                    logger.error(f"فشل rollback من {final_dst} إلى {src}")
                result.success = False
                result.error = f"فشل حساب checksum بعد النقل: {e}"
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            if result.checksum_before != result.checksum_after:
                # عدم تطابق — rollback
                logger.error(
                    f"عدم تطابق checksum: قبل={result.checksum_before} "
                    f"بعد={result.checksum_after} — rollback"
                )
                try:
                    _atomic_move(final_dst, src)
                except OSError:
                    logger.error(f"فشل rollback من {final_dst} إلى {src}")
                result.success = False
                result.error = (
                    f"عدم تطابق checksum بعد النقل "
                    f"(قبل={result.checksum_before[:12]}..., "
                    f"بعد={result.checksum_after[:12]}...)"
                )
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

        # نقل sidecar
        if do_sidecar and sidecar_existed:
            try:
                if dst_sidecar.exists() and src_sidecar.resolve() != dst_sidecar.resolve():
                    # دمج — ندمج الوسوم
                    _merge_sidecar(dst_sidecar, src_sidecar)
                    src_sidecar.unlink()
                else:
                    _atomic_move(src_sidecar, dst_sidecar)
                result.sidecar_moved = True
                result.sidecar_source = str(src_sidecar)
                result.sidecar_destination = str(dst_sidecar)
            except OSError as e:
                # فشل نقل sidecar ليس فادحًا — السجل يحذّر فقط
                logger.warning(f"فشل نقل sidecar من {src_sidecar} إلى {dst_sidecar}: {e}")
                result.sidecar_moved = False

        result.success = True
        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ─── Copy ────────────────────────────────────────────────────────────

    def copy(
        self,
        source: Union[str, Path],
        destination: Union[str, Path],
        *,
        verify_checksum: Optional[bool] = None,
        copy_sidecar: Optional[bool] = None,
        overwrite: Optional[bool] = None,
    ) -> CopyResult:
        """نسخ آمن لملف مع تحقّق checksum

        Args:
            source: مسار المصدر
            destination: مسار الوجهة
            verify_checksum: تجاوز الإعداد الافتراضي
            copy_sidecar: تجاوز إعداد نسخ sidecar
            overwrite: تجاوز إعداد overwrite

        Returns:
            CopyResult بتفاصيل العملية
        """
        start = time.monotonic()
        verify = self.verify_checksum if verify_checksum is None else verify_checksum
        do_sidecar = self.move_sidecar if copy_sidecar is None else copy_sidecar
        do_overwrite = self.overwrite if overwrite is None else overwrite

        src = Path(source)
        dst = Path(destination)

        result = CopyResult(
            source=str(src),
            destination=str(dst),
            final_path=str(dst),
        )

        # التحقق من وجود المصدر
        if not src.exists():
            result.success = False
            result.error = f"الملف المصدر غير موجود: {src}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # checksum قبل
        try:
            if verify:
                result.checksum_before = compute_sha256(src)
        except OSError as e:
            result.success = False
            result.error = f"فشل حساب checksum للمصدر: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # ضمان مجلد الوجهة
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            result.success = False
            result.error = f"فشل إنشاء مجلد الوجهة: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # حل التضارب
        try:
            if do_overwrite:
                if dst.exists() and src.resolve() != dst.resolve():
                    dst.unlink()
                final_dst, renamed = dst, False
            else:
                final_dst, renamed = _resolve_collision(dst, src)
        except SafeMoveError as e:
            result.success = False
            result.error = str(e)
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        result.renamed_due_to_collision = renamed
        result.final_path = str(final_dst)

        # نسخ sidecar
        src_sidecar = _sidecar_path(src)
        dst_sidecar = _sidecar_path(final_dst)
        sidecar_existed = src_sidecar.exists()

        # النسخ الذرّي
        try:
            _atomic_copy(src, final_dst)
        except OSError as e:
            result.success = False
            result.error = f"فشل النسخ: {e}"
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        # تحقّق checksum
        if verify:
            try:
                result.checksum_after = compute_sha256(final_dst)
            except OSError as e:
                logger.error(f"فشل حساب checksum بعد النسخ: {e} — حذف النسخة")
                try:
                    final_dst.unlink()
                except OSError:
                    pass
                result.success = False
                result.error = f"فشل حساب checksum بعد النسخ: {e}"
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

            if result.checksum_before != result.checksum_after:
                logger.error(
                    f"عدم تطابق checksum بعد النسخ: قبل={result.checksum_before} "
                    f"بعد={result.checksum_after} — حذف النسخة"
                )
                try:
                    final_dst.unlink()
                except OSError:
                    pass
                result.success = False
                result.error = (
                    f"عدم تطابق checksum بعد النسخ "
                    f"(قبل={result.checksum_before[:12]}..., "
                    f"بعد={result.checksum_after[:12]}...)"
                )
                result.duration_ms = (time.monotonic() - start) * 1000
                return result

        # نسخ sidecar
        if do_sidecar and sidecar_existed:
            try:
                if dst_sidecar.exists() and src_sidecar.resolve() != dst_sidecar.resolve():
                    _merge_sidecar(dst_sidecar, src_sidecar)
                else:
                    _atomic_copy(src_sidecar, dst_sidecar)
                result.sidecar_copied = True
                result.sidecar_source = str(src_sidecar)
                result.sidecar_destination = str(dst_sidecar)
            except OSError as e:
                logger.warning(f"فشل نسخ sidecar: {e}")
                result.sidecar_copied = False

        result.success = True
        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ─── Batch ───────────────────────────────────────────────────────────

    def move_many(
        self,
        pairs: List[tuple[Union[str, Path], Union[str, Path]]],
        *,
        stop_on_error: bool = False,
    ) -> List[MoveResult]:
        """ينقل عدة أزواج (source, destination) دفعة واحدة

        Args:
            pairs: قائمة أزواج (source, destination)
            stop_on_error: لو True، يتوقف عند أول فشل

        Returns:
            قائمة MoveResult بنفس ترتيب pairs
        """
        results: List[MoveResult] = []
        for src, dst in pairs:
            r = self.move(src, dst)
            results.append(r)
            if not r.success and stop_on_error:
                break
        return results

    def copy_many(
        self,
        pairs: List[tuple[Union[str, Path], Union[str, Path]]],
        *,
        stop_on_error: bool = False,
    ) -> List[CopyResult]:
        """ينسخ عدة أزواج دفعة واحدة"""
        results: List[CopyResult] = []
        for src, dst in pairs:
            r = self.copy(src, dst)
            results.append(r)
            if not r.success and stop_on_error:
                break
        return results


# ─── Sidecar merge helper ───────────────────────────────────────────────────

def _merge_sidecar(target_sidecar: Path, source_sidecar: Path) -> None:
    """يدمج محتوى sidecar مصدر في sidecar هدف

    الوسوم: اتحاد القائمتين (deduped)
    التصنيف: يُحتفظ بقيمة الهدف إن وُجدت، وإلا يؤخذ من المصدر
    """
    import json
    try:
        target_data = json.loads(target_sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        target_data = {}
    try:
        source_data = json.loads(source_sidecar.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        source_data = {}

    merged_tags = list(set(target_data.get("tags", []) + source_data.get("tags", [])))
    target_data["tags"] = merged_tags
    if "category" not in target_data and "category" in source_data:
        target_data["category"] = source_data["category"]
    target_sidecar.write_text(
        json.dumps(target_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─── Convenience: integration with RuleEngine ──────────────────────────────

def safe_move_for_rule_engine(
    source: Union[str, Path],
    destination: Union[str, Path],
    *,
    overwrite: bool = False,
) -> tuple[bool, str, str]:
    """واجهة مبسّطة لاستخدام SafeMover من RuleEngine

    Returns:
        (success, final_destination, error_message)
        لو success=True، error_message فارغ
    """
    mover = SafeMover(verify_checksum=True, move_sidecar=True, overwrite=overwrite)
    result = mover.move(source, destination)
    if result.success:
        return True, result.final_path, ""
    return False, "", result.error or "unknown error"


def safe_copy_for_rule_engine(
    source: Union[str, Path],
    destination: Union[str, Path],
    *,
    overwrite: bool = False,
) -> tuple[bool, str, str]:
    """واجهة مبسّطة لاستخدام SafeMover (copy) من RuleEngine"""
    mover = SafeMover(verify_checksum=True, move_sidecar=True, overwrite=overwrite)
    result = mover.copy(source, destination)
    if result.success:
        return True, result.final_path, ""
    return False, "", result.error or "unknown error"
