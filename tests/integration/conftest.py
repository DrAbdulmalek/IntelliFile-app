"""Conftest لاختبارات واجهة PySide6 — fixtures مشتركة

يوفّر:
  - qapp: fixture session-scoped لـ QApplication
  - tmp_with_files: مجلد مؤقت مع ملفات عيّنة
  - default_ruleset_path: مسار default_rules.yaml

هام: اختبارات desktop تتطلب PySide6 + libEGL.so.1. لو لم تتوفر،
تُتخطى تلقائيًا. لتشغيلها محليًا:
    LD_LIBRARY_PATH=/home/z/.local/lib/qtfix python -m pytest tests/integration/test_desktop_ux.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# التأكد من أن مسار المشروع في sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ضبط Qt env vars (مهم لـ CI/headless)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

# محاولة preload libEGL.so.1 (قد لا ينجح لكن لا يضر)
try:
    import ctypes
    _qtfix_dir = Path.home() / ".local" / "lib" / "qtfix"
    _egl_path = _qtfix_dir / "libEGL.so.1"
    if _egl_path.exists():
        ctypes.CDLL(str(_egl_path), mode=ctypes.RTLD_GLOBAL)
except Exception:
    pass


# ─── التحقق من توفر PySide6 ────────────────────────────────────────────────

def _pyside6_available() -> bool:
    """يتحقق إذا كان PySide6.QtGui قابلًا للاستيراد (يتطلب libEGL.so.1)"""
    try:
        import PySide6.QtGui  # noqa: F401
        return True
    except ImportError:
        return False


PYSIDE6_AVAILABLE = _pyside6_available()


# ─── Session-scoped QApplication ───────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    """QApplication مشترك لكل الجلسة"""
    if not PYSIDE6_AVAILABLE:
        pytest.skip("PySide6.QtGui غير متوفر — يتطلب LD_LIBRARY_PATH لـ libEGL.so.1")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ─── مجلد مؤقت مع ملفات عيّنة ─────────────────────────────────────────────

@pytest.fixture
def tmp_with_files(tmp_path):
    """مجلد مؤقت مع ملفات متنوعة لاختبارات IFM Desktop"""
    (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0 JFIF fake" + b"x" * 6000)
    (tmp_path / "notes.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "script.py").write_text("print(1)\n", encoding="utf-8")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    (tmp_path / "archive.zip").write_bytes(b"PK\x03\x04 fake zip")
    return tmp_path


# ─── Ruleset ───────────────────────────────────────────────────────────────

@pytest.fixture
def default_ruleset_path():
    """مسار ملف القواعد الافتراضي"""
    p = PROJECT_ROOT / "rules" / "default_rules.yaml"
    if not p.exists():
        pytest.skip(f"default_rules.yaml غير موجود: {p}")
    return str(p)


# ─── Skip hook لاختبارات desktop ──────────────────────────────────────────

def pytest_collection_modifyitems(config, items):
    """يتخطى اختبارات desktop لو PySide6 غير متوفر"""
    if PYSIDE6_AVAILABLE:
        return
    skip_desktop = pytest.mark.skip(
        reason="PySide6.QtGui غير متوفر — حاول: LD_LIBRARY_PATH=/home/z/.local/lib/qtfix python -m pytest"
    )
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip_desktop)
