"""IFMSettings — نموذج الإعدادات + التحميل/الحفظ JSON

يدير إعدادات IFM Desktop القابلة للتخصيص من قبل المستخدم:
  - watch_folders_enabled: تفعيل/تعطيل watch folders
  - default_dry_run: dry-run افتراضي قبل التنفيذ
  - confirm_destructive: تأكيد قبل الإجراءات التدميرية
  - semantic_search_enabled: تفعيل البحث الدلالي (اختياري)
  - dark_mode: الوضع الداكن
  - rtl: اتجاه RTL
  - auto_organize: تنظيم تلقائي بعد الفحص
  - max_text_preview_bytes: أقصى حجم لمعاينة النص
  - thumbnail_size: حجم المصغّرات

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─── قيم افتراضية ──────────────────────────────────────────────────────────

DEFAULT_SETTINGS_PATH = ".ifm_settings.json"

DEFAULT_THUMBNAIL_SIZE = 256  # px
DEFAULT_MAX_TEXT_PREVIEW_BYTES = 64 * 1024  # 64 KB


@dataclass
class IFMSettings:
    """إعدادات IFM Desktop

    جميع الحقول لها قيم افتراضية آمنة. الحفظ/التحميل عبر to_json/from_json.
    """

    # ─── المراقب ───────────────────────────────────────────────────────────
    watch_folders_enabled: bool = True
    """تفعيل مراقبة المجلدات (watch folders) تلقائيًا عند بدء التطبيق"""

    # ─── السلوك الآمن ───────────────────────────────────────────────────────
    default_dry_run: bool = True
    """إجراء محاكاة dry-run افتراضيًا قبل التنفيذ"""

    confirm_destructive: bool = True
    """طلب تأكيد صريح قبل الإجراءات التدميرية (delete_flag)"""

    # ─── الذكاء الاصطناعي (اختياري) ───────────────────────────────────────
    semantic_search_enabled: bool = False
    """تفعيل البحث الدلالي (يتطلب تنزيل نموذج embeddings)"""

    # ─── الواجهة ───────────────────────────────────────────────────────────
    dark_mode: bool = True
    """الوضع الداكن"""

    rtl: bool = True
    """اتجاه RTL للعربية"""

    auto_organize: bool = False
    """تشغيل القواعد تلقائيًا بعد كل فحص (يتطلب default_dry_run=true)"""

    # ─── المعاينة ───────────────────────────────────────────────────────────
    max_text_preview_bytes: int = DEFAULT_MAX_TEXT_PREVIEW_BYTES
    """أقصى حجم بالبايت لمعاينة النص (تجنّب قراءة ملفات ضخمة)"""

    thumbnail_size: int = DEFAULT_THUMBNAIL_SIZE
    """حجم المصغّرات بالبكسل (مربّعة)"""

    # ─── منع丢失 البيانات ────────────────────────────────────────────────
    save_undo_log_on_exit: bool = True
    """حفظ سجل التراجع تلقائيًا عند الإغلاق"""

    save_action_log_on_exit: bool = True
    """حفظ سجل الإجراءات تلقائيًا عند الإغلاق"""

    # ─── بيانات وصفية (لا يعدّلها المستخدم مباشرة) ────────────────────────
    last_base_dir: str = ""
    """آخر مجلد فُتح — يُستخدم لاستعادة الجلسة"""

    version: str = "1"
    """إصدار مخطّط الإعدادات (للترحيل المستقبلي)"""

    # ─── Serialize / Deserialize ───────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IFMSettings":
        """يبني IFMSettings من قاموس — يتجاهل المفاتيح غير المعروفة"""
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    @classmethod
    def from_json(cls, json_str: str) -> "IFMSettings":
        return cls.from_dict(json.loads(json_str))

    # ─── Persistence ───────────────────────────────────────────────────────

    def save(self, path: Optional[Path] = None) -> Path:
        """يحفظ الإعدادات إلى ملف JSON

        Args:
            path: المسار. إن None، يُستخدم ~/.ifm_settings.json

        Returns:
            المسار الفعلي للحفظ
        """
        target = Path(path) if path else Path.home() / DEFAULT_SETTINGS_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(self.to_json(), encoding="utf-8")
            logger.debug(f"IFMSettings saved to {target}")
        except OSError as e:
            logger.warning(f"IFMSettings.save failed: {e}")
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "IFMSettings":
        """يحمّل الإعدادات من ملف JSON — يُرجع افتراضي لو فشل

        Args:
            path: المسار. إن None، يُستخدم ~/.ifm_settings.json

        Returns:
            IFMSettings (افتراضي لو الملف غير موجود أو تالف)
        """
        target = Path(path) if path else Path.home() / DEFAULT_SETTINGS_PATH
        if not target.exists():
            logger.debug(f"IFMSettings file not found, using defaults: {target}")
            return cls()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"IFMSettings.load failed ({e}), using defaults")
            return cls()

    # ─── Apply diffs ───────────────────────────────────────────────────────

    def update(self, **kwargs) -> bool:
        """يحدّث حقولًا متعددة دفعة واحدة

        Returns:
            True لو تغيّرت أي قيمة، False لو لا
        """
        changed = False
        for k, v in kwargs.items():
            if k in self.__dataclass_fields__ and getattr(self, k) != v:
                setattr(self, k, v)
                changed = True
        return changed


__all__ = [
    "IFMSettings",
    "DEFAULT_SETTINGS_PATH",
    "DEFAULT_THUMBNAIL_SIZE",
    "DEFAULT_MAX_TEXT_PREVIEW_BYTES",
]
