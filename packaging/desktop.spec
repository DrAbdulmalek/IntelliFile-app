# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for IntelliFile Desktop (Linux-first).

الاستخدام:
    cd packaging
    pyinstaller desktop.spec

الناتج:
    dist/IntelliFile-Desktop/intellifile-desktop  (Linux ELF binary)
    dist/IntelliFile-Desktop/  (مجلد يحتوي كل الـ dependencies)

لتحويله إلى AppImage لاحقًا:
    appimagetool dist/IntelliFile-Desktop IntelliFile-Desktop.AppImage

ملاحظات:
  - Linux-first: يُجرَّب أولاً على Debian/Ubuntu. Windows/macOS تدعم
    عبر cross-platform Qt wheels لكن تحتاج testing منفصل.
  - excludes: تجنّب حزم tkinter و matplotlib (غير مستخدمة في IFM Desktop).
  - hiddenimports: قائمة الوحدات التي يصعب على PyInstaller اكتشافها
    ديناميكيًا بسبب imports متأخرة في PySide6 + IFM.
"""
from pathlib import Path

block_cipher = None

# المسارات النسبية لمجلد المشروع
PROJECT_ROOT = Path(SPECPATH).parent  # noqa: F821  (PyInstaller injects SPECPATH)
SRC = PROJECT_ROOT / "src"
DESKTOP = SRC / "desktop"

a = Analysis(
    ["../src/desktop/app.py"],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(SRC / "desktop" / "theme.py"), "desktop"),
        (str(PROJECT_ROOT / "rules" / "default_rules.yaml"), "rules"),
    ],
    hiddenimports=[
        # desktop modules
        "desktop.controllers.ifm_controller",
        "desktop.panels.action_log_panel",
        "desktop.panels.inventory_panel",
        "desktop.panels.preview_panel",
        "desktop.panels.rule_engine_panel",
        "desktop.panels.settings_panel",
        "desktop.panels.undo_log_panel",
        "desktop.panels.watcher_panel",
        "desktop.widgets.sidebar",
        "desktop.widgets.status_bar",
        "desktop.widgets.watcher_indicator",
        "desktop.widgets.progress_manager",
        "desktop.widgets.error_reporter",
        "desktop.widgets.recent_actions",
        "desktop.settings",
        "desktop.theme",
        "desktop.keyboard_shortcuts",
        "desktop.crash_recovery",
        # core modules
        "core.file_inventory",
        "core.metadata_extractor",
        "core.rule_engine",
        "core.rule_schemas",
        "core.undo_log",
        "core.action_log",
        "core.safe_mover",
        "core.duplicate_detector",
        "core.watcher",
        "core.dry_run_reporter",
        # PySide6 plugins
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.random._examples", "IPython", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="intellifile-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed mode
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# مجلد واحد (not onefile) — أفضل لـ Linux AppImage wrapping
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="IntelliFile-Desktop",
)
