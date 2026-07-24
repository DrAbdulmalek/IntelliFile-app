"""IFM Desktop — PySide6 main window + core panels (PR-08)

التصديرات:
  - IFMMainWindow: النافذة الرئيسية
  - IFMController: منسّق التكامل
  - init_app_theme, apply_theme, toggle_theme: السمات
  - Panels: InventoryPanel, RuleEnginePanel, ActionLogPanel, UndoLogPanel, WatcherPanel
"""
from .main_window import IFMMainWindow
from .controllers.ifm_controller import IFMController, IFMStateSnapshot
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
from .panels.rule_engine_panel import RuleEnginePanel
from .panels.action_log_panel import ActionLogPanel
from .panels.undo_log_panel import UndoLogPanel
from .panels.watcher_panel import WatcherPanel
from .widgets.sidebar import Sidebar, NAV_ITEMS
from .widgets.status_bar import IFMStatusBar
from .widgets.watcher_indicator import WatcherIndicator

__all__ = [
    "IFMMainWindow",
    "IFMController",
    "IFMStateSnapshot",
    "apply_theme",
    "apply_rtl",
    "toggle_theme",
    "init_app_theme",
    "LIGHT_QSS",
    "DARK_QSS",
    "LIGHT_PALETTE",
    "DARK_PALETTE",
    "InventoryPanel",
    "RuleEnginePanel",
    "ActionLogPanel",
    "UndoLogPanel",
    "WatcherPanel",
    "Sidebar",
    "NAV_ITEMS",
    "IFMStatusBar",
    "WatcherIndicator",
]
