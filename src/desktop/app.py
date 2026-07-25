"""نقطة دخول IFM Desktop — QApplication + IFMMainWindow

الاستخدام:
    python -m src.desktop.app [--base-dir DIR] [--ruleset YAML] [--dark|--light]
                              [--settings PATH] [--version]

PR-08 من development-roadmap-v1.0 (IFM Phase C)
PR-09 من development-roadmap-v1.0 (progress + previews + settings)
PR-10 من development-roadmap-v1.0 (polish + keyboard shortcuts + crash recovery + v2.2.0)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src import __version__

from .controllers.ifm_controller import IFMController
from .crash_recovery import CrashRecovery
from .main_window import IFMMainWindow
from .settings import IFMSettings
from .theme import init_app_theme


def parse_args(argv: list | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IntelliFile Desktop")
    parser.add_argument(
        "--base-dir",
        default=str(Path.cwd()),
        help="المجلد الأساسي للعمليات (افتراضيًا: المجلد الحالي)",
    )
    parser.add_argument(
        "--ruleset",
        default=None,
        help="مسار ملف قواعد YAML",
    )
    parser.add_argument(
        "--undo-log",
        default=None,
        help="مسار ملف سجل التراجع JSON",
    )
    parser.add_argument(
        "--action-log",
        default=None,
        help="مسار ملف سجل الإجراءات JSON",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="مسار ملف الإعدادات JSON (افتراضيًا: ~/.ifm_settings.json)",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark"],
        default=None,
        help="تجاوز السمة من الإعدادات (light/dark)",
    )
    parser.add_argument(
        "--no-rtl",
        action="store_true",
        help="إيقاف دعم RTL (الافتراضي: من الإعدادات)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"IntelliFile {__version__}",
        help="إظهار الإصدار والخروج",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # تحميل الإعدادات (PR-09)
    settings_path = Path(args.settings) if args.settings else None
    settings = IFMSettings.load(settings_path)

    # تجاوزات من سطر الأوامر
    if args.theme:
        settings.dark_mode = (args.theme == "dark")
    if args.no_rtl:
        settings.rtl = False

    app = QApplication.instance() or QApplication(sys.argv)
    init_app_theme(
        app,
        mode="dark" if settings.dark_mode else "light",
        rtl=settings.rtl,
    )

    # PR-10: تركيب معالج الأعطال العام قبل إنشاء الـ controller
    crash_recovery = CrashRecovery(parent=app)

    controller = IFMController(
        base_dir=args.base_dir,
        ruleset_path=args.ruleset,
        undo_log_path=args.undo_log,
        action_log_path=args.action_log,
        settings=settings,
    )
    window = IFMMainWindow(
        controller=controller,
        base_dir=args.base_dir,
        crash_recovery=crash_recovery,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
