"""InventoryPanel — لوحة عرض FileInventory

تعرض:
  - زر اختيار مجلد + زر فحص
  - جدول بالملفات المفهرسة (الاسم، المسار، الحجم، التصنيف، الوسوم، SHA-256)
  - إحصائيات ملخصة (إجمالي الملفات، الحجم، المكررات)

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


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


class InventoryPanel(QWidget):
    """لوحة عرض ملفات FileInventory

    Signals:
        scan_requested(str): طلب فحص مجلد
        selection_changed(str): تغيّر الملف المحدّد (file_path)
    """

    scan_requested = Signal(str)
    selection_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("جرد الملفات")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel("افحص مجلدًا لبناء قائمة الملفات المفهرسة مع SHA-256 والميتاداتا")
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── شريط الأدوات ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("مسار المجلد...")
        self.path_edit.setToolTip("مسار المجلد المراد فحصه (مثل /home/user/Downloads)")
        self.path_edit.setStatusTip("أدخل مسار المجلد ثم اضغط فحص")
        toolbar.addWidget(self.path_edit, stretch=1)

        browse_btn = QPushButton("تصفّح...")
        browse_btn.setToolTip("اختيار مجلد عبر حوار الملفات")
        browse_btn.setStatusTip("افتح حوار اختيار المجلد")
        browse_btn.clicked.connect(self._on_browse)
        toolbar.addWidget(browse_btn)

        self.scan_btn = QPushButton("فحص")
        self.scan_btn.setProperty("primary", True)
        self.scan_btn.setToolTip("فحص المجلد المُدخل وبناء قائمة الملفات (F5)")
        self.scan_btn.setStatusTip("ابدأ فحص المجلد")
        self.scan_btn.clicked.connect(self._on_scan)
        toolbar.addWidget(self.scan_btn)

        layout.addLayout(toolbar)

        # ─── إحصائيات ──────────────────────────────────────────────────
        self.stats_label = QLabel("لم يُفحص أي مجلد بعد")
        self.stats_label.setStyleSheet("color: #656d76; font-size: 12px;")
        layout.addWidget(self.stats_label)

        # ─── جدول الملفات ─────────────────────────────────────────────
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "اسم الملف", "المجلد", "الحجم", "النوع", "التصنيف", "الوسوم", "SHA-256",
        ])
        self.table.setToolTip("قائمة الملفات المفهرسة — اختر صفًا لمعاينة محتواه")
        self.table.setStatusTip("انقر على صف لمعاينة الملف")
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "اختر مجلدًا للفحص")
        if path:
            self.path_edit.setText(path)

    def _on_scan(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            self.stats_label.setText("⚠ أدخل مسار مجلد أولًا")
            return
        self.scan_requested.emit(path)

    def _on_selection_changed(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        # نأخذ المسار الكامل المخزّن في Qt.UserRole لعمود "اسم الملف"
        name_item = self.table.item(row, 0)
        if name_item is None:
            return
        file_path = name_item.data(Qt.UserRole)
        if file_path:
            self.selection_changed.emit(str(file_path))
        else:
            # fallback: إعادة بناء من اسم الملف + المجلد
            dir_item = self.table.item(row, 1)
            if name_item and dir_item:
                file_path = f"{dir_item.text()}/{name_item.text()}"
                self.selection_changed.emit(file_path)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_records(self, records: list) -> None:
        """يملأ الجدول بقائمة FileRecord"""
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            md = record.metadata
            name_item = QTableWidgetItem(md.file_name)
            # نخزّن المسار الكامل في Qt.UserRole لاستخدامه في المعاينة (PR-09)
            name_item.setData(Qt.UserRole, md.file_path)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(md.parent_dir))
            self.table.setItem(row, 2, QTableWidgetItem(_format_size(md.file_size)))
            self.table.setItem(row, 3, QTableWidgetItem(md.extension or ""))
            self.table.setItem(row, 4, QTableWidgetItem(md.category or ""))
            self.table.setItem(row, 5, QTableWidgetItem(", ".join(md.tags)))
            # SHA-256 مختصر (8 حروف)
            sha = md.sha256_hash[:8] + "…" if len(md.sha256_hash) > 8 else md.sha256_hash
            self.table.setItem(row, 6, QTableWidgetItem(sha))

    def set_stats(self, total_files: int, total_size_bytes: int, duplicates: int = 0) -> None:
        """يحدّث ملخص الإحصائيات"""
        self.stats_label.setText(
            f"📊 {total_files} ملف | 💾 {_format_size(total_size_bytes)} | "
            f"🔁 {duplicates} مكرر محتمل"
        )

    def set_path(self, path: str) -> None:
        """يضبط مسار المجلد في حقل الإدخال"""
        self.path_edit.setText(path)

    def set_scanning(self, scanning: bool) -> None:
        """يضع اللوحة في حالة فحص (تعطيل زر الفحص)"""
        self.scan_btn.setEnabled(not scanning)
        self.scan_btn.setText("يفحص..." if scanning else "فحص")
