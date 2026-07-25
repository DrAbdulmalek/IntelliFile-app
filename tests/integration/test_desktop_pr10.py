"""Tests for PR-10: Desktop polish + keyboard shortcuts + crash recovery + v2.2.0.

Tests cover:
  - ShortcutManager: creation, signal emission, enable/disable.
  - CrashRecovery: init, session roundtrip, crash log rotation.
  - Version: __version__ == "2.2.0" (semver format).
  - MainWindow integration: shortcuts + crash recovery wired in.
  - CLI: --version flag works.

All tests skip automatically if PySide6 is not available.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.desktop


# ─── Keyboard Shortcuts ────────────────────────────────────────────────────


class TestKeyboardShortcuts:
    def test_shortcut_manager_creation(self, qapp):
        """ShortcutManager should register 8 global shortcuts."""
        from src.desktop.keyboard_shortcuts import SHORTCUTS, ShortcutManager

        # qapp (QApplication) is a valid QObject parent
        sm = ShortcutManager(qapp)
        assert sm.get_shortcut_count() == 8
        assert len(SHORTCUTS) == 8

    def test_shortcut_signals_emitted(self, qapp):
        """Each signal should be emitted independently."""
        from src.desktop.keyboard_shortcuts import ShortcutManager

        sm = ShortcutManager(qapp)

        emitted = []

        sm.refresh_requested.connect(lambda: emitted.append("refresh"))
        sm.scan_requested.connect(lambda: emitted.append("scan"))
        sm.undo_requested.connect(lambda: emitted.append("undo"))
        sm.cancel_requested.connect(lambda: emitted.append("cancel"))

        sm.refresh_requested.emit()
        sm.scan_requested.emit()
        sm.undo_requested.emit()
        sm.cancel_requested.emit()

        assert emitted == ["refresh", "scan", "undo", "cancel"]

    def test_shortcut_enable_disable(self, qapp):
        """set_shortcut_enabled should toggle a shortcut."""
        from src.desktop.keyboard_shortcuts import ShortcutManager

        sm = ShortcutManager(qapp)

        # All enabled by default
        info = sm.get_shortcuts_info()
        assert all(s["enabled"] for s in info)

        # Disable Ctrl+R
        sm.set_shortcut_enabled("Ctrl+R", False)
        info = {s["sequence"]: s["enabled"] for s in sm.get_shortcuts_info()}
        assert info["Ctrl+R"] is False
        assert info["F5"] is True  # others still enabled

    def test_shortcut_invalid_seq_raises(self, qapp):
        """Passing an unknown sequence should raise KeyError."""
        from src.desktop.keyboard_shortcuts import ShortcutManager

        sm = ShortcutManager(qapp)
        with pytest.raises(KeyError):
            sm.set_shortcut_enabled("Ctrl+XYZ", False)


# ─── Crash Recovery ────────────────────────────────────────────────────────


class TestCrashRecovery:
    def test_crash_recovery_init(self, qapp, tmp_path):
        """CrashRecovery should start with empty session."""
        from src.desktop import crash_recovery

        with patch.object(crash_recovery, "SESSION_FILE", tmp_path / "session.json"), \
             patch.object(crash_recovery, "CRASH_LOG_DIR", tmp_path / "crashes"):
            cr = crash_recovery.CrashRecovery()
            assert cr._session == {}
            assert cr.get_session_value("nonexistent", "default") == "default"
            cr.cleanup()

    def test_session_roundtrip(self, qapp, tmp_path):
        """Session values should persist across save/load."""
        from src.desktop import crash_recovery

        session_file = tmp_path / "session.json"
        with patch.object(crash_recovery, "SESSION_FILE", session_file), \
             patch.object(crash_recovery, "CRASH_LOG_DIR", tmp_path / "crashes"):
            cr1 = crash_recovery.CrashRecovery()
            cr1.set_session_value("last_directory", "/home/user/Downloads")
            cr1.set_session_value("last_panel", 3)
            cr1._save_session()

            # New instance should load the saved session
            cr2 = crash_recovery.CrashRecovery()
            session = cr2.load_session()
            assert session.get("last_directory") == "/home/user/Downloads"
            assert session.get("last_panel") == 3
            cr2.cleanup()

    def test_crash_log_rotation(self, qapp, tmp_path):
        """Old crash logs should be removed, keeping only MAX_CRASH_LOGS."""
        from src.desktop import crash_recovery

        crash_dir = tmp_path / "crashes"
        crash_dir.mkdir(parents=True, exist_ok=True)

        with patch.object(crash_recovery, "SESSION_FILE", tmp_path / "session.json"), \
             patch.object(crash_recovery, "CRASH_LOG_DIR", crash_dir):
            cr = crash_recovery.CrashRecovery()

            # Simulate 15 crash logs
            for i in range(15):
                path = crash_dir / f"crash_2026-01-{i + 1:02d}T10-00-00.json"
                path.write_text('{"test": true}')
                # Set mtime so rotation sorts correctly
                import os
                os.utime(path, (i, i))

            cr._rotate_crash_logs()
            remaining = list(crash_dir.glob("crash_*.json"))
            assert len(remaining) == crash_recovery.MAX_CRASH_LOGS
            cr.cleanup()

    def test_get_last_crash_returns_none_when_empty(self, qapp, tmp_path):
        """get_last_crash should return None when no crash logs exist."""
        from src.desktop import crash_recovery

        with patch.object(crash_recovery, "SESSION_FILE", tmp_path / "session.json"), \
             patch.object(crash_recovery, "CRASH_LOG_DIR", tmp_path / "crashes"):
            cr = crash_recovery.CrashRecovery()
            assert cr.has_crash_logs() is False
            assert cr.get_last_crash() is None
            cr.cleanup()


# ─── Version ───────────────────────────────────────────────────────────────


class TestVersion:
    def test_version_is_semver(self):
        """__version__ should follow semver MAJOR.MINOR.PATCH."""
        from src import __version__
        parts = __version__.split(".")
        assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}: {parts}"
        assert all(p.isdigit() for p in parts), f"Non-digit parts: {parts}"
        assert __version__ == "2.2.0"

    def test_app_metadata(self):
        """App name + description should be set."""
        from src import __app_description__, __app_name__
        assert __app_name__ == "IntelliFile"
        assert "file manager" in __app_description__.lower()


# ─── CLI ───────────────────────────────────────────────────────────────────


class TestCLI:
    def test_version_flag(self, qapp):
        """--version flag should print version and exit."""
        from src.desktop.app import parse_args

        with pytest.raises(SystemExit) as exc_info:
            parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_version_flag_output(self, qapp, capsys):
        """--version should print 'IntelliFile <version>' to stdout."""
        from src import __version__
        from src.desktop.app import parse_args

        with pytest.raises(SystemExit):
            parse_args(["--version"])

        captured = capsys.readouterr()
        assert __version__ in captured.out
        assert "IntelliFile" in captured.out


# ─── MainWindow Integration ────────────────────────────────────────────────


class TestMainWindowPR10:
    def test_main_window_has_shortcut_manager(self, qapp, tmp_path):
        """MainWindow should have a ShortcutManager with 8 shortcuts."""
        from src.desktop.controllers.ifm_controller import IFMController
        from src.desktop.main_window import IFMMainWindow

        with patch("src.desktop.crash_recovery.SESSION_FILE", tmp_path / "session.json"), \
             patch("src.desktop.crash_recovery.CRASH_LOG_DIR", tmp_path / "crashes"):
            controller = IFMController(base_dir=str(tmp_path))
            window = IFMMainWindow(controller=controller, base_dir=str(tmp_path))
            assert hasattr(window, "shortcut_manager")
            assert window.shortcut_manager.get_shortcut_count() == 8
            assert hasattr(window, "crash_recovery")
            window.crash_recovery.cleanup()

    def test_main_window_close_saves_session(self, qapp, tmp_path):
        """closeEvent should save last_directory + last_panel to session."""
        from PySide6.QtGui import QCloseEvent

        from src.desktop import crash_recovery
        from src.desktop.controllers.ifm_controller import IFMController
        from src.desktop.main_window import IFMMainWindow

        session_file = tmp_path / "session.json"
        with patch.object(crash_recovery, "SESSION_FILE", session_file), \
             patch.object(crash_recovery, "CRASH_LOG_DIR", tmp_path / "crashes"):
            controller = IFMController(base_dir=str(tmp_path))
            window = IFMMainWindow(controller=controller, base_dir=str(tmp_path))

            # Simulate close
            event = QCloseEvent()
            window.closeEvent(event)

            # Session file should exist and contain last_directory
            assert session_file.exists()
            import json
            data = json.loads(session_file.read_text(encoding="utf-8"))
            assert "last_directory" in data
            assert "last_panel" in data
            assert "last_theme" in data
