"""IFM Plugin System — Phase E foundation.

Provides a stable extension point for adding file-processing capabilities
(OCR, NLP, classification, custom extractors) without touching core code.

Public API:
    IFMPlugin        — abstract base class all plugins must inherit
    PluginManager    — discovers, loads, and orchestrates plugins

Plugin discovery path: ~/.intellifile/plugins/*_plugin.py
Plugin config path:    ~/.intellifile/plugins.json  (name -> {config dict})
"""
from __future__ import annotations

from .base import IFMPlugin
from .manager import PluginManager

__all__ = ["IFMPlugin", "PluginManager"]
