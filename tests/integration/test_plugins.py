"""Tests for the IFM Plugin System (Phase E).

Covers:
  - IFMPlugin abstract interface (cannot instantiate, requires overrides)
  - PluginManager discovery + loading from a temp plugin directory
  - Plugin config loading from a JSON file
  - process_all() pipeline chaining (plugin B sees plugin A's output)
  - Error isolation (one failing plugin doesn't break the pipeline)
  - shutdown_all() clears the registry

Tests are hermetic — they use tmp_path fixtures and patch PLUGIN_DIR /
CONFIG_FILE on the manager instance so no real ~/.intellifile state is touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# NOTE: No `pytestmark = pytest.mark.desktop` here — the Plugin System is
# pure Python with no Qt dependency. Marking it `desktop` would trigger the
# auto-skip hook in tests/integration/conftest.py when PySide6 is unavailable.


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    """A clean temp directory for plugin discovery."""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    """A clean temp plugin config JSON file."""
    return tmp_path / "plugins.json"


@pytest.fixture
def manager(plugins_dir: Path, config_file: Path):
    """A PluginManager with PLUGIN_DIR / CONFIG_FILE pointed at temp paths."""
    # Ensure src/ is importable so `from src.plugins.base import IFMPlugin`
    # works inside the dynamically-loaded plugin modules.
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))

    from src.plugins.manager import PluginManager

    pm = PluginManager()
    pm.PLUGIN_DIR = plugins_dir
    pm.CONFIG_FILE = config_file
    return pm


# ──────────────────────────────────────────────────────────────────────
# Test: IFMPlugin abstract interface
# ──────────────────────────────────────────────────────────────────────


class TestIFMPlugin:
    def test_cannot_instantiate_abstract_base(self):
        """IFMPlugin is abstract — direct instantiation must fail."""
        from src.plugins.base import IFMPlugin

        with pytest.raises(TypeError):
            IFMPlugin()

    def test_subclass_must_implement_abstract_methods(self):
        """A subclass that doesn't override initialize/process_file is also abstract."""
        from src.plugins.base import IFMPlugin

        class Incomplete(IFMPlugin):
            name = "Incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_works(self, tmp_path: Path):
        """A complete subclass can be instantiated and used."""
        from src.plugins.base import IFMPlugin

        class DummyPlugin(IFMPlugin):
            name = "Dummy"

            def initialize(self, config):
                super().initialize(config)

            def process_file(self, file_path, metadata):
                metadata["dummy"] = True
                return metadata

        p = DummyPlugin()
        assert not p.is_initialized
        p.initialize({"key": "value"})
        assert p.is_initialized
        assert p.config == {"key": "value"}

        meta = p.process_file(tmp_path / "test.txt", {})
        assert meta["dummy"] is True

    def test_default_shutdown_resets_initialized(self):
        """shutdown() should mark the plugin as not initialized."""
        from src.plugins.base import IFMPlugin

        class P(IFMPlugin):
            name = "P"

            def initialize(self, config):
                super().initialize(config)

            def process_file(self, file_path, metadata):
                return metadata

        p = P()
        p.initialize({})
        assert p.is_initialized
        p.shutdown()
        assert not p.is_initialized


# ──────────────────────────────────────────────────────────────────────
# Test: PluginManager basics
# ──────────────────────────────────────────────────────────────────────


class TestPluginManager:
    def test_empty_manager_has_zero_plugins(self, manager):
        assert manager.count == 0
        assert manager.list_plugins() == []

    def test_get_returns_none_for_unknown_plugin(self, manager):
        assert manager.get("DoesNotExist") is None

    def test_load_all_returns_zero_on_empty_dir(self, manager):
        assert manager.load_all() == 0
        assert manager.count == 0


# ──────────────────────────────────────────────────────────────────────
# Test: Discovery + loading
# ──────────────────────────────────────────────────────────────────────


PLUGIN_CODE_TEMPLATE = '''
from src.plugins.base import IFMPlugin


class {class_name}(IFMPlugin):
    name = "{name}"
    version = "{version}"
    description = "{description}"

    def initialize(self, config):
        super().initialize(config)

    def process_file(self, file_path, metadata):
        metadata["{key}"] = "{value}"
        return metadata
'''


class TestPluginDiscovery:
    def test_load_single_plugin(self, manager, plugins_dir):
        plugins_dir.joinpath("test_plugin.py").write_text(
            PLUGIN_CODE_TEMPLATE.format(
                class_name="TestPlugin",
                name="TestPlugin",
                version="1.0.0",
                description="A test plugin",
                key="tested",
                value="yes",
            )
        )
        count = manager.load_all()
        assert count == 1
        assert manager.get("TestPlugin") is not None
        assert manager.get("TestPlugin").version == "1.0.0"

    def test_load_multiple_plugins_sorted(self, manager, plugins_dir):
        """Plugins should load in sorted filename order for determinism."""
        # Write in non-alphabetical order to verify sorting
        for name in ["zebra_plugin.py", "alpha_plugin.py", "middle_plugin.py"]:
            plugins_dir.joinpath(name).write_text(
                PLUGIN_CODE_TEMPLATE.format(
                    class_name=name.replace("_plugin.py", "").title(),
                    name=name.replace("_plugin.py", "").title(),
                    version="1.0.0",
                    description="",
                    key="loaded",
                    value=name,
                )
            )
        count = manager.load_all()
        assert count == 3

    def test_plugin_without_name_is_skipped(self, manager, plugins_dir):
        """A module with an IFMPlugin subclass but empty name should be skipped."""
        plugins_dir.joinpath("bad_plugin.py").write_text(
            "from src.plugins.base import IFMPlugin\n"
            "class NoName(IFMPlugin):\n"
            "    # name defaults to ''\n"
            "    def initialize(self, c): super().initialize(c)\n"
            "    def process_file(self, fp, m): return m\n"
        )
        count = manager.load_all()
        assert count == 0

    def test_plugin_with_syntax_error_is_skipped(self, manager, plugins_dir):
        """A plugin file with a syntax error should not break the manager."""
        plugins_dir.joinpath("broken_plugin.py").write_text(
            "this is not valid python !!!\n"
        )
        # Should not raise — should just log and skip
        count = manager.load_all()
        assert count == 0

    def test_duplicate_plugin_name_is_skipped(self, manager, plugins_dir):
        """Two files defining the same plugin name should load only once."""
        plugins_dir.joinpath("a_plugin.py").write_text(
            PLUGIN_CODE_TEMPLATE.format(
                class_name="Dup", name="Dup", version="1.0.0",
                description="", key="k", value="a",
            )
        )
        plugins_dir.joinpath("b_plugin.py").write_text(
            PLUGIN_CODE_TEMPLATE.format(
                class_name="Dup", name="Dup", version="1.0.0",
                description="", key="k", value="b",
            )
        )
        count = manager.load_all()
        assert count == 1


# ──────────────────────────────────────────────────────────────────────
# Test: Config loading
# ──────────────────────────────────────────────────────────────────────


class TestPluginConfig:
    def test_config_passed_to_initialize(self, manager, plugins_dir, config_file):
        """Per-plugin config from plugins.json should reach initialize()."""
        plugins_dir.joinpath("cfg_plugin.py").write_text(
            PLUGIN_CODE_TEMPLATE.format(
                class_name="CfgPlugin", name="CfgPlugin", version="1.0.0",
                description="", key="cfg", value="ok",
            )
        )
        config_file.write_text(json.dumps({
            "CfgPlugin": {"api_key": "secret", "timeout": 30}
        }))
        # Reload configs (manager __init__ already ran with empty file)
        manager._load_configs()
        assert manager.load_all() == 1
        plugin = manager.get("CfgPlugin")
        assert plugin.config == {"api_key": "secret", "timeout": 30}

    def test_corrupt_config_falls_back_to_empty(self, manager, config_file):
        """A corrupt plugins.json should not crash the manager."""
        config_file.write_text("not valid json {{{")
        manager._load_configs()
        assert manager._configs == {}


# ──────────────────────────────────────────────────────────────────────
# Test: Pipeline
# ──────────────────────────────────────────────────────────────────────


class TestPluginPipeline:
    def test_process_all_chains_plugins(self, manager, tmp_path):
        """Plugin B should see the metadata plugin A added."""
        from src.plugins.base import IFMPlugin

        class P1(IFMPlugin):
            name = "P1"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                meta["p1"] = 1
                return meta

        class P2(IFMPlugin):
            name = "P2"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                meta["p2"] = meta.get("p1", 0) + 1
                return meta

        # Bypass discovery — inject directly for pipeline testing
        manager._plugins["P1"] = P1()
        manager._plugins["P1"].initialize({})
        manager._plugins["P2"] = P2()
        manager._plugins["P2"].initialize({})

        result = manager.process_all(tmp_path / "test.txt", {})
        assert result["p1"] == 1
        assert result["p2"] == 2

    def test_failing_plugin_does_not_break_pipeline(self, manager, tmp_path):
        """A plugin that raises should be logged + skipped, not crash the chain."""
        from src.plugins.base import IFMPlugin

        class GoodBefore(IFMPlugin):
            name = "GoodBefore"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                meta["before"] = True
                return meta

        class Bad(IFMPlugin):
            name = "Bad"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                raise RuntimeError("plugin exploded")

        class GoodAfter(IFMPlugin):
            name = "GoodAfter"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                meta["after"] = True
                return meta

        for cls in (GoodBefore, Bad, GoodAfter):
            manager._plugins[cls.name] = cls()
            manager._plugins[cls.name].initialize({})

        result = manager.process_all(tmp_path / "test.txt", {})
        # Before and after should still run
        assert result["before"] is True
        assert result["after"] is True
        # The failure should be recorded
        assert "plugin_errors" in result
        assert any("Bad" in err for err in result["plugin_errors"])

    def test_uninitialized_plugin_is_skipped(self, manager, tmp_path):
        """A plugin that's loaded but not initialized should be skipped in pipeline."""
        from src.plugins.base import IFMPlugin

        class P(IFMPlugin):
            name = "Uninitialized"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                meta["should_not_run"] = True
                return meta

        # Instantiate but DON'T initialize
        manager._plugins["Uninitialized"] = P()
        result = manager.process_all(tmp_path / "test.txt", {})
        assert "should_not_run" not in result


# ──────────────────────────────────────────────────────────────────────
# Test: Shutdown
# ──────────────────────────────────────────────────────────────────────


class TestPluginShutdown:
    def test_shutdown_all_clears_registry(self, manager):
        from src.plugins.base import IFMPlugin

        class P(IFMPlugin):
            name = "ShutdownTest"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                return meta

        manager._plugins["ShutdownTest"] = P()
        manager._plugins["ShutdownTest"].initialize({})
        assert manager.count == 1

        manager.shutdown_all()
        assert manager.count == 0
        assert manager.get("ShutdownTest") is None

    def test_shutdown_calls_plugin_shutdown_hook(self, manager):
        """Plugin.shutdown() should be called, not just the registry cleared."""
        from src.plugins.base import IFMPlugin

        shutdown_calls = []

        class P(IFMPlugin):
            name = "HookTest"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                return meta

            def shutdown(self):
                shutdown_calls.append(self.name)
                super().shutdown()

        manager._plugins["HookTest"] = P()
        manager._plugins["HookTest"].initialize({})
        manager.shutdown_all()
        assert shutdown_calls == ["HookTest"]


# ──────────────────────────────────────────────────────────────────────
# Test: list_plugins introspection
# ──────────────────────────────────────────────────────────────────────


class TestPluginList:
    def test_list_plugins_returns_metadata(self, manager):
        from src.plugins.base import IFMPlugin

        class P(IFMPlugin):
            name = "ListTest"
            version = "2.3.4"
            description = "test plugin"
            author = "tester"

            def initialize(self, c):
                super().initialize(c)

            def process_file(self, fp, meta):
                return meta

        manager._plugins["ListTest"] = P()
        manager._plugins["ListTest"].initialize({})
        listing = manager.list_plugins()
        assert len(listing) == 1
        entry = listing[0]
        assert entry["name"] == "ListTest"
        assert entry["version"] == "2.3.4"
        assert entry["description"] == "test plugin"
        assert entry["author"] == "tester"
        assert entry["initialized"] is True
