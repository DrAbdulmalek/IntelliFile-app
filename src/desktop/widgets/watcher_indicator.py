"""WatcherIndicator — مؤشر LED لحالة المراقب في الـ status bar

States:
  - idle (gray): المراقب متوقف
  - running (green): المراقب يعمل
  - pending (yellow): يوجد أحداث معلَّقة قيد المعالجة
  - error (red): خطأ في المراقب

PR-08 من development-roadmap-v1.0 (IFM Phase C)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel


class WatcherIndicator(QLabel):
    """مؤشر LED لحالة المراقب

    Signal:
        clicked(): نُقر المؤشر
    """

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WatcherIndicator")
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("idle")
        self._pending_count = 0
        self._running = False
        # مؤقت لإبقاء حالة "pending" ظاهرة لفترة قصيرة
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.setInterval(1500)
        self._pending_timer.timeout.connect(self._on_pending_timeout)

    def _on_pending_timeout(self) -> None:
        if self._running:
            self.set_state("running")
        else:
            self.set_state("idle")

    def set_state(self, state: str) -> None:
        """يضبط حالة المؤشر بصريًا

        Args:
            state: "idle" | "running" | "pending" | "error"
        """
        states = {
            "idle": ("● متوقف", "#6e7681", "transparent"),
            "running": ("● يعمل", "#3fb950", "#1c3a26"),
            "pending": ("● معالجة", "#d29922", "#3a2f1c"),
            "error": ("● خطأ", "#f85149", "#3a1c1c"),
        }
        if state not in states:
            return
        text, color, bg = states[state]
        self.setText(text)
        self.setStyleSheet(
            f"color: {color}; background-color: {bg}; "
            f"padding: 2px 10px; border-radius: 10px; font-weight: 600;"
        )
        self._state = state

    @property
    def state(self) -> str:
        return self._state

    def set_running(self, running: bool) -> None:
        """يضبط حالة التشغيل"""
        self._running = running
        if running and self._state != "pending":
            self.set_state("running")
        elif not running and self._state == "running":
            self.set_state("idle")

    def set_pending(self, count: int = 1) -> None:
        """يضع المؤقت في حالة معالجة مؤقتة"""
        self._pending_count += count
        self.set_state("pending")
        self._pending_timer.start()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
