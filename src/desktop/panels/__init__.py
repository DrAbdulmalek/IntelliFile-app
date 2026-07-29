"""IFM Desktop Panels — اللوحات الأساسية للنافذة الرئيسية"""
from .action_log_panel import ActionLogPanel
from .inventory_panel import InventoryPanel
from .plugin_panel import PluginPanel
from .rule_engine_panel import RuleEnginePanel
from .undo_log_panel import UndoLogPanel
from .watcher_panel import WatcherPanel

__all__ = [
    "ActionLogPanel",
    "InventoryPanel",
    "PluginPanel",
    "RuleEnginePanel",
    "UndoLogPanel",
    "WatcherPanel",
]
