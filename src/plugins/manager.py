"""PluginManager — discovers, loads, and orchestrates IFM plugins.

Discovery:
    Scans ``~/.intellifile/plugins/*_plugin.py`` for files containing a
    class that subclasses IFMPlugin and has a non-empty ``name``.

Config:
    Reads ``~/.intellifile/plugins.json`` (a JSON object mapping
    plugin name -> config dict) and passes each plugin's config to its
    ``initialize()`` method.

Pipeline:
    ``process_all(file_path, metadata)`` calls ``process_file()`` on each
    loaded + initialized plugin, in load order. Each plugin receives the
    metadata dict from the previous plugin, so plugins can chain.

Error handling:
    - Plugin load failures (import errors, missing IFMPlugin subclass)
      are logged and skipped — one bad plugin never breaks the manager.
    - Plugin ``process_file()`` failures are logged and appended to
      ``metadata["plugin_errors"]`` — the pipeline continues with the
      metadata unchanged for that plugin.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import IFMPlugin

logger = logging.getLogger(__name__)


class PluginManager:
    """Manages plugin discovery, loading, and the file-processing pipeline."""

    # Default plugin directory — overridden in tests via instance assignment.
    PLUGIN_DIR: Path = Path.home() / ".intellifile" / "plugins"
    CONFIG_FILE: Path = Path.home() / ".intellifile" / "plugins.json"

    def __init__(self) -> None:
        self._plugins: Dict[str, IFMPlugin] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._load_configs()

    # ── Config loading ─────────────────────────────────────────────────
    def _load_configs(self) -> None:
        """Load per-plugin configs from CONFIG_FILE (JSON object).

        On any parse error: log a warning and fall back to empty configs
        (do not raise — a corrupt config file should never break startup).
        """
        if not self.CONFIG_FILE.exists():
            return
        try:
            with open(self.CONFIG_FILE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._configs = {
                    k: v for k, v in loaded.items() if isinstance(v, dict)
                }
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load plugin configs from %s: %s",
                           self.CONFIG_FILE, e)
            self._configs = {}

    # ── Discovery + loading ────────────────────────────────────────────
    def _discover_plugins(self) -> List[Path]:
        """Return list of plugin files (sorted for deterministic load order)."""
        self.PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        return sorted(self.PLUGIN_DIR.glob("*_plugin.py"))

    def _load_plugin_module(self, path: Path) -> Optional[type]:
        """Import the plugin module from ``path`` and return its IFMPlugin subclass.

        Returns None if:
          - The module fails to import (logged as warning)
          - The module contains no IFMPlugin subclass with a non-empty name
        """
        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if not spec or not spec.loader:
                logger.warning("Could not create spec for plugin %s", path)
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning("Failed to load plugin from %s: %s", path, e)
            return None

        # Find the first IFMPlugin subclass with a non-empty name.
        # Skip IFMPlugin itself and any abstract intermediate classes.
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, IFMPlugin)
                    and attr is not IFMPlugin
                    and getattr(attr, "name", "")):
                return attr
        logger.warning("No valid IFMPlugin subclass found in %s", path)
        return None

    def load_all(self) -> int:
        """Discover, instantiate, and initialize all plugins.

        Returns the number of successfully loaded plugins. Plugins that
        fail to import, have no IFMPlugin subclass, or fail during
        ``initialize()`` are skipped (logged).
        """
        loaded = 0
        for plugin_file in self._discover_plugins():
            plugin_class = self._load_plugin_module(plugin_file)
            if plugin_class is None:
                continue
            name = plugin_class.name
            if name in self._plugins:
                logger.info("Skipping duplicate plugin name: %s (in %s)",
                            name, plugin_file)
                continue
            instance = plugin_class()
            config = self._configs.get(name, {})
            try:
                instance.initialize(config)
            except Exception as e:
                logger.error("Failed to initialize plugin %s: %s", name, e)
                continue
            self._plugins[name] = instance
            loaded += 1
            logger.info("Loaded plugin: %s v%s", name, instance.version)
        return loaded

    # ── Accessors ──────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[IFMPlugin]:
        """Return the loaded plugin with the given name, or None."""
        return self._plugins.get(name)

    def list_plugins(self) -> List[Dict[str, Any]]:
        """Return a list of metadata dicts for all loaded plugins."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "initialized": p.is_initialized,
            }
            for p in self._plugins.values()
        ]

    # ── Pipeline ───────────────────────────────────────────────────────
    def process_all(self, file_path: Path, metadata: dict) -> dict:
        """Run all initialized plugins' ``process_file()`` on a single file.

        Plugins are called in load order. Each plugin receives the metadata
        dict from the previous plugin. Plugin failures are logged and
        appended to ``metadata["plugin_errors"]`` — the pipeline continues
        with the metadata unchanged for that plugin.
        """
        for name, plugin in self._plugins.items():
            if not plugin.is_initialized:
                continue
            try:
                metadata = plugin.process_file(file_path, metadata)
            except Exception as e:
                logger.error("Plugin %s failed on %s: %s", name, file_path, e)
                metadata.setdefault("plugin_errors", []).append(f"{name}: {e}")
        return metadata

    def on_scan_complete(self, inventory: list) -> None:
        """Notify all plugins that a scan has completed."""
        for plugin in self._plugins.values():
            try:
                plugin.on_scan_complete(inventory)
            except Exception as e:
                logger.error("Plugin %s on_scan_complete failed: %s",
                             plugin.name, e)

    # ── Shutdown ───────────────────────────────────────────────────────
    def shutdown_all(self) -> None:
        """Call ``shutdown()`` on every loaded plugin, then clear the registry."""
        for plugin in self._plugins.values():
            try:
                plugin.shutdown()
            except Exception as e:
                logger.error("Plugin %s shutdown failed: %s", plugin.name, e)
        self._plugins.clear()

    @property
    def count(self) -> int:
        """Number of currently loaded plugins."""
        return len(self._plugins)
