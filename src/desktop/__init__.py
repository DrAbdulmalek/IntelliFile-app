"""IFM Desktop — PySide6 main window + core panels (PR-08) + progress/previews/settings (PR-09)
   + keyboard shortcuts/crash recovery (PR-10)

التصديرات:
  - IFMMainWindow: النافذة الرئيسية
  - IFMController: منسّق التكامل
  - IFMSettings: نموذج الإعدادات + persistence
  - ProgressToken: توكن إلغاء للتقدّم
  - ShortcutManager: اختصارات لوحة المفاتيح (PR-10)
  - CrashRecovery: استرداد الأعطال + حفظ الجلسة (PR-10)
  - init_app_theme, apply_theme, toggle_theme: السمات
  - Panels: InventoryPanel, FilePreviewPanel, RuleEnginePanel,
            ActionLogPanel, UndoLogPanel, WatcherPanel, SettingsPanel
  - Widgets: Sidebar, IFMStatusBar, WatcherIndicator,
             ProgressManager, RecentActionsWidget, ErrorReporter
"""
from .controllers.ifm_controller import IFMController, IFMStateSnapshot, ProgressToken
from .crash_recovery import CrashRecovery
from .keyboard_shortcuts import SHORTCUTS, ShortcutManager
from .main_window import IFMMainWindow
from .panels.action_log_panel import ActionLogPanel
from .panels.inventory_panel import InventoryPanel
from .panels.plugin_panel import PluginPanel
from .panels.preview_panel import FilePreviewPanel
from .panels.rule_engine_panel import RuleEnginePanel
from .panels.settings_panel import SettingsPanel
from .panels.undo_log_panel import UndoLogPanel
from .panels.watcher_panel import WatcherPanel
from .settings import IFMSettings
from .theme import (
    DARK_PALETTE,
    DARK_QSS,
    LIGHT_PALETTE,
    LIGHT_QSS,
    apply_rtl,
    apply_theme,
    init_app_theme,
    toggle_theme,
)
from .widgets.error_reporter import ErrorDetailsDialog, ErrorRecord, ErrorReporter
from .widgets.progress_manager import ProgressManager
from .widgets.recent_actions import RecentActionsWidget
from .widgets.sidebar import NAV_ITEMS, Sidebar
from .widgets.status_bar import IFMStatusBar
from .widgets.watcher_indicator import WatcherIndicator

__all__ = [
    # Main
    "CrashRecovery",
    "IFMController",
    "IFMMainWindow",
    "IFMStateSnapshot",
    "ProgressToken",
    "SHORTCUTS",
    "ShortcutManager",
    # Settings
    "IFMSettings",
    # Theme
    "DARK_PALETTE",
    "DARK_QSS",
    "LIGHT_PALETTE",
    "LIGHT_QSS",
    "apply_rtl",
    "apply_theme",
    "init_app_theme",
    "toggle_theme",
    # Panels
    "ActionLogPanel",
    "FilePreviewPanel",
    "InventoryPanel",
    "PluginPanel",
    "RuleEnginePanel",
    "SettingsPanel",
    "UndoLogPanel",
    "WatcherPanel",
    # Widgets
    "ErrorDetailsDialog",
    "ErrorRecord",
    "ErrorReporter",
    "IFMStatusBar",
    "NAV_ITEMS",
    "ProgressManager",
    "RecentActionsWidget",
    "Sidebar",
    "WatcherIndicator",
]
