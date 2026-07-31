# Architecture — intelli-file-manager

AI-powered file manager: FastAPI backend (port 8421) + PySide6 desktop
UI + Next.js web UI. Combines BM25 keyword search with semantic
embeddings (Ollama) for hybrid retrieval.

```
┌────────────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ PySide6 Desktop │  │ Next.js Web UI  │  │ REST API clients │  │
│  │  (Qt 6)         │  │  (React 18)     │  │ (curl/httpx)     │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘  │
└───────────┼─────────────────────┼────────────────────┼────────────┘
            │                     │                    │
            ▼                     ▼                    ▼
┌────────────────────────────────────────────────────────────────────┐
│  API LAYER  —  src/api/server.py  (FastAPI, port 8421)              │
│  • REST endpoints: /api/files, /api/search, /api/categories        │
│  • WebSocket: /ws/events (file system watch)                       │
│  • Auth: optional API key header                                   │
│  • _SAFE_CATEGORY_RE moved to module top (was: after create_app)   │
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  CORE ENGINE  —  src/core/                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐│
│  │ classifier   │  │ action_log   │  │ rule_engine              ││
│  │ (magika ML)  │  │ (undo/redo)  │  │ (dry-run + apply)        ││
│  └──────────────┘  └──────────────┘  └──────────────────────────┘│
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐│
│  │ hybrid_search│  │ file_copilot │  │ agent_cli                ││
│  │ BM25+semant. │  │ (Ollama LLM) │  │ (REPL)                   ││
│  │ _extract_text│  │ TCP probe    │  │                          ││
│  │ → "" on fail │  │ →11434 first │  │                          ││
│  └──────────────┘  └──────────────┘  └──────────────────────────┘│
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  AI & DATA LAYER                                                   │
│  • Ollama (localhost:11434) — local LLM inference                  │
│  • SQLite — file metadata, action log, rules                       │
│  • watchdog — real-time FS events                                  │
│  • sentence-transformers — semantic embeddings                     │
└────────────────────────────────────────────────────────────────────┘
```

## P0/P1 fixes

1. **`_SAFE_CATEGORY_RE` ordering** — moved from after `create_app()`
   to module-level constant. Avoids rare NameError when the regex is
   referenced during application factory wiring.
2. **`_extract_text()` fallback** — was returning `path.name` (filename)
   when text extraction failed, causing filenames to be indexed as
   document text. Now returns `""` so failed files contribute nothing
   to the BM25 corpus.
3. **`hybrid_search.search()` guard** — added `_check_initialized()`
   guard before BM25 lookup to avoid `AttributeError` when
   `_doc_ids` is empty.
