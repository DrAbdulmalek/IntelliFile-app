"""PluginPanel — لوحة إدارة المكونات الإضافية (Phase E)

تعرض:
  - جدول بكل المكونات المُكتشفة (اسم، إصدار، مؤلف، وصف، حالة التهيئة)
  - شريط أدوات: إعادة تحميل + فتح مجلد المكونات + فتح ملف الإعدادات
  - منطقة تفاصيل للمكوّن المحدد (config JSON قابل للعرض فقط)
  - حالة سفلية: عدد المكوّنات + المسارات

الترابط مع PluginManager:
  - تأخذ PluginManager في __init__ (اختياري — لو None، الأزرار تتعطل)
  - set_plugins(metadata) يحدّث الجدول من PluginManager.list_plugins()
  - إشارة reload_requested تُطلق عند طلب المستخدم إعادة التحميل
  - يعرض PluginManager.PLUGIN_DIR و CONFIG_FILE في الأسفل

Phase E من development-roadmap-v1.0
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PluginPanel(QWidget):
    """لوحة إدارة المكونات الإضافية

    Signals:
        reload_requested(): طلب إعادة اكتشاف + تحميل المكونات
    """

    reload_requested = Signal()

    def __init__(
        self,
        plugin_manager: Any | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._plugin_manager = plugin_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ─── عنوان ─────────────────────────────────────────────────────
        title = QLabel("المكونات الإضافية")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "إدارة المكونات المُكتشفة من ~/.intellifile/plugins/*_plugin.py"
        )
        subtitle.setObjectName("PanelSubtitle")
        layout.addWidget(subtitle)

        # ─── شريط الأدوات ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.reload_btn = QPushButton("↻ إعادة تحميل")
        self.reload_btn.setProperty("primary", True)
        self.reload_btn.setToolTip(
            "إعادة اكتشاف + تحميل كل المكونات من ~/.intellifile/plugins/"
        )
        self.reload_btn.setEnabled(plugin_manager is not None)
        self.reload_btn.clicked.connect(self._on_reload)
        toolbar.addWidget(self.reload_btn)

        self.open_dir_btn = QPushButton("📁 فتح مجلد المكونات")
        self.open_dir_btn.setToolTip("فتح ~/.intellifile/plugins/ في مدير الملفات")
        self.open_dir_btn.clicked.connect(self._on_open_dir)
        toolbar.addWidget(self.open_dir_btn)

        self.open_config_btn = QPushButton("⚙ فتح ملف الإعدادات")
        self.open_config_btn.setToolTip("فتح ~/.intellifile/plugins.json")
        self.open_config_btn.clicked.connect(self._on_open_config)
        toolbar.addWidget(self.open_config_btn)

        toolbar.addStretch(1)

        self.count_label = QLabel("0 مكوّن")
        self.count_label.setStyleSheet("color: #656d76; font-size: 12px;")
        toolbar.addWidget(self.count_label)

        layout.addLayout(toolbar)

        # ─── جدول المكونات ────────────────────────────────────────────
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "الاسم", "الإصدار", "المؤلف", "الوصف", "الحالة",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=2)

        # ─── تفاصيل المكوّن المحدد ─────────────────────────────────────
        details_label = QLabel("تفاصيل المكوّن المحدد (config):")
        details_label.setStyleSheet("color: #656d76; font-size: 12px;")
        layout.addWidget(details_label)

        self.details_view = QPlainTextEdit()
        self.details_view.setReadOnly(True)
        self.details_view.setPlaceholderText(
            "اختر مكوّناً من الجدول لعرض إعداداته (config) هنا."
        )
        self.details_view.setMaximumHeight(150)
        layout.addWidget(self.details_view, stretch=1)

        # ─── حالة سفلية: المسارات ─────────────────────────────────────
        self.paths_label = QLabel()
        self.paths_label.setStyleSheet("color: #6e7681; font-size: 11px;")
        self.paths_label.setWordWrap(True)
        layout.addWidget(self.paths_label)
        self._refresh_paths_label()

    # ─── Slots ─────────────────────────────────────────────────────────────

    def _on_reload(self) -> None:
        """يطلب من الـ controller إعادة اكتشاف + تحميل المكونات."""
        self.reload_requested.emit()

    def _on_open_dir(self) -> None:
        """يفتح مجلد المكونات في مدير الملفات الافتراضي."""
        plugin_dir = self._get_plugin_dir()
        try:
            plugin_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(plugin_dir.absolute().as_uri())

    def _on_open_config(self) -> None:
        """يفتح ~/.intellifile/plugins.json (ينشئه فارغاً لو غير موجود)."""
        config_file = self._get_config_file()
        if not config_file.exists():
            try:
                config_file.parent.mkdir(parents=True, exist_ok=True)
                config_file.write_text("{}", encoding="utf-8")
            except OSError as e:
                QMessageBox.warning(
                    self, "تعذّر الإنشاء",
                    f"تعذّر إنشاء ملف الإعدادات:\n{config_file}\n\nالسبب: {e}",
                )
                return
        QDesktopServices.openUrl(config_file.absolute().as_uri())

    def _on_selection_changed(self) -> None:
        """يعرض config المكوّن المحدد في منطقة التفاصيل."""
        current = self.table.currentItem()
        if current is None:
            self.details_view.clear()
            return
        row = current.row()
        name_item = self.table.item(row, 0)
        if name_item is None:
            self.details_view.clear()
            return
        name = name_item.text()
        config = self._get_plugin_config(name)
        if config is None:
            self.details_view.setPlainText(
                f"(لا يوجد config محفوظ للمكوّن '{name}' في plugins.json)"
            )
        else:
            try:
                formatted = json.dumps(config, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                formatted = str(config)
            self.details_view.setPlainText(formatted)

    # ─── Public API ────────────────────────────────────────────────────────

    def set_plugins(self, plugins: list[dict]) -> None:
        """يملأ الجدول بقائمة metadata مكوّنات (من PluginManager.list_plugins()).

        كل عنصر: {"name", "version", "description", "author", "initialized"}
        """
        self.table.setRowCount(0)
        for plugin in plugins:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(plugin.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(plugin.get("version", "")))
            self.table.setItem(row, 2, QTableWidgetItem(plugin.get("author", "")))
            self.table.setItem(row, 3, QTableWidgetItem(plugin.get("description", "")))
            initialized = bool(plugin.get("initialized", False))
            status_text = "✓ مهيّأ" if initialized else "✗ غير مهيّأ"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(Qt.darkGreen if initialized else Qt.red)
            self.table.setItem(row, 4, status_item)

        self.count_label.setText(f"{len(plugins)} مكوّن")

    def refresh_from_manager(self) -> None:
        """يسحب أحدث metadata من PluginManager ويحدّث الجدول."""
        if self._plugin_manager is None:
            return
        self.set_plugins(self._plugin_manager.list_plugins())

    def set_plugin_manager(self, plugin_manager: Any) -> None:
        """يضبط PluginManager (بعد الإنشاء إن لم يُمرر في __init__)."""
        self._plugin_manager = plugin_manager
        self.reload_btn.setEnabled(plugin_manager is not None)
        self._refresh_paths_label()
        if plugin_manager is not None:
            self.refresh_from_manager()

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _get_plugin_dir(self) -> Path:
        """يرجع مسار مجلد المكونات (من PluginManager أو الافتراضي)."""
        if self._plugin_manager is not None:
            return Path(self._plugin_manager.PLUGIN_DIR)
        return Path.home() / ".intellifile" / "plugins"

    def _get_config_file(self) -> Path:
        """يرجع مسار ملف الإعدادات (من PluginManager أو الافتراضي)."""
        if self._plugin_manager is not None:
            return Path(self._plugin_manager.CONFIG_FILE)
        return Path.home() / ".intellifile" / "plugins.json"

    def _get_plugin_config(self, name: str) -> dict | None:
        """يرجع config المكوّن المحدد من PluginManager إن وُجد."""
        if self._plugin_manager is None:
            return None
        # الوصول المباشر للـ configs الخاصة (آمن لأنه داخل نفس التطبيق)
        return self._plugin_manager._configs.get(name)

    def _refresh_paths_label(self) -> None:
        """يحدّث نص المسارات في الأسفل."""
        plugin_dir = self._get_plugin_dir()
        config_file = self._get_config_file()
        self.paths_label.setText(
            f"المجلد: {plugin_dir}\n"
            f"الإعدادات: {config_file}"
        )
