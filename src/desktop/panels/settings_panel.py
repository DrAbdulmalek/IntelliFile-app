"""SettingsPanel — لوحة الإعدادات

تعرض كل الإعدادات القابلة للتخصيص من قبل المستخدم:

  ─── المراقب ─────────────────
  ☑ تفعيل watch folders

  ─── السلوك الآمن ─────────────
  ☑ dry-run افتراضي قبل التنفيذ
  ☑ تأكيد قبل الإجراءات التدميرية
  ☐ تنظيم تلقائي بعد الفحص

  ─── الذكاء الاصطناعي ─────────
  ☐ تفعيل البحث الدلالي (اختياري)

  ─── الواجهة ─────────────────
  ☑ الوضع الداكن
  ☑ اتجاه RTL

  ─── حفظ ─────────────────────
  ☑ حفظ سجل التراجع عند الإغلاق
  ☑ حفظ سجل الإجراءات عند الإغلاق

  [حفظ الإعدادات]  [استعادة الافتراضي]

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..settings import IFMSettings

logger = logging.getLogger(__name__)


# ─── SettingsPanel ──────────────────────────────────────────────────────────

class SettingsPanel(QWidget):
    """لوحة إعدادات IFM

    Signals:
        settings_changed(IFMSettings): الإعدادات المحدّثة (عند الحفظ)
        theme_change_requested(str): طلب تغيير السمة ("dark" أو "light")
        rtl_change_requested(bool): طلب تغيير اتجاه RTL
    """

    settings_changed = Signal(object)  # IFMSettings
    theme_change_requested = Signal(str)  # "dark" | "light"
    rtl_change_requested = Signal(bool)

    def __init__(self, settings: IFMSettings | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SettingsPanel")
        self._settings = settings or IFMSettings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────────
        title = QLabel("الإعدادات")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("خصّص سلوك IFM Desktop — كل التغييرات تُحفظ محليًا")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── صندوق المراقب ─────────────────────────────────────────────────
        watch_box = QGroupBox("المراقب (Watch Folders)")
        watch_layout = QVBoxLayout(watch_box)

        self.watch_folders_check = QCheckBox("تفعيل مراقبة المجلدات تلقائيًا")
        self.watch_folders_check.setToolTip(
            "عند التفعيل، يبدأ المراقب تلقائيًا مع التطبيق لرصد التغييرات في المجلد الأساسي"
        )
        watch_layout.addWidget(self.watch_folders_check)

        layout.addWidget(watch_box)

        # ─── صندوق السلوك الآمن ────────────────────────────────────────────
        safety_box = QGroupBox("السلوك الآمن")
        safety_layout = QVBoxLayout(safety_box)

        self.dry_run_check = QCheckBox("إجراء محاكاة (dry-run) افتراضيًا قبل التنفيذ")
        self.dry_run_check.setToolTip(
            "يفحص الإجراءات قبل تنفيذها — يُنصح بشدّة بإبقائه مفعّلًا"
        )
        safety_layout.addWidget(self.dry_run_check)

        self.confirm_destructive_check = QCheckBox("طلب تأكيد قبل الإجراءات التدميرية")
        self.confirm_destructive_check.setToolTip(
            "تأكيد إضافي قبل عمليات delete_flag (لا يمكن التراجع عنها)"
        )
        safety_layout.addWidget(self.confirm_destructive_check)

        self.auto_organize_check = QCheckBox("تشغيل القواعد تلقائيًا بعد كل فحص")
        self.auto_organize_check.setToolTip(
            "ينفّذ القواعد تلقائيًا بعد الفحص — يتطلب تفعيل dry-run افتراضيًا للأمان"
        )
        safety_layout.addWidget(self.auto_organize_check)

        layout.addWidget(safety_box)

        # ─── صندوق الذكاء الاصطناعي ────────────────────────────────────────
        ai_box = QGroupBox("الذكاء الاصطناعي (اختياري)")
        ai_layout = QVBoxLayout(ai_box)

        self.semantic_search_check = QCheckBox("تفعيل البحث الدلالي")
        self.semantic_search_check.setToolTip(
            "يتطلب تنزيل نموذج embeddings (~120 MB) — قد يستغرق وقتًا طويلًا"
        )
        ai_layout.addWidget(self.semantic_search_check)

        ai_hint = QLabel(
            "ℹ️ البحث الدلالي ميزة اختيارية لا تؤثّر على الوظائف الأساسية. "
            "عند التفعيل لأول مرة، سيُنزَّل النموذج تلقائيًا."
        )
        ai_hint.setStyleSheet("color: #656d76; font-size: 11px;")
        ai_hint.setWordWrap(True)
        ai_layout.addWidget(ai_hint)

        layout.addWidget(ai_box)

        # ─── صندوق الواجهة ────────────────────────────────────────────────
        ui_box = QGroupBox("الواجهة")
        ui_layout = QVBoxLayout(ui_box)

        self.dark_mode_check = QCheckBox("الوضع الداكن")
        self.dark_mode_check.setToolTip("تبديل بين السمة الفاتحة والداكنة")
        ui_layout.addWidget(self.dark_mode_check)

        self.rtl_check = QCheckBox("اتجاه RTL (يمين-إلى-يسار)")
        self.rtl_check.setToolTip("مناسب للعربية والعبرية")
        ui_layout.addWidget(self.rtl_check)

        # حجم المصغّرات
        thumb_row = QHBoxLayout()
        thumb_row.addWidget(QLabel("حجم المصغّرات:"))
        self.thumbnail_size_spin = QSpinBox()
        self.thumbnail_size_spin.setRange(64, 1024)
        self.thumbnail_size_spin.setSingleStep(32)
        self.thumbnail_size_spin.setSuffix(" px")
        thumb_row.addWidget(self.thumbnail_size_spin)
        thumb_row.addStretch(1)
        ui_layout.addLayout(thumb_row)

        # حد المعاينة النصية
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("حد المعاينة النصية:"))
        self.text_preview_spin = QSpinBox()
        self.text_preview_spin.setRange(4, 1024)
        self.text_preview_spin.setSingleStep(4)
        self.text_preview_spin.setSuffix(" KB")
        preview_row.addWidget(self.text_preview_spin)
        preview_row.addStretch(1)
        ui_layout.addLayout(preview_row)

        layout.addWidget(ui_box)

        # ─── صندوق الحفظ ───────────────────────────────────────────────────
        save_box = QGroupBox("الحفظ عند الإغلاق")
        save_layout = QVBoxLayout(save_box)

        self.save_undo_check = QCheckBox("حفظ سجل التراجع تلقائيًا")
        save_layout.addWidget(self.save_undo_check)

        self.save_action_check = QCheckBox("حفظ سجل الإجراءات تلقائيًا")
        save_layout.addWidget(self.save_action_check)

        layout.addWidget(save_box)

        # ─── أزرار ─────────────────────────────────────────────────────────
        buttons_row = QHBoxLayout()
        buttons_row.addStretch(1)

        reset_btn = QPushButton("استعادة الافتراضي")
        reset_btn.clicked.connect(self._on_reset)
        buttons_row.addWidget(reset_btn)

        save_btn = QPushButton("💾 حفظ الإعدادات")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self._on_save)
        buttons_row.addWidget(save_btn)

        layout.addLayout(buttons_row)

        # ملء القيم الحالية
        self._load_from_settings(self._settings)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_settings(self, settings: IFMSettings) -> None:
        """يحدّث الإعدادات المعروضة"""
        self._settings = settings
        self._load_from_settings(settings)

    def get_settings(self) -> IFMSettings:
        """يرجع الإعدادات الحالية من الحقول"""
        return IFMSettings(
            watch_folders_enabled=self.watch_folders_check.isChecked(),
            default_dry_run=self.dry_run_check.isChecked(),
            confirm_destructive=self.confirm_destructive_check.isChecked(),
            semantic_search_enabled=self.semantic_search_check.isChecked(),
            dark_mode=self.dark_mode_check.isChecked(),
            rtl=self.rtl_check.isChecked(),
            auto_organize=self.auto_organize_check.isChecked(),
            max_text_preview_bytes=self.text_preview_spin.value() * 1024,
            thumbnail_size=self.thumbnail_size_spin.value(),
            save_undo_log_on_exit=self.save_undo_check.isChecked(),
            save_action_log_on_exit=self.save_action_check.isChecked(),
            last_base_dir=self._settings.last_base_dir,
            version=self._settings.version,
        )

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        """يجمع القيم، يحفظ، ويبثّ settings_changed"""
        new_settings = self.get_settings()

        # كشف تغيير السمة / RTL
        old_dark = self._settings.dark_mode
        old_rtl = self._settings.rtl
        self._settings = new_settings

        # حفظ على القرص
        save_path = new_settings.save()
        logger.info(f"Settings saved to {save_path}")

        # بثّ الإشارات
        self.settings_changed.emit(new_settings)

        # لو تغيّرت السمة
        if new_settings.dark_mode != old_dark:
            self.theme_change_requested.emit("dark" if new_settings.dark_mode else "light")

        # لو تغيّر RTL
        if new_settings.rtl != old_rtl:
            self.rtl_change_requested.emit(new_settings.rtl)

        QMessageBox.information(
            self, "تم الحفظ",
            "تم حفظ الإعدادات بنجاح.\n"
            "بعض التغييرات (مثل السمة) قد تحتاج لإعادة تشغيل التطبيق لتظهر بالكامل.",
        )

    def _on_reset(self) -> None:
        """يستعيد الإعدادات الافتراضية"""
        reply = QMessageBox.question(
            self, "استعادة الافتراضي",
            "هل تريد استعادة كل الإعدادات الافتراضية؟\n(لن تُحفظ حتى تضغط زر الحفظ)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._load_from_settings(IFMSettings())

    # ─── Internal ──────────────────────────────────────────────────────────

    def _load_from_settings(self, settings: IFMSettings) -> None:
        """يملأ الحقول من كائن الإعدادات"""
        self.watch_folders_check.setChecked(settings.watch_folders_enabled)
        self.dry_run_check.setChecked(settings.default_dry_run)
        self.confirm_destructive_check.setChecked(settings.confirm_destructive)
        self.semantic_search_check.setChecked(settings.semantic_search_enabled)
        self.dark_mode_check.setChecked(settings.dark_mode)
        self.rtl_check.setChecked(settings.rtl)
        self.auto_organize_check.setChecked(settings.auto_organize)
        self.thumbnail_size_spin.setValue(settings.thumbnail_size)
        # text_preview_spin بالكيلوبايت
        self.text_preview_spin.setValue(max(4, settings.max_text_preview_bytes // 1024))
        self.save_undo_check.setChecked(settings.save_undo_log_on_exit)
        self.save_action_check.setChecked(settings.save_action_log_on_exit)


__all__ = ["SettingsPanel"]
