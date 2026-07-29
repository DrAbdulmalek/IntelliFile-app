"""Tests for Phase E: Plugin System + PluginPanel UI integration.

Covers:
  - PluginPanel: creation, set_plugins, refresh_from_manager, set_plugin_manager
  - PluginPanel: reload_requested signal emission
  - PluginPanel: details view updates on selection
  - PluginPanel: graceful behavior when no PluginManager attached
  - PluginManager + IFMPlugin: already covered in test_plugins.py — here we
    focus on the Qt UI layer only.
  - IFMMainWindow integration: plugins nav item exists, panel is in stack,
    _on_plugins_reload slot works end-to-end with a real PluginManager.

All tests skip automatically if PySide6 is not available.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

pytestmark = pytest.mark.desktop


# ─── Test fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fake_plugin_manager():
    """A minimal stand-in for PluginManager with the attributes PluginPanel uses."""
    from src.plugins import PluginManager

    pm = PluginManager()
    # Override paths to a tmp area (also done in plugin tests, but here we
    # just want list_plugins() to return predictable data without touching
    # the real ~/.intellifile).
    pm._plugins = {}  # clear
    pm._configs = {"alpha": {"option": "value"}}
    return pm


@pytest.fixture
def fake_plugin_metadata():
    """Predictable plugin metadata list (matches PluginManager.list_plugins shape)."""
    return [
        {
            "name": "alpha",
            "version": "1.2.0",
            "description": "Alpha test plugin",
            "author": "tester",
            "initialized": True,
        },
        {
            "name": "beta",
            "version": "0.9.1",
            "description": "Beta test plugin (not initialized)",
            "author": "another",
            "initialized": False,
        },
    ]


# ─── PluginPanel creation ─────────────────────────────────────────────────


class TestPluginPanelCreation:
    def test_creation_without_manager(self, qapp):
        """PluginPanel can be created with plugin_manager=None."""
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel(plugin_manager=None)
        assert panel.table.columnCount() == 5
        assert panel.table.rowCount() == 0
        # Reload button disabled when no manager attached
        assert not panel.reload_btn.isEnabled()
        # Open dir / config buttons always enabled (they don't need a manager)
        assert panel.open_dir_btn.isEnabled()
        assert panel.open_config_btn.isEnabled()

    def test_creation_with_manager_enables_reload(self, qapp, fake_plugin_manager):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel(plugin_manager=fake_plugin_manager)
        assert panel.reload_btn.isEnabled()

    def test_nav_item_exists_in_sidebar(self, qapp):
        """Sidebar should include 'plugins' as the last nav item."""
        from src.desktop.widgets.sidebar import NAV_ITEMS

        nav_ids = [item[0] for item in NAV_ITEMS]
        assert "plugins" in nav_ids
        assert nav_ids[-1] == "plugins"  # appended last

    def test_panel_exported_from_desktop_package(self, qapp):
        """PluginPanel should be importable from src.desktop."""
        from src.desktop import PluginPanel as ExportedPanel
        from src.desktop.panels.plugin_panel import PluginPanel

        assert ExportedPanel is PluginPanel


# ─── set_plugins ───────────────────────────────────────────────────────────


class TestPluginPanelSetPlugins:
    def test_set_plugins_populates_table(self, qapp, fake_plugin_metadata):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel()
        panel.set_plugins(fake_plugin_metadata)

        assert panel.table.rowCount() == 2
        assert "2" in panel.count_label.text()
        # First row name
        name_item = panel.table.item(0, 0)
        assert name_item.text() == "alpha"
        # Initialized status on column 4
        status_item = panel.table.item(0, 4)
        assert "مهيّأ" in status_item.text()

    def test_set_plugins_empty_clears_table(self, qapp, fake_plugin_metadata):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel()
        panel.set_plugins(fake_plugin_metadata)
        assert panel.table.rowCount() == 2

        panel.set_plugins([])
        assert panel.table.rowCount() == 0
        assert "0" in panel.count_label.text()

    def test_set_plugins_marks_uninitialized_red(self, qapp, fake_plugin_metadata):
        from PySide6.QtGui import QColor

        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel()
        panel.set_plugins(fake_plugin_metadata)

        # beta (row 1) is not initialized
        beta_status = panel.table.item(1, 4)
        assert "غير مهيّأ" in beta_status.text()
        # Foreground should be red (Qt.red)
        red_color = QColor(Qt.red)
        assert beta_status.foreground().color() == red_color


# ─── refresh_from_manager ──────────────────────────────────────────────────


class TestPluginPanelRefresh:
    def test_refresh_from_manager_without_manager_is_noop(self, qapp):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel(plugin_manager=None)
        # Should not raise
        panel.refresh_from_manager()
        assert panel.table.rowCount() == 0

    def test_refresh_pulls_metadata_from_manager(
        self, qapp, fake_plugin_manager, monkeypatch
    ):
        from src.desktop.panels.plugin_panel import PluginPanel

        # Inject a fake list_plugins result
        fake_meta = [
            {
                "name": "injected",
                "version": "9.9.9",
                "description": "injected desc",
                "author": "tester",
                "initialized": True,
            }
        ]
        monkeypatch.setattr(
            fake_plugin_manager, "list_plugins", lambda: fake_meta
        )

        panel = PluginPanel(plugin_manager=fake_plugin_manager)
        panel.refresh_from_manager()

        assert panel.table.rowCount() == 1
        assert panel.table.item(0, 0).text() == "injected"

    def test_set_plugin_manager_updates_paths_label(
        self, qapp, fake_plugin_manager, tmp_path
    ):
        from src.desktop.panels.plugin_panel import PluginPanel

        # Override paths on the manager
        fake_plugin_manager.PLUGIN_DIR = tmp_path / "plugins"
        fake_plugin_manager.CONFIG_FILE = tmp_path / "plugins.json"

        panel = PluginPanel()  # no manager at construction
        # Default paths label should mention ~/.intellifile
        assert ".intellifile" in panel.paths_label.text()

        panel.set_plugin_manager(fake_plugin_manager)
        # Now label should reflect the overridden paths
        assert str(tmp_path / "plugins") in panel.paths_label.text()
        assert str(tmp_path / "plugins.json") in panel.paths_label.text()


# ─── reload_requested signal ───────────────────────────────────────────────


class TestPluginPanelReloadSignal:
    def test_reload_button_emits_signal(self, qapp, fake_plugin_manager):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel(plugin_manager=fake_plugin_manager)
        received: list[bool] = []
        panel.reload_requested.connect(lambda: received.append(True))

        panel.reload_btn.click()
        assert received == [True]


# ─── details view on selection ─────────────────────────────────────────────


class TestPluginPanelDetailsView:
    def test_selection_shows_config_json(self, qapp, fake_plugin_manager, monkeypatch):
        from src.desktop.panels.plugin_panel import PluginPanel

        # Make list_plugins return predictable data
        fake_meta = [
            {
                "name": "alpha",
                "version": "1.0.0",
                "description": "alpha",
                "author": "tester",
                "initialized": True,
            }
        ]
        monkeypatch.setattr(
            fake_plugin_manager, "list_plugins", lambda: fake_meta
        )
        # Pre-populate a config
        fake_plugin_manager._configs = {"alpha": {"key": "value", "n": 42}}

        panel = PluginPanel(plugin_manager=fake_plugin_manager)
        panel.refresh_from_manager()

        # Explicitly set the current item (more reliable than selectRow in
        # shared-session offscreen mode) then trigger the slot.
        name_item = panel.table.item(0, 0)
        panel.table.setCurrentItem(name_item)
        panel._on_selection_changed()

        details_text = panel.details_view.toPlainText()
        assert "key" in details_text
        assert "value" in details_text
        assert "42" in details_text

    def test_no_selection_clears_details(self, qapp, fake_plugin_metadata):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel()
        panel.set_plugins(fake_plugin_metadata)

        # Select then clear
        name_item = panel.table.item(0, 0)
        panel.table.setCurrentItem(name_item)
        panel._on_selection_changed()

        panel.table.setCurrentItem(None)
        panel._on_selection_changed()
        assert panel.details_view.toPlainText() == ""

    def test_selection_without_manager_shows_fallback_message(
        self, qapp, fake_plugin_metadata
    ):
        from src.desktop.panels.plugin_panel import PluginPanel

        panel = PluginPanel(plugin_manager=None)
        panel.set_plugins(fake_plugin_metadata)

        # Select first row — no manager means no config available
        name_item = panel.table.item(0, 0)
        panel.table.setCurrentItem(name_item)
        panel._on_selection_changed()
        details = panel.details_view.toPlainText()
        # Should show fallback message about missing config
        assert "alpha" in details or "لا يوجد" in details


# ─── IFMMainWindow integration ─────────────────────────────────────────────


class TestMainWindowPluginIntegration:
    """Verify PluginPanel is wired into IFMMainWindow correctly."""

    def test_main_window_has_plugin_panel(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow
        from src.desktop.controllers.ifm_controller import IFMController

        controller = IFMController(base_dir=tmp_path)
        win = IFMMainWindow(controller=controller)

        # Panel exists
        assert hasattr(win, "plugin_panel")
        # It's in the stack at index 7
        assert win.stack.indexOf(win.plugin_panel) == 7
        # Stack has 8 widgets total (7 original + plugins)
        assert win.stack.count() == 8

    def test_main_window_nav_to_plugins(self, qapp, tmp_path):
        from src.desktop import IFMMainWindow
        from src.desktop.controllers.ifm_controller import IFMController

        controller = IFMController(base_dir=tmp_path)
        win = IFMMainWindow(controller=controller)

        # Click plugins nav button
        plugins_btn = win.sidebar.get_button("plugins")
        assert plugins_btn is not None
        plugins_btn.click()

        # Stack should now show plugin panel
        assert win.stack.currentIndex() == 7
        assert win.stack.currentWidget() is win.plugin_panel

    def test_on_plugins_reload_creates_manager(self, qapp, tmp_path, monkeypatch):
        """_on_plugins_reload should lazily create a PluginManager and call load_all."""
        from src.desktop import IFMMainWindow
        from src.desktop.controllers.ifm_controller import IFMController

        # Patch PluginManager to use a tmp PLUGIN_DIR so we don't touch real ~/.intellifile
        from src.plugins import PluginManager

        tmp_plugins_dir = tmp_path / "plugins"
        tmp_plugins_dir.mkdir()

        # Patch load_all to be deterministic (return 0 since dir is empty)
        original_init = PluginManager.__init__

        def patched_init(self):
            original_init(self)
            self.PLUGIN_DIR = tmp_plugins_dir
            self.CONFIG_FILE = tmp_path / "plugins.json"

        monkeypatch.setattr(PluginManager, "__init__", patched_init)

        controller = IFMController(base_dir=tmp_path)
        win = IFMMainWindow(controller=controller)

        # Initially no _plugin_manager attribute
        assert not getattr(win, "_plugin_manager", None)

        # Trigger reload
        win._on_plugins_reload()

        # Manager should now exist and panel should reflect it
        assert win._plugin_manager is not None
        assert win.plugin_panel.reload_btn.isEnabled()
        # Empty plugin dir means 0 plugins in table
        assert win.plugin_panel.table.rowCount() == 0
        # Status bar message should mention 0 plugins
        assert "0" in win.status_bar._message_label.text()
