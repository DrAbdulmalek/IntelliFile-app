<div align="center">

# IntelliFile Manager
## مدير الملفات الذكي — Smart File Manager

### تطبيق محلي لإدارة وتنظيم الملفات باستخدام الذكاء الاصطناعي
### Local-first AI File Manager for Personal Desktop Use

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)

<p align="center">
  <img src="https://img.shields.io/badge/الذكاء_الاصطناعي-AI_Powered-purple" alt="AI Powered" />
  <img src="https://img.shields.io/badge/البحث_الهجين-Hybrid_Search-blue" alt="Hybrid Search" />
  <img src="https://img.shields.io/badge/العربية-RTL_Support-FF6F00" alt="Arabic RTL" />
  <img src="https://img.shields.io/badge/الخصوصية-Offline_First-red" alt="Offline First" />
</p>

</div>

---

## Table of Contents

- [Description | الوصف](#description--الوصف)
- [Features | المميزات](#features--المميزات)
- [Architecture | البنية المعمارية](#architecture--البنية-المعمارية)
- [Quick Start | البدء السريع](#quick-start--البدء-السريع)
- [API Endpoints | نقاط نهاية API](#api-endpoints--نقاط-نهاية-api)
- [Development Guide | دليل التطوير](#development-guide--دليل-التطوير)
- [Plugin System | نظام الإضافات](#plugin-system--نظام-الإضافات)
- [License | الترخيص](#license--الترخيص)

---

## Description | الوصف

### العربية

**IntelliFile Manager** هو مدير ملفات ذكي يعمل محلياً على سطح المكتب، مصمم للاستخدام الشخصي اليومي. يجمع بين محرك بحث هجين (BM25 + دلالي + RRF)، وتصنيف ذكي للملفات، ووسوم تلقائية، ومساعد ملفات محلي (RAG)، ومعالجة متعددة الوسائط — كل ذلك مع دعم كامل للغة العربية وخصوصية تامة عبر المعالجة المحلية بدون اتصال بالإنترنت.

يعمل النظام كخدمة API عبر FastAPI مع واجهة ويب مبنية بـ Next.js، بالإضافة إلى واجهة سطح مكتب PySide6. جميع معالجات الذكاء الاصطناعي تعمل محلياً عبر Ollama وsentence-transformers لضمان الخصوصية الكاملة.

### English

**IntelliFile Manager** is a local-first AI file manager designed for personal desktop use. It combines a hybrid search engine (BM25 + Semantic + RRF), smart file classification, auto-tagging, a local RAG-based File Copilot, and multimodal processing — all with full Arabic RTL support and offline-first privacy through local AI processing.

The system runs as a FastAPI service with a Next.js web interface and an optional PySide6 desktop GUI. All AI processing runs locally via Ollama and sentence-transformers for complete privacy.

---

## Product Scope | نطاق المنتج

IntelliFile is a **general-purpose local-first desktop file manager** for
personal use. The supported surfaces are:

- **FastAPI service** (backend)
- **PySide6 desktop GUI** (primary user-facing surface)
- **Next.js web UI** (optional companion)

The `mobile/` directory and `buildozer.spec` are **experimental and not
part of the product core** — see [`mobile/README.md`](mobile/README.md).
Android / Kivy is not the product direction for the foreseeable future.

IntelliFile is **not** a medical tool. Any medical-specific classification
logic that may exist in the codebase is unintended scope and is being
tracked separately.

---

## Features | المميزات

### 🔍 Hybrid Search | البحث الهجين

محرك بحث هجين يجمع بين خوارزمية BM25 للبحث الكلمي والبحث الدلالي عبر المتجهات (sentence-transformers)، مع دمج النتائج باستخدام خوارزمية Reciprocal Rank Fusion (RRF). يدعم البحث باللغة العربية والإنجليزية مع فهم عميق لسياق الاستعلام.

- **BM25 Keyword Search**: بحث كلمي سريع ودقيق
- **Semantic Vector Search**: بحث دلالي يفهم المعنى والسياق (اختياري)
- **RRF Fusion**: دمج ذكي لنتائج المحركين مع ترجيح متوازن
- **Arabic Tokenization**: دعم تجزئة النص العربي

### 📁 Smart Classification | التصنيف الذكي

تصنيف تلقائي للملفات بناءً على المحتوى والامتداد:

- **كشف النوع**: تحديد نوع الملف تلقائياً (Magika)
- **تصنيف المحتوى**: تصنيف حسب محتوى الملف النصي
- **دعم العربية**: تصنيف الملفات العربية
- **تصنيف مجمع**: معالجة مجلدات كاملة دفعة واحدة

### 🏷️ Smart Tagging | الوسوم الذكية

نظام وسوم ذكي متعدد الطبقات يولد وسوماً تلقائياً بناءً على:

- **وسوم المحتوى**: استخراج الكلمات المفتاحية والمواضيع
- **وسوم النوع**: تصنيف حسب نوع الملف وامتداده
- **وسوم مخصصة**: إضافة وسوم يدوية مع تصنيفات قابلة للتخصيص
- **وسوم مجمعة**: تطبيق وسوم على مجموعة ملفات دفعة واحدة
- **بحث الوسوم**: البحث عن الملفات بواسطة الوسوم

### 🤖 File Copilot | مساعد الملفات

مساعد ذكي يعتمد على تقنية RAG (Retrieval-Augmented Generation) للمحادثة مع ملفاتك:

- **محادثة ذكية**: أسئلة وأجوبة بناءً على محتوى ملفاتك
- **تلخيص تلقائي**: إنشاء ملخصات شاملة لأي ملف
- **فهرسة ذكية**: إضافة ملفات إلى قاعدة المعرفة
- **بث مباشر**: دعم WebSocket للردود المتدفقة

### 🖼️ Multimodal Processing | المعالجة متعددة الوسائط

معالجة شاملة لأنواع الملفات المختلفة:

- **الصور**: استخراج النصوص (OCR)، وصف المحتوى
- **الصوت**: تحويل الكلام إلى نص (STT)، تحليل المحتوى الصوتي
- **الفيديو**: استخراج الإطارات، إنشاء ملخصات
- **المستندات**: استخراج النصوص من PDF وDOCX وXLSX

### 🌐 RTL Support | دعم العربية

دعم كامل للغة العربية في جميع مستويات التطبيق:

- **واجهة عربية**: واجهة مستخدم كاملة من اليمين لليسار
- **بحث عربي**: معالجة خاصة للنص العربي في البحث والتصنيف
- **وسوم عربية**: إنشاء وسوم باللغة العربية

### ⚡ Offline-First | أولوية العمل بدون اتصال

جميع عمليات الذكاء الاصطناعي تعمل محلياً بدون حاجة للإنترنت:

- **Ollama LLM**: نماذج لغوية محلية
- **Local Embeddings**: تضمينات محلية (sentence-transformers)
- **ChromaDB**: قاعدة بيانات متجهات محلية
- **Magika**: كشف نوع الملف محلياً (100+ نوع)

### 🔒 Privacy & Security | الخصوصية والأمان

- **لا بيانات خارجية**: لا يتم إرسال أي بيانات لخوادم خارجية
- **معالجة محلية**: جميع العمليات تتم على جهازك
- **ربط محلي**: API يربط على 127.0.0.1 فقط افتراضياً
- **مصادقة اختيارية**: دعم API Key عبر `INTELLIFILE_API_KEY`
- **حماية المسارات**: sandboxing يمنع الوصول لمسارات غير مصرح بها

---

## Architecture | البنية المعمارية

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Presentation Layer                          │
│  ┌───────────────────────┐    ┌──────────────────────────────────┐  │
│  │  Desktop GUI (PySide6)│    │  Web UI (Next.js + shadcn)      │  │
│  │  src/gui/             │    │  web/src/                       │  │
│  └───────────┬───────────┘    └──────────────┬───────────────────┘  │
└──────────────┼───────────────────────────────┼─────────────────────┘
               │                               │
               ▼                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        API Layer (FastAPI)                           │
│                    src/api/server.py — Port 8421                     │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────────┐ │
│  │ Classify│ │  Search  │ │   Tags   │ │ Copilot │ │  Organize  │ │
│  │ /api/   │ │ /api/    │ │ /api/    │ │ /api/   │ │ /api/      │ │
│  │ classify│ │ search   │ │ tags     │ │ copilot │ │ organize   │ │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ └─────┬──────┘ │
└───────┼───────────┼────────────┼─────────────┼────────────┼────────┘
        │           │            │             │            │
        ▼           ▼            ▼             ▼            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       Core Engine Layer (src/core/)                  │
│  ┌───────────────┐ ┌──────────────┐ ┌─────────────────────────────┐ │
│  │ SmartFile     │ │ HybridSearch │ │ SmartTagger                 │ │
│  │ Classifier    │ │ Engine       │ │ (auto-tag + manual)         │ │
│  └───────────────┘ └──────────────┘ └─────────────────────────────┘ │
│  ┌───────────────┐ ┌──────────────┐ ┌─────────────────────────────┐ │
│  │ FileCopilot   │ │ Enhanced     │ │ FileHandler                 │ │
│  │ (RAG Chat)    │ │ Multimodal   │ │ (CRUD + Undo)               │ │
│  └───────────────┘ └──────────────┘ └─────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    AI & Data Layer                                   │
│  ┌──────────┐ ┌──────────────────┐ ┌────────────────────────────┐  │
│  │  Ollama  │ │ sentence-        │ │      ChromaDB              │  │
│  │  (LLM)   │ │ transformers     │ │    (Vector Store)          │  │
│  └──────────┘ └──────────────────┘ └────────────────────────────┘  │
│  ┌──────────┐ ┌──────────────────────────────────────────────────┐ │
│  │  Magika  │ │  Plugin System (src/plugins/)                   │ │
│  │(Type Det)│ │  • IntelliFilePlugin base class                 │ │
│  └──────────┘ │  • PluginManager + PluginContext                │ │
│               │  • Auto-discovery from src/plugins/              │ │
│               └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start | البدء السريع

### Prerequisites | المتطلبات المسبقة

- **Python** 3.10 أو أحدث
- **Node.js** 18 أو أحدث (لواجهة الويب)
- **Ollama** (للذكاء الاصطناعي المحلي)

### Installation | التثبيت

```bash
# 1. استنساخ المستودع
git clone https://github.com/DrAbdulmalek/intelli-file-manager.git
cd intelli-file-manager

# 2. إنشاء بيئة افتراضية
python -m venv venv
source venv/bin/activate

# 3. تثبيت متطلبات Python
pip install -r requirements.txt

# 4. تثبيت Ollama وتحميل النماذج (اختياري)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
ollama pull nomic-embed-text

# 5. تثبيت واجهة الويب (اختياري)
cd web && npm install && cd ..
```

### Running the API Server | تشغيل خادم API

```bash
# تشغيل خادم API على المنفذ 8421 (localhost فقط)
uvicorn src.api.server:app --host 127.0.0.1 --port 8421 --reload

# أو باستخدام main.py
python -m src.main --web

# التوثيق التفاعلي
# Swagger UI: http://localhost:8421/api/docs
# ReDoc:      http://localhost:8421/api/redoc
```

### Running the Web Interface | تشغيل واجهة الويب

```bash
cd web
npm run dev
# افتح http://localhost:3000 في المتصفح
```

### Running the Desktop App | تشغيل واجهة سطح المكتب

> **جديد في v2.2.0** — واجهة PySide6 محلية بالكامل (Phase C مكتملة)

```bash
# تشغيل واجهة سطح المكتب
python -m src.desktop.app --base-dir /path/to/folder

# أو مع ملف قواعد مخصّص
python -m src.desktop.app --base-dir ~/Downloads --ruleset rules/custom.yaml

# عرض الإصدار
python -m src.desktop.app --version
```

#### Keyboard Shortcuts | اختصارات لوحة المفاتيح

| الاختصار | الإجراء | Description |
|---|---|---|
| `Ctrl+R` | تحديث العرض الحالي | Refresh current panel |
| `F5` | فحص المجلد الحالي | Scan current folder |
| `Ctrl+Z` | تراجع عن آخر إجراء | Undo last action |
| `Ctrl+F` | تركيز البحث في اللوحة | Focus search in current panel |
| `Ctrl+,` | فتح لوحة الإعدادات | Open settings panel |
| `Ctrl+P` | فتح لوحة المعاينة | Open preview panel |
| `Ctrl+T` | تبديل السمة (داكن/فاتح) | Toggle dark/light theme |
| `Esc` | إلغاء العملية الجارية | Cancel running operation |
| `Ctrl+O` | فتح مجلد جديد | Open new folder |
| `Ctrl+Q` | خروج | Exit application |

#### Features | المميزات

- **7 panels**: جرد، معاينة، قواعد، سجل إجراءات، سجل تراجع، مراقب، إعدادات
- **Live progress + cancellation**: شريط تقدّم قابل للإلغاء لكل عملية طويلة
- **File preview**: معاينة نصية (50+ امتداد) + مصغّرات صور (jpg/png/gif/...)
- **Crash recovery**: استرداد آخر جلسة (آخر مجلد + لوحة) عند إعادة التشغيل
- **Tooltips + Tab navigation**: تلميحات على كل مكوّن + ترتيب Tab منطقي
- **RTL support**: دعم كامل لاتجاهRTL للعربية

> الاختلال المعروف: يتطلب توفّر `libEGL.so.1` على لينكس — يُحل عبر تثبيت `libgl1` أو `libegl1`.

### Running Tests | تشغيل الاختبارات

```bash
# جميع الاختبارات
pytest

# اختبارات الوحدات فقط
pytest tests/unit/ -v

# اختبارات التكامل فقط
pytest tests/integration/ -v

# مع تغطية الكود
pytest --cov=src tests/ --cov-report=html
```

### CLI Usage | واجهة سطر الأوامر

```bash
# تصنيف مجلد
python -m src.main classify /path/to/folder

# بحث هجين
python -m src.main search "تقارير المبيعات"

# تنظيم ملفات
python -m src.main organize /path/to/folder --dry-run

# كشف المكررات
python -m src.main duplicates /path/to/folder
```

---

## API Endpoints | نقاط نهاية API

| # | Method | Endpoint | الوصف | Description |
|---|--------|----------|-------|-------------|
| 1 | `GET` | `/api/health` | فحص صحة النظام | Health check |
| 2 | `POST` | `/api/classify` | تصنيف ملف أو مجلد | Classify file or directory |
| 3 | `POST` | `/api/search` | بحث هجين | Hybrid search |
| 4 | `POST` | `/api/search/index` | فهرسة مجلد للبحث | Index directory for search |
| 5 | `POST` | `/api/tags/auto` | وسوم تلقائية لملف | Auto-tag a file |
| 6 | `POST` | `/api/tags/add` | إضافة وسم يدوي | Add manual tag |
| 7 | `POST` | `/api/tags/batch` | وسوم مجمعة | Batch tag files |
| 8 | `DELETE` | `/api/tags/remove` | حذف وسم | Remove tag |
| 9 | `GET` | `/api/tags/search` | بحث بوسم | Search by tag |
| 10 | `GET` | `/api/tags/all` | جميع الوسوم | Get all tags |
| 11 | `POST` | `/api/copilot/chat` | محادثة مع مساعد | Chat with Copilot |
| 12 | `POST` | `/api/copilot/index` | فهرسة للمحادثة | Index for Copilot |
| 13 | `GET` | `/api/copilot/conversations` | قائمة المحادثات | List conversations |
| 14 | `POST` | `/api/copilot/summarize` | تلخيص ملف | Summarize file |
| 15 | `WS` | `/api/copilot/ws` | محادثة مباشرة | Streaming chat |
| 16 | `POST` | `/api/process/image` | معالجة صورة | Process image |
| 17 | `POST` | `/api/process/audio` | معالجة صوت | Process audio |
| 18 | `POST` | `/api/process/video` | معالجة فيديو | Process video |
| 19 | `POST` | `/api/process/document` | معالجة مستند | Process document |
| 20 | `POST` | `/api/process/upload` | رفع ومعالجة ملف | Upload & process |
| 21 | `POST` | `/api/ner/extract` | استخراج كيانات مسماة | Extract named entities |
| 22 | `POST` | `/api/organize` | تنظيم ملفات | Auto-organize files |
| 23 | `POST` | `/api/embed` | تضمينات متجهية | Generate embeddings |
| 24 | `POST` | `/api/embed/similarity` | حساب التشابه | Compute similarity |
| 25 | `GET` | `/api/stats` | إحصائيات | Stats |

### API Authentication

المصادقة اختيارية. عند تعيين متغير البيئة `INTELLIFILE_API_KEY`، يتطلب API إرسال رأس `X-API-Key` مع كل طلب. بدون تعيينه، يعمل API بدون مصادقة (آمن للاستخدام المحلي على localhost).

### Example API Calls

```bash
# فحص صحة النظام
curl http://localhost:8421/api/health

# تصنيف مجلد
curl -X POST http://localhost:8421/api/classify \
  -H "Content-Type: application/json" \
  -d '{"path": "/home/user/documents", "recursive": true}'

# بحث هجين
curl -X POST http://localhost:8421/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "تقارير المبيعات", "top_k": 10, "engine": "hybrid"}'

# وسوم تلقائية
curl -X POST "http://localhost:8421/api/tags/auto?filepath=/home/user/report.pdf"

# محادثة مع مساعد الملفات
curl -X POST http://localhost:8421/api/copilot/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "لخص لي تقرير المبيعات"}'

# مع مصادقة API Key
curl -X POST http://localhost:8421/api/classify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"path": "/home/user/documents"}'
```

---

## Development Guide | دليل التطوير

### Project Structure | هيكل المشروع

```
intelli-file-manager/
├── src/
│   ├── api/                    # FastAPI server
│   │   └── server.py
│   ├── core/                   # Core engines
│   │   ├── config.py           # Configuration & categories
│   │   ├── classifier.py       # Smart file classifier
│   │   ├── hybrid_search.py    # BM25 + Semantic + RRF
│   │   ├── smart_tagger.py     # Auto + manual tagging
│   │   ├── file_copilot.py     # RAG-based chat assistant
│   │   ├── enhanced_multimodal.py  # Multimodal processing
│   │   ├── file_handler.py     # CRUD + undo + backup
│   │   ├── ai_engine.py        # Ollama integration
│   │   ├── semantic_search.py  # Vector search
│   │   ├── rag_engine.py       # RAG engine
│   │   ├── medical_ner.py      # Named Entity Recognition
│   │   ├── voice_controller.py # Voice control
│   │   └── ...                 # Other modules
│   ├── ai/                     # AI engine layer
│   │   ├── embeddings.py       # Embedding engine
│   │   └── ...
│   ├── plugins/                # Plugin system
│   │   ├── __init__.py         # IntelliFilePlugin, PluginManager
│   │   └── ...
│   ├── gui/                    # PySide6 desktop GUI
│   └── utils/                  # Utilities
├── web/                        # Next.js web interface
├── tests/                      # Test suite
├── docs/                       # Documentation
├── README.md
└── requirements.txt
```

### Development Setup | إعداد بيئة التطوير

```bash
# 1. استنساخ وإنشاء بيئة افتراضية
git clone https://github.com/DrAbdulmalek/intelli-file-manager.git
cd intelli-file-manager
python -m venv venv
source venv/bin/activate

# 2. تثبيت متطلبات التطوير
pip install -r requirements.txt
pip install pytest pytest-cov ruff mypy

# 3. تشغيل الاختبارات
pytest -v

# 4. فحص جودة الكود
ruff check src/
mypy src/ --ignore-missing-imports
```

### Code Style | معايير الكود

- **Python**: اتباع PEP 8 مع حد أقصى 120 حرفاً لكل سطر
- **Type Hints**: استخدام تعليقات النوع لجميع الدوال العامة
- **Docstrings**: توثيق جميع الدوال والفئات العامة
- **Arabic RTL**: ضمان دعم RTL في أي تغييرات على الواجهة

---

## Plugin System | نظام الإضافات

يتضمن IntelliFile Manager نظام إضافات مرن يسمح بتوسيع الوظائف بدون تعديل الكود الأساسي.

### Creating a Plugin | إنشاء إضافة

```python
from src.plugins import IntelliFilePlugin, PluginContext

class MyPlugin(IntelliFilePlugin):
    name = "my_plugin"
    version = "1.0.0"
    description = "وصف الإضافة"
    
    def initialize(self, context: PluginContext) -> None:
        context.register_classifier("my_classifier", self._classify)
        context.register_tag_generator("my_tags", self._generate_tags)
    
    def _classify(self, text: str) -> dict:
        return {"category": "custom", "confidence": 0.9}
    
    def _generate_tags(self, filepath: str, text: str) -> list[str]:
        return ["custom/tag1", "custom/tag2"]
```

### Plugin Discovery | اكتشاف الإضافات

الإضافات يتم اكتشافها تلقائياً من:

1. **`src/plugins/`** — إضافات مدمجة (built-in)
2. **`~/.intellifile/plugins/`** — إضافات المستخدم
3. **PYTHONPATH** — حزم باسم `intellifile_plugin`

### Optional Integrations | تكاملات اختيارية

يمكن ربط IntelliFile Manager مع أنظمة خارجية عبر نظام الإضافات أو REST API. أي تكامل مع أنظمة أخرى (مثل منصات OCR/NLP) اختياري تماماً ولا يؤثر على الوظائف الأساسية.

---

## Tech Stack | التقنيات المستخدمة

### Backend | الخلفية

| التقنية | الغرض |
|---------|-------|
| Python 3.10+ | لغة البرمجة الرئيسية |
| FastAPI | إطار عمل API |
| Ollama | نماذج اللغة المحلية |
| sentence-transformers | التضمينات الدلالية (اختياري) |
| ChromaDB | قاعدة بيانات المتجهات |
| Magika | كشف نوع الملف |
| PySide6 | واجهة سطح المكتب |

### Frontend | الواجهة

| التقنية | الغرض |
|---------|-------|
| Next.js | إطار عمل الويب |
| TypeScript | لغة مكتوبة |
| Tailwind CSS | إطار التصميم |
| shadcn/ui | مكونات UI |

---

## License | الترخيص

هذا المشروع مرخص بموجب رخصة **MIT**. يمكنك الاطلاع على ملف [LICENSE](LICENSE) للتفاصيل الكاملة.

---

<div align="center">

**صُنع بـ ❤️ لمجتمع لينكس والبرمجيات الحرة**
**Built with ❤️ for the Linux & Free Software communities**

[Report Bug](https://github.com/DrAbdulmalek/intelli-file-manager/issues) · [Request Feature](https://github.com/DrAbdulmalek/intelli-file-manager/issues) · [Contribute](CONTRIBUTING.md)

</div>
