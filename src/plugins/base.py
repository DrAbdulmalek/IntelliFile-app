"""IFMPlugin — abstract base class for all IFM plugins.

A plugin is a self-contained module that can:
  - Inspect and enrich file metadata during scan
  - Hook into post-scan events
  - Be configured via a JSON file (~/.intellifile/plugins.json)

Plugins are discovered by the PluginManager from ~/.intellifile/plugins/*_plugin.py
and must subclass IFMPlugin, set a non-empty ``name`` class attribute, and
implement ``initialize`` and ``process_file``.

Lifecycle:
    1. PluginManager.load_all()  → discovers + instantiates + initialize()
    2. PluginManager.process_all(file_path, metadata)  → calls process_file()
    3. PluginManager.shutdown_all()  → calls shutdown() on each
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class IFMPlugin(ABC):
    """Abstract base class for all IFM plugins.

    Subclasses MUST set ``name`` to a unique non-empty string. ``version``,
    ``description``, ``author``, and ``requires`` are optional metadata.
    """

    # ── Plugin metadata (override in subclasses) ────────────────────────
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    requires: list[str] = []

    def __init__(self) -> None:
        self._initialized: bool = False
        self._config: Dict[str, Any] = {}

    # ── Lifecycle hooks ────────────────────────────────────────────────
    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """Called once when the plugin is loaded.

        ``config`` is the per-plugin config dict from plugins.json.
        Subclasses should call ``super().initialize(config)`` first to
        store the config and mark the plugin as initialized.
        """
        self._config = config
        self._initialized = True

    @abstractmethod
    def process_file(self, file_path: Path, metadata: dict) -> dict:
        """Process a single file and return (possibly enriched) metadata.

        This is called by PluginManager.process_all() for every file in
        the inventory, in plugin-load order. The metadata dict passed in
        is the result of all previous plugins' process_file() calls, so
        later plugins can build on earlier plugins' output.

        Must return the (possibly modified) metadata dict.
        """
        ...

    def on_scan_complete(self, inventory: list) -> None:
        """Optional hook called once after a full scan completes.

        ``inventory`` is the list of all file records. Default: no-op.
        Override to perform batch post-processing.
        """
        pass

    def shutdown(self) -> None:
        """Called when the plugin is being unloaded (app exit, manager reset).

        Default: mark as uninitialized. Override to release resources
        (open files, network connections, model weights, etc.).
        """
        self._initialized = False

    # ── Introspection ──────────────────────────────────────────────────
    @property
    def is_initialized(self) -> bool:
        """True if ``initialize()`` has been called successfully."""
        return self._initialized

    @property
    def config(self) -> Dict[str, Any]:
        """The per-plugin config dict passed to ``initialize()``."""
        return self._config
