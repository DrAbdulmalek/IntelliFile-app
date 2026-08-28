"""⚠️ EXPERIMENTAL — NOT PART OF PRODUCT CORE.

IntelliFile Manager — Kivy Mobile App (Android APK)

This module is kept for historical reference and exploration. It is NOT
actively maintained, NOT tested in CI, and NOT a release target.
IntelliFile is a desktop-first local file manager; Android/Kivy is NOT
the product direction. See mobile/README.md for the full status note.

A mobile-first thin client for IntelliFile Manager with Arabic RTL support.
Connects to the FastAPI backend when available, works offline otherwise.

Architecture:
  - Thin client: no heavy ML dependencies (no sentence-transformers, chromadb)
  - API-first: all AI operations go through the FastAPI backend
  - Offline fallback: basic file browsing and local search when server is down

Build APK:
    buildozer android debug

Run on desktop:
    python mobile/main.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.metrics import dp
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle

# ---------------------------------------------------------------------------
# Arabic RTL helpers
# ---------------------------------------------------------------------------

RTL_MARK = "\u200F"


def _rtl(text: str) -> str:
    """Prepend RTL mark for proper Arabic display."""
    return RTL_MARK + str(text)


# ---------------------------------------------------------------------------
# API Client — communicates with FastAPI backend
# ---------------------------------------------------------------------------

_DEFAULT_API = "http://localhost:8421"


class APIClient:
    """Lightweight API client for IntelliFile backend."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("INTELLIFILE_API", _DEFAULT_API)).rstrip("/")

    def _request(self, method: str, path: str, **kwargs):
        """Make HTTP request using urllib (no external deps needed)."""
        url = f"{self.base_url}{path}"
        try:
            import urllib.request
            import urllib.error
            data = kwargs.get("json")
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode() if data else None,
                headers=headers,
                method=method,
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()), resp.status
        except Exception as exc:
            return {"error": str(exc)}, 503

    def health(self) -> dict:
        data, _ = self._request("GET", "/api/health")
        return data

    def search(self, query: str, top_k: int = 10) -> dict:
        data, _ = self._request("POST", "/api/search", json={"query": query, "top_k": top_k})
        return data

    def classify(self, path: str) -> dict:
        data, _ = self._request("POST", "/api/classify", json={"path": path})
        return data

    def ner_extract(self, text: str) -> dict:
        data, _ = self._request("POST", "/api/ner/extract", json={"text": text})
        return data

    def stats(self) -> dict:
        data, _ = self._request("GET", "/api/stats")
        return data

    def tags(self, path: str = ".") -> dict:
        data, _ = self._request("POST", "/api/tags/search", json={"query": "", "path": path})
        return data

    def is_available(self) -> bool:
        try:
            data, code = self._request("GET", "/api/health")
            return code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------


class RTLLabel(Label):
    """Label with RTL Arabic support."""

    def __init__(self, **kwargs):
        kwargs.setdefault("halign", "right")
        kwargs.setdefault("valign", "top")
        super().__init__(**kwargs)


class HeaderBar(BoxLayout):
    """Blue title bar with app name."""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(56), **kwargs)
        with self.canvas.before:
            Color(0.145, 0.388, 0.922, 1)  # #2563eb
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        title = Label(
            text="IntelliFile Manager",
            font_size="20sp",
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle",
        )
        self.add_widget(title)

    def _update_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size


class ResultPanel(ScrollView):
    """Scrollable result display with RTL text."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.label = RTLLabel(
            text=_rtl("مرحباً بك في IntelliFile Manager\nاضغط بحث للبدء"),
            font_size="15sp",
            size_hint_y=None,
            height=dp(500),
            text_size=(None, None),
        )
        self.label.bind(
            width=lambda *a: setattr(self.label, "text_size", (self.label.width, None)),
            texture_size=lambda *a: setattr(self.label, "height", max(dp(500), self.label.texture_size[1])),
        )
        self.add_widget(self.label)

    def set_text(self, text: str):
        self.label.text = _rtl(str(text))
        self.scroll_y = 1


class StatusBar(BoxLayout):
    """Bottom status bar showing API connection state."""

    def __init__(self, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(28), **kwargs)
        with self.canvas.before:
            Color(0.12, 0.12, 0.12, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)
        self.status_label = Label(
            text="جاري الاتصال...",
            font_size="12sp",
            color=(0.7, 0.7, 0.7, 1),
            halign="right",
            valign="middle",
        )
        self.add_widget(self.status_label)

    def _update_bg(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def set_status(self, text: str, connected: bool = False):
        icon = "متصل" if connected else "غير متصل"
        self.status_label.text = _rtl(f"{icon} — {text}")
        self.status_label.color = (0.4, 0.9, 0.4, 1) if connected else (0.9, 0.4, 0.4, 1)


# ---------------------------------------------------------------------------
# Main Screen
# ---------------------------------------------------------------------------


class MainScreen(Screen):
    """الشاشة الرئيسية للتطبيق"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.api = APIClient()

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(6))

        # Header
        root.add_widget(HeaderBar())

        # Search bar
        search_box = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(8),
        )
        self.search_input = TextInput(
            hint_text="بحث في الملفات...",
            size_hint_x=0.72,
            multiline=False,
            font_size="16sp",
        )
        search_btn = Button(text="بحث", size_hint_x=0.28, font_size="16sp")
        search_btn.bind(on_press=lambda x: self.do_search())
        self.search_input.bind(on_text_validate=lambda x: self.do_search())

        search_box.add_widget(self.search_input)
        search_box.add_widget(search_btn)
        root.add_widget(search_box)

        # Result panel
        self.result_panel = ResultPanel()
        root.add_widget(self.result_panel)

        # Action buttons row
        actions = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(6),
        )
        for label, callback in [
            ("تصنيف", self.do_classify),
            ("وسوم", self.do_tags),
            ("NER طبي", self.do_ner),
            ("إحصائيات", self.do_stats),
            ("صحة", self.do_health),
        ]:
            btn = Button(text=label, font_size="13sp")
            btn.bind(on_press=lambda x, cb=callback: cb())
            actions.add_widget(btn)

        root.add_widget(actions)

        # Status bar
        self.status_bar = StatusBar()
        root.add_widget(self.status_bar)

        self.add_widget(root)

        # Check API health on start
        Clock.schedule_once(self._check_health, 1)

    def _check_health(self, dt=None):
        """Check API server availability."""
        try:
            if self.api.is_available():
                data = self.api.health()
                ver = data.get("version", "?")
                self.status_bar.set_status(f"v{ver}", connected=True)
            else:
                self.status_bar.set_status("وضع عدم الاتصال", connected=False)
        except Exception:
            self.status_bar.set_status("وضع عدم الاتصال", connected=False)

    def _show_error(self, msg: str):
        """Display error popup."""
        popup = Popup(
            title="خطأ",
            content=Label(text=_rtl(msg)),
            size_hint=(0.8, 0.4),
        )
        popup.open()

    # ----- Action Handlers -----

    def do_search(self):
        query = self.search_input.text.strip()
        if not query:
            self.result_panel.set_text("الرجاء إدخال نص للبحث")
            return
        self.result_panel.set_text("جاري البحث...")
        try:
            result = self.api.search(query)
            if "error" in result:
                self.result_panel.set_text(f"خطأ: {result['error']}")
            elif "results" in result:
                items = result["results"]
                if not items:
                    self.result_panel.set_text("لا توجد نتائج")
                else:
                    lines = []
                    for i, r in enumerate(items, 1):
                        score = r.get("rrf_score", r.get("score", 0))
                        rid = r.get("id", r.get("path", "unknown"))
                        if isinstance(rid, str) and len(rid) > 60:
                            rid = rid[:60] + "..."
                        lines.append(f"{i}. {rid} (score: {score:.4f})")
                    self.result_panel.set_text("\n".join(lines))
            else:
                self.result_panel.set_text(str(result))
        except Exception as e:
            self.result_panel.set_text(f"خطأ: {e}")

    def do_classify(self):
        self.result_panel.set_text("جاري التصنيف...")
        try:
            result = self.api.classify(".")
            if "error" in result:
                self.result_panel.set_text(f"خطأ: {result['error']}")
            elif "categories" in result:
                lines = [f"{k}: {v}" for k, v in result["categories"].items()]
                self.result_panel.set_text("\n".join(lines))
            else:
                self.result_panel.set_text(str(result))
        except Exception as e:
            self.result_panel.set_text(f"خطأ: {e}")

    def do_tags(self):
        self.result_panel.set_text("جاري تحميل الوسوم...")
        try:
            result = self.api.tags(".")
            if "error" in result:
                self.result_panel.set_text(f"خطأ: {result['error']}")
            elif "tags" in result:
                tags = result["tags"]
                if isinstance(tags, dict):
                    sorted_tags = sorted(tags.items(), key=lambda x: -x[1])[:20]
                    lines = [f"{k}: {v}" for k, v in sorted_tags]
                elif isinstance(tags, list):
                    lines = [str(t) for t in tags[:20]]
                else:
                    lines = [str(tags)]
                self.result_panel.set_text("\n".join(lines))
            else:
                self.result_panel.set_text(str(result))
        except Exception as e:
            self.result_panel.set_text(f"خطأ: {e}")

    def do_ner(self):
        sample = "المريض أحمد يعاني من مرض السكري ويأخذ الميتفورمين 500 ملغ"
        self.result_panel.set_text("جاري استخراج الكيانات الطبية...")
        try:
            result = self.api.ner_extract(sample)
            if "error" in result:
                self.result_panel.set_text(f"خطأ: {result['error']}")
            elif "entities" in result:
                entities = result["entities"]
                if not entities:
                    self.result_panel.set_text("لا توجد كيانات مستخرجة")
                else:
                    lines = []
                    for ent in entities:
                        etype = ent.get("entity_type", ent.get("type", "?"))
                        text_val = ent.get("text", "?")
                        lines.append(f"[{etype}] {text_val}")
                    self.result_panel.set_text("\n".join(lines))
            else:
                self.result_panel.set_text(str(result))
        except Exception as e:
            self.result_panel.set_text(f"خطأ: {e}")

    def do_stats(self):
        self.result_panel.set_text("جاري تحميل الإحصائيات...")
        try:
            result = self.api.stats()
            if "error" in result:
                self.result_panel.set_text(f"خطأ: {result['error']}")
            else:
                lines = [f"{k}: {v}" for k, v in result.items()]
                self.result_panel.set_text("\n".join(lines))
        except Exception as e:
            self.result_panel.set_text(f"خطأ: {e}")

    def do_health(self):
        self.result_panel.set_text("جاري فحص الخادم...")
        try:
            data = self.api.health()
            status = data.get("status", "unknown")
            version = data.get("version", "?")
            engines = data.get("engines", {})
            lines = [f"الحالة: {status}", f"الإصدار: {version}"]
            for k, v in engines.items():
                icon = "نعم" if v else "لا"
                lines.append(f"{k}: {icon}")
            connected = status == "ok"
            self.status_bar.set_status(f"v{version}", connected=connected)
            self.result_panel.set_text("\n".join(lines))
        except Exception as e:
            self.status_bar.set_status("غير متصل", connected=False)
            self.result_panel.set_text("الخادم غير متاح\nوضع عدم الاتصال")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class IntelliFileApp(App):
    """تطبيق IntelliFile Manager"""

    def build(self):
        self.title = "IntelliFile Manager"
        sm = ScreenManager()
        sm.add_widget(MainScreen(name="main"))
        return sm

    def on_pause(self):
        return True

    def on_resume(self):
        pass


if __name__ == "__main__":
    IntelliFileApp().run()
