"""FilePreviewPanel — معاينة محتوى الملف (نص + صورة مصغّرة)

يدعم:
  - ملفات نصية (txt, md, csv, log, py, js, json, yaml, ...): أول N بايت
  - صور (jpg, png, gif, bmp, webp): مصغّرة عبر QPixmap
  - ملفات أخرى: عرض معلومات الملف فقط (الحجم، النوع، آخر تعديل)

التصميم:
  - معاينة غير متزامنة (تُحمَّل في الخلفية عبر QThread — TODO في PR-10)
  - في PR-09: معاينة متزامنة لكن سريعة (للملفات الصغيرة فقط)
  - يعرض معلومات الملف دائمًا

PR-09 من development-roadmap-v1.0 (IFM Phase C — Desktop UX)
"""
from __future__ import annotations

import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# ─── ثوابت ─────────────────────────────────────────────────────────────────

# امتدادات تُعتبر نصية للمعاينة
TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".md", ".markdown", ".rst",
    ".csv", ".tsv", ".log",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".rb", ".go", ".rs", ".swift", ".kt", ".scala",
    ".html", ".htm", ".css", ".scss", ".sass",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".sql", ".sh", ".bash", ".zsh", ".ps1",
    ".env", ".gitignore", ".dockerfile",
    ".tex", ".bib",
}

# امتدادات صور يدعمها QPixmap مباشرة
IMAGE_EXTENSIONS: Set[str] = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".tif",
}

# حد أقصى لحجم النص المعروض (1 MB) — لتجنّب تجميد الواجهة
MAX_TEXT_DISPLAY_BYTES = 1 * 1024 * 1024


def _format_size(size_bytes: int) -> str:
    """تنسيق الحجم بصيغة مقروءة"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


# ─── FilePreviewPanel ───────────────────────────────────────────────────────

class FilePreviewPanel(QWidget):
    """لوحة معاينة محتوى الملف

    يعرض:
      - معلومات الملف (الاسم، المسار، الحجم، النوع، آخر تعديل)
      - معاينة النص (للملفات النصية الصغيرة)
      - صورة مصغّرة (للصور)
      - رسالة "غير متاح" للأنواع الأخرى
    """

    def __init__(self, max_text_bytes: int = 64 * 1024, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("FilePreviewPanel")
        self._max_text_bytes = max_text_bytes
        self._current_path: Optional[Path] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ─── عنوان ─────────────────────────────────────────────────────────
        title = QLabel("معاينة الملف")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        # ─── معلومات الملف ─────────────────────────────────────────────────
        info_box = QGroupBox("معلومات الملف")
        info_layout = QVBoxLayout(info_box)
        info_layout.setSpacing(4)

        self._name_label = QLabel("—")
        self._path_label = QLabel("—")
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color: #656d76; font-size: 11px;")
        self._size_label = QLabel("—")
        self._type_label = QLabel("—")
        self._modified_label = QLabel("—")

        info_layout.addWidget(self._name_label)
        info_layout.addWidget(self._path_label)
        info_layout.addWidget(self._size_label)
        info_layout.addWidget(self._type_label)
        info_layout.addWidget(self._modified_label)

        layout.addWidget(info_box)

        # ─── منطقة المعاينة ───────────────────────────────────────────────
        preview_box = QGroupBox("المعاينة")
        preview_layout = QVBoxLayout(preview_box)

        # منطقة عرض المعاينة (scroll area)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setMinimumHeight(240)

        # container للمعاينة
        self._preview_container = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_container)
        self._preview_layout.setContentsMargins(0, 0, 0, 0)
        self._preview_layout.setSpacing(8)

        # تسمية النص
        self._text_preview = QPlainTextEdit()
        self._text_preview.setReadOnly(True)
        self._text_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._text_preview.setStyleSheet(
            "QPlainTextEdit { font-family: 'Noto Sans Mono', 'Courier New', monospace; "
            "font-size: 12px; }"
        )
        self._text_preview.setVisible(False)
        self._preview_layout.addWidget(self._text_preview)

        # تسمية الصورة
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._image_label.setMinimumHeight(240)
        self._image_label.setStyleSheet("background: #f0f2f5; border-radius: 4px;")
        self._image_label.setVisible(False)
        self._preview_layout.addWidget(self._image_label)

        # تسمية "غير متاح"
        self._unavailable_label = QLabel("معاينة غير متاحة لهذا النوع من الملفات")
        self._unavailable_label.setAlignment(Qt.AlignCenter)
        self._unavailable_label.setStyleSheet("color: #656d76; padding: 40px;")
        self._unavailable_label.setVisible(False)
        self._preview_layout.addWidget(self._unavailable_label)

        # تسمية "لا يوجد ملف محدّد"
        self._no_file_label = QLabel("اختر ملفًا من جدول الجرد لمعاينته")
        self._no_file_label.setAlignment(Qt.AlignCenter)
        self._no_file_label.setStyleSheet("color: #656d76; padding: 40px;")
        self._no_file_label.setVisible(True)
        self._preview_layout.addWidget(self._no_file_label)

        self._scroll.setWidget(self._preview_container)
        preview_layout.addWidget(self._scroll)

        layout.addWidget(preview_box, stretch=1)

        # إخفاء كل المعاينات افتراضيًا
        self._hide_all_previews()

    # ─── Public API ────────────────────────────────────────────────────────

    def set_max_text_bytes(self, max_bytes: int) -> None:
        """يضبط أقصى حجم لمعاينة النص"""
        self._max_text_bytes = max_bytes

    def clear_preview(self) -> None:
        """يعرض حالة "لا يوجد ملف محدّد" """
        self._current_path = None
        self._hide_all_previews()
        self._no_file_label.setVisible(True)
        self._name_label.setText("—")
        self._path_label.setText("—")
        self._size_label.setText("—")
        self._type_label.setText("—")
        self._modified_label.setText("—")

    def preview_file(self, file_path: str) -> None:
        """يعاين ملفًا — يحدّد النوع ويستدعي المعاين المناسب"""
        path = Path(file_path)
        self._current_path = path

        if not path.exists() or not path.is_file():
            self._show_error(f"الملف غير موجود: {file_path}")
            return

        # تحديث معلومات الملف
        self._update_file_info(path)

        # تحديد نوع المعاينة حسب الامتداد
        ext = path.suffix.lower()
        if ext in TEXT_EXTENSIONS:
            self._preview_text(path)
        elif ext in IMAGE_EXTENSIONS:
            self._preview_image(path)
        else:
            self._show_unavailable(path)

    # ─── Internal: previews ────────────────────────────────────────────────

    def _preview_text(self, path: Path) -> None:
        """يعاين ملفًا نصيًا"""
        try:
            size = path.stat().st_size
            # لو الملف كبير جدًا، نقرأ فقط أول max_text_bytes
            read_bytes = min(size, self._max_text_bytes)
            with open(path, "rb") as f:
                raw = f.read(read_bytes)
            # محاولة فك الترميز (UTF-8 افتراضيًا، fallback إلى latin-1)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")

            self._hide_all_previews()
            self._text_preview.setPlainText(text)
            if size > self._max_text_bytes:
                self._text_preview.appendPlainText(
                    f"\n\n... [قُصعت المعاينة عند {_format_size(self._max_text_bytes)} من أصل {_format_size(size)}]"
                )
            self._text_preview.setVisible(True)

            # Scroll إلى الأعلى
            cursor = self._text_preview.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self._text_preview.setTextCursor(cursor)
        except Exception as e:
            self._show_error(f"تعذّرت قراءة الملف: {e}")

    def _preview_image(self, path: Path) -> None:
        """يعاين صورة كمصغّرة"""
        try:
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self._show_error("تعذّر تحميل الصورة (صيغة غير مدعومة)")
                return
            # تصغير الصورة لتناسب المعاينة (مع الحفاظ على النسبة)
            max_size = 480
            if pixmap.width() > max_size or pixmap.height() > max_size:
                pixmap = pixmap.scaled(
                    max_size, max_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            self._hide_all_previews()
            self._image_label.setPixmap(pixmap)
            self._image_label.setVisible(True)
        except Exception as e:
            self._show_error(f"تعذّر تحميل الصورة: {e}")

    def _show_unavailable(self, path: Path) -> None:
        """يعرض رسالة "معاينة غير متاحة" """
        self._hide_all_previews()
        ext = path.suffix.lower()
        mime, _ = mimetypes.guess_type(str(path))
        msg = f"معاينة غير متاحة لهذا النوع من الملفات ({ext})"
        if mime:
            msg += f"\nالنوع MIME: {mime}"
        self._unavailable_label.setText(msg)
        self._unavailable_label.setVisible(True)

    def _show_error(self, message: str) -> None:
        """يعرض رسالة خطأ"""
        self._hide_all_previews()
        self._unavailable_label.setText(f"⚠ {message}")
        self._unavailable_label.setVisible(True)

    def _update_file_info(self, path: Path) -> None:
        """يحدّث معلومات الملف"""
        stat = path.stat()
        self._name_label.setText(f"📁 <b>{path.name}</b>")
        self._path_label.setText(f"📍 {path.parent}")
        self._size_label.setText(f"💾 الحجم: {_format_size(stat.st_size)}")
        ext = path.suffix.lower() or "(بدون امتداد)"
        mime, _ = mimetypes.guess_type(str(path))
        type_str = mime or "غير معروف"
        self._type_label.setText(f"🏷 النوع: {ext} — {type_str}")
        try:
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            mtime = "—"
        self._modified_label.setText(f"🕒 آخر تعديل: {mtime}")

    def _hide_all_previews(self) -> None:
        """يخفي كل عناصر المعاينة"""
        self._text_preview.setVisible(False)
        self._image_label.setVisible(False)
        self._unavailable_label.setVisible(False)
        self._no_file_label.setVisible(False)


__all__ = ["FilePreviewPanel", "TEXT_EXTENSIONS", "IMAGE_EXTENSIONS"]
