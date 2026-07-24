"""IFM Desktop — PySide6 main window + core panels (PR-08) + progress/previews/settings (PR-09)

التصديرات:
  - IFMMainWindow: النافذة الرئيسية
  - IFMController: منسّق التكامل
  - IFMSettings: نموذج الإعدادات + persistence
  - ProgressToken: توكن إلغاء للتقدّم
  - init_app_theme, apply_theme, toggle_theme: السمات
  - Panels: InventoryPanel, FilePreviewPanel, RuleEnginePanel,
            ActionLogPanel, UndoLogPanel, WatcherPanel, SettingsPanel
  - Widgets: Sidebar, IFMStatusBar, WatcherIndicator,
             ProgressManager, RecentActionsWidget, ErrorReporter
"""
from .main_window import IFMMainWindow
from .controllers.ifm_controller import IFMController, IFMStateSnapshot, ProgressToken
from .settings import IFMSettings
from .theme import (
    apply_theme,
    apply_rtl,
    toggle_theme,
    init_app_theme,
    LIGHT_QSS,
    DARK_QSS,
    LIGHT_PALETTE,
    DARK_PALETTE,
)
from .panels.inventory_panel import InventoryPanel
from .panels.preview_panel import FilePreviewPanel
from .panels.rule_engine_panel import RuleEnginePanel
from .panels.action_log_panel import ActionLogPanel
from .panels.undo_log_panel import UndoLogPanel
from .panels.watcher_panel import WatcherPanel
from .panels.settings_panel import SettingsPanel
from .widgets.sidebar import Sidebar, NAV_ITEMS
from .widgets.status_bar import IFMStatusBar
from .widgets.watcher_indicator import WatcherIndicator
from .widgets.progress_manager import ProgressManager
from .widgets.recent_actions import RecentActionsWidget
from .widgets.error_reporter import ErrorReporter, ErrorRecord, ErrorDetailsDialog

__all__ = [
    # Main
    "IFMMainWindow",
    "IFMController",
    "IFMStateSnapshot",
    "ProgressToken",
    # Settings
    "IFMSettings",
    # Theme
    "apply_theme",
    "apply_rtl",
    "toggle_theme",
    "init_app_theme",
    "LIGHT_QSS",
    "DARK_QSS",
    "LIGHT_PALETTE",
    "DARK_PALETTE",
    # Panels
    "InventoryPanel",
    "FilePreviewPanel",
    "RuleEnginePanel",
    "ActionLogPanel",
    "UndoLogPanel",
    "WatcherPanel",
    "SettingsPanel",
    # Widgets
    "Sidebar",
    "NAV_ITEMS",
    "IFMStatusBar",
    "WatcherIndicator",
    "ProgressManager",
    "RecentActionsWidget",
    "ErrorReporter",
    "ErrorRecord",
    "ErrorDetailsDialog",
]
