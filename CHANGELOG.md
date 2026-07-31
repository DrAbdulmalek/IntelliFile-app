# Changelog

All notable changes to IntelliFile are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2.2.0-dev

> The work below is merged to `main` but **not yet tagged `v2.2.0`**.
> The latest released tag is `v2.1.0`. The `2.2.0.dev0` version in
> `setup.py` reflects this pre-release state. Tag `v2.2.0` only after
> completing `docs/RELEASE_CHECKLIST_v2.2.0.md`.

### Desktop UX (Phase C Complete)

#### PR-09: Progress + Previews + Settings
- **Cancellable progress bars** — `ProgressManager` (multi-op) integrated with
  `IFMController.progress` + `operation_cancelled`. Covers indexing, dry-run,
  and rule execution.
- **File preview panel** — `FilePreviewPanel`:
  - Text preview for ~30 extensions (txt, md, csv, json, yaml, py, js, ...)
  - Image thumbnails for 10 extensions (jpg, png, gif, bmp, webp, svg, ...)
  - Full file metadata (name / path / size / MIME / mtime)
  - Smart truncation for files >100 KB
  - Auto-update on inventory row selection
- **Settings panel** — `SettingsPanel` with 11 persisted fields:
  - watch_folders_enabled, default_dry_run, confirm_destructive
  - semantic_search_enabled (optional — off by default)
  - dark_mode, rtl, auto_organize
  - thumbnail_size, max_text_preview_bytes
  - save_undo_log_on_exit, save_action_log_on_exit
- **Error reporter** — `ErrorReporter` (counter + last-50 log) in status bar
- **Recent actions widget** — last 20 actions in status bar

#### PR-10: Polish + Release Checklist + v2.2.0
- **Keyboard shortcuts** — `ShortcutManager` with 8 global shortcuts:
  - Ctrl+R (refresh), F5 (scan), Ctrl+Z (undo), Ctrl+F (search)
  - Ctrl+, (settings), Ctrl+P (preview), Ctrl+T (toggle theme), Esc (cancel)
- **Crash recovery** — `CrashRecovery`:
  - Session persistence (last directory, panel, theme)
  - Global exception hook with crash logs (rotated, last 10 kept)
  - SIGINT/SIGTERM graceful shutdown
  - Crash recovery dialog on restart
- **PyInstaller packaging spec** — `packaging/desktop.spec` (Linux-first)
- **Release checklist** — `docs/RELEASE_CHECKLIST_v2.2.0.md`
- **Version bump** — `2.1.0` → `2.2.0`
- **`--version` CLI flag** — `python -m src.desktop.app --version`

### Core MVP (Phase A Complete)
- Indexed file inventory with SHA-256 deduplication
- Metadata extraction (EXIF, ffprobe, python-magic)
- Rule engine with YAML rulesets + dry-run mode
- Undo/rollback log with full action reversal
- Duplicate detection (exact + near-duplicate via embeddings)
- Watch folders with debounce + safe batch processing
- Safe atomic move/copy with checksum verification
- Action log with JSON/HTML/CSV export

### Security & Identity
- Product identity reset: local-first desktop file manager
- Removed all omni-medical-suite coupling
- API key optional auth + localhost binding
- No medical/DICOM/SyncManager scope creep

---

## [2.1.0] — 2026-07-24

### Desktop UX Foundation (Phase C — PR-08)
- PySide6 main window with sidebar + central stack + status bar
- 7 panels: Inventory, Preview, Rules, ActionLog, UndoLog, Watcher, Settings
- RTL Arabic theme + dark mode toggle
- IFMController signal/slot integration

### Phase A — Core MVP (PR-01 through PR-07)
- PR-01: Removed DICOM/SyncManager (scope reset)
- PR-02: Indexed file inventory with SHA-256
- PR-03: Enhanced metadata + content extraction
- PR-05: Rule engine + dry-run + undo
- PR-06: Duplicate detection + watch folders
- PR-07: Safe move/copy + action log

---

## [2.0.0] — 2026-07-22

### Initial Product Identity Reset
- Established local-first desktop file manager scope
- Created PRODUCT_IDENTITY.md, REPO_POLICY.md, SECURITY_NOTES.md
- Removed all medical/DICOM/SyncManager scope creep
