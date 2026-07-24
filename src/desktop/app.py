"""نقطة دخول IFM Desktop — QApplication + IFMMainWindow

الاستخدام:
    python -m src.desktop.app [--base-dir DIR] [--ruleset YAML] [--dark|--light]

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QApplication

from .controllers.ifm_controller import IFMController
from .main_window import IFMMainWindow
from .theme import init_app_theme


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
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
        "--theme",
        choices=["light", "dark"],
        default="dark",
        help="السمة الافتراضية",
    )
    parser.add_argument(
        "--no-rtl",
        action="store_true",
        help="إيقاف دعم RTL (الافتراضي: RTL مفعّل)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QApplication.instance() or QApplication(sys.argv)
    init_app_theme(app, mode=args.theme, rtl=not args.no_rtl)

    controller = IFMController(
        base_dir=args.base_dir,
        ruleset_path=args.ruleset,
        undo_log_path=args.undo_log,
        action_log_path=args.action_log,
    )
    window = IFMMainWindow(controller=controller, base_dir=args.base_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
