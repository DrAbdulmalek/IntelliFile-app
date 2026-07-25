"""استرداد الأعطال + حفظ الجلسة + معالج الأخطاء العام (PR-10).

يوفّر `CrashRecovery`:

  1. **حفظ الجلسة** عند الخروج (آخر مجلد مفتوح، آخر لوحة نشطة، آخر تحديد).
  2. **استعادة الجلسة** عند بدء التشغيل التالي.
  3. **التقاط الأعطال** عبر `sys.excepthook` وكتابتها إلى `~/.intellifile/crashes/`.
  4. **تدوير سجلات الأعطال** (يبقي آخر 10 سجلات فقط).
  5. **إشارة `crash_detected`** لإظهار حوار استرداد للمستخدم.

التصميم:
  - كل المسارات قابلة للتجاوز من الاختبارات عبر monkeypatch.
  - لا يُ force إعادة تحميل الـ session تلقائيًا؛ يستدعيها MainWindow يدويًا.
  - معالج SIGINT/SIGTERM لإنهاء ناعم عند الإيقاف من الـ terminal.

PR-10 من development-roadmap-v1.0 (Desktop polish + release checklist)
"""
from __future__ import annotations

import atexit
import json
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

# المسارات الافتراضية (قابلة للتجاوز من الاختبارات)
CRASH_LOG_DIR = Path.home() / ".intellifile" / "crashes"
SESSION_FILE = Path.home() / ".intellifile" / "session.json"
MAX_CRASH_LOGS = 10


class CrashRecovery(QObject):
    """استرداد الأعطال + حفظ الجلسة + معالج الأخطاء العام."""

    # تُصدر عند التقاط عطل (المعامل = مسار سجل العطل)
    crash_detected = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._session: dict[str, Any] = {}
        self._dirty = False
        self._original_excepthook = None
        self._setup_handlers()

    # ─── تركيب المعالجات ────────────────────────────────────────────────────

    def _setup_handlers(self) -> None:
        """تركيب معالجات atexit + signal + excepthook."""
        atexit.register(self._save_session)

        # SIGINT/SIGTERM للإنهاء الناعم
        try:
            signal.signal(signal.SIGINT, self._on_signal)
            signal.signal(signal.SIGTERM, self._on_signal)
        except (ValueError, OSError):
            # قد تفشل خارج الخيط الرئيسي — نتجاهل بأمان
            pass

        # معالج الأخطاء العام
        self._original_excepthook = sys.excepthook
        sys.excepthook = self._global_excepthook

    def _on_signal(self, signum: int, frame: Any) -> None:
        """إنهاء ناعم عند استقبال إشارة."""
        self._save_session()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _global_excepthook(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        """كتابة الاستثناء غير المُلتقط إلى سجل عطل."""
        try:
            CRASH_LOG_DIR.mkdir(parents=True, exist_ok=True)
            self._rotate_crash_logs()

            timestamp = datetime.now().isoformat()
            crash_path = CRASH_LOG_DIR / f"crash_{timestamp.replace(':', '-')}.json"

            crash_data = {
                "timestamp": timestamp,
                "exception_type": exc_type.__name__,
                "message": str(exc_value),
                "traceback": "".join(
                    traceback.format_exception(exc_type, exc_value, exc_tb)
                ),
            }

            with open(crash_path, "w", encoding="utf-8") as f:
                json.dump(crash_data, f, ensure_ascii=False, indent=2)

            self.crash_detected.emit(str(crash_path))
        except Exception:
            # لا نريد أن يفشل معالج الأخطاء نفسه
            pass
        finally:
            # استدعاء المعالج الأصلي للحفاظ على السلوك الافتراضي
            if self._original_excepthook is not None:
                self._original_excepthook(exc_type, exc_value, exc_tb)

    def _rotate_crash_logs(self) -> None:
        """يبقي آخر MAX_CRASH_LOGS سجلات فقط."""
        if not CRASH_LOG_DIR.exists():
            return
        logs = sorted(
            CRASH_LOG_DIR.glob("crash_*.json"), key=lambda p: p.stat().st_mtime
        )
        for old in logs[:-MAX_CRASH_LOGS]:
            try:
                old.unlink()
            except OSError:
                pass

    # ─── حفظ/استعادة الجلسة ──────────────────────────────────────────────────

    def set_session_value(self, key: str, value: Any) -> None:
        """تعيين قيمة في الجلسة وتعليمها كـ dirty."""
        self._session[key] = value
        self._dirty = True

    def get_session_value(self, key: str, default: Any = None) -> Any:
        """قراءة قيمة من الجلسة، default إن لم تكن موجودة."""
        return self._session.get(key, default)

    def load_session(self) -> dict[str, Any]:
        """تحميل الجلسة السابقة من القرص إن وُجدت."""
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE, encoding="utf-8") as f:
                    self._session = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._session = {}
        return self._session

    def _save_session(self) -> None:
        """حفظ الجلسة على القرص إن كانت dirty."""
        if not self._dirty:
            return
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(self._session, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def clear_session(self) -> None:
        """حذف ملف الجلسة + الذاكرة."""
        self._session = {}
        self._dirty = True
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    # ─── استعلامات الأعطال ────────────────────────────────────────────────────

    def has_crash_logs(self) -> bool:
        """هل توجد سجلات أعطال سابقة؟"""
        try:
            return any(CRASH_LOG_DIR.glob("crash_*.json"))
        except OSError:
            return False

    def get_last_crash(self) -> dict[str, Any] | None:
        """بيانات آخر عطل مسجّل، أو None."""
        if not CRASH_LOG_DIR.exists():
            return None
        logs = sorted(
            CRASH_LOG_DIR.glob("crash_*.json"), key=lambda p: p.stat().st_mtime
        )
        if not logs:
            return None
        try:
            with open(logs[-1], encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def cleanup(self) -> None:
        """فصل المعالجات عند إغلاق التطبيق (للاختبارات)."""
        if self._original_excepthook is not None:
            sys.excepthook = self._original_excepthook
            self._original_excepthook = None
        self._save_session()
