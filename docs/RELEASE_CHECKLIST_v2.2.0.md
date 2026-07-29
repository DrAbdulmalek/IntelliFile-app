# Release Checklist — IntelliFile Desktop v2.2.0

> PR-10 release checklist. Each item must be ticked before tagging v2.2.0.

---

## 1. Pre-Release Verification

- [ ] **All tests pass**:
  ```bash
  LD_LIBRARY_PATH=/home/z/.local/lib/qtfix:$LD_LIBRARY_PATH \
  QT_QPA_PLATFORM=offscreen \
  python -m pytest tests/ -q --tb=no
  ```
  Target: 665/665 passing (658 pre-PR-10 + 7 new PR-10 tests).
- [ ] **Lint clean (or pre-existing failures only)**:
  ```bash
  ruff check src/desktop/ tests/integration/test_desktop_pr10.py
  ```
  PR-10 files must not add new ruff errors.
- [ ] **Desktop smoke test (manual)**:
  ```bash
  LD_LIBRARY_PATH=/home/z/.local/lib/qtfix:$LD_LIBRARY_PATH \
  python -m src.desktop.app --base-dir /tmp/ifm_smoke
  ```
  Verify: window opens, sidebar shows 7 panels, scan runs, preview works,
  settings persist across restart, Esc cancels long operations.
- [ ] **Keyboard shortcuts smoke test**: Ctrl+R, F5, Ctrl+Z, Ctrl+F, Ctrl+,,
  Ctrl+P, Ctrl+T, Esc — all fire correct actions.
- [ ] **Crash recovery smoke test**: Force-kill the app mid-scan, relaunch,
  verify the "restore last session?" dialog appears.

---

## 2. Version Bump

- [ ] `src/__init__.py`: `__version__ = "2.2.0"`
- [ ] `setup.py`: `version="2.2.0"`
- [ ] `pyproject.toml`: `version = "2.2.0"` (if present)
- [ ] `CHANGELOG.md`: append `[2.2.0]` section
- [ ] `AI_WORKLOG.md`: append Phase PR-10 entry

---

## 3. Packaging

### 3.1 Linux (primary target)

- [ ] **PyInstaller build**:
  ```bash
  cd packaging
  pyinstaller desktop.spec
  ```
  Expected output: `dist/IntelliFile-Desktop/intellifile-desktop`
- [ ] **Run packaged binary**:
  ```bash
  ./dist/IntelliFile-Desktop/intellifile-desktop --base-dir /tmp/ifm_packaged
  ```
- [ ] **(Optional) AppImage**:
  ```bash
  appimagetool dist/IntelliFile-Desktop IntelliFile-Desktop-v2.2.0-x86_64.AppImage
  ```

### 3.2 Windows (cross-compile or CI)

- [ ] `pyinstaller packaging/desktop.spec --onefile` on Windows
- [ ] Test on Windows 10/11
- [ ] Verify no missing DLLs (especially Qt plugins)

### 3.3 macOS

- [ ] `pyinstaller packaging/desktop.spec --onefile --windowed` on macOS
- [ ] Test on macOS 13+ (Intel + Apple Silicon)
- [ ] Verify code signing (optional for v2.2.0)

---

## 4. Documentation

- [ ] **CHANGELOG.md** updated with [2.2.0] section
- [ ] **README.md** — version badge updated
- [ ] **docs/RELEASE_CHECKLIST_v2.2.0.md** (this file) — completed
- [ ] **AI_WORKLOG.md** — Phase PR-10 entry added
- [ ] **Screenshots** (optional): capture 3-4 key UI screenshots for README

---

## 5. Git & Release

- [ ] **Commit all PR-10 changes**:
  ```bash
  git add -A
  git commit -m "feat(desktop): polish + keyboard shortcuts + crash recovery + v2.2.0"
  ```
- [ ] **Push branch**:
  ```bash
  git push origin feat/ifm-desktop-polish-release
  ```
- [ ] **Open PR** titled `feat(desktop): PR-10 polish + release checklist + v2.2.0`
- [ ] **Merge PR** after review
- [ ] **Tag v2.2.0**:
  ```bash
  git tag -a v2.2.0 -m "IntelliFile Desktop v2.2.0 — Phase C complete"
  git push origin v2.2.0
  ```
- [ ] **GitHub Release** created with:
  - Title: `v2.2.0 — Desktop Phase C Complete`
  - Body: CHANGELOG.md [2.2.0] section
  - Assets: packaged binary (Linux), spec files (Win/macOS to follow)

---

## 6. Post-Release

- [ ] Verify GitHub Release page renders correctly
- [ ] Verify `pip install intellifile==2.2.0` works (if published to PyPI)
- [ ] Update `main` branch to v2.2.0
- [ ] Announce on relevant channels (Discord/Twitter/blog)
- [ ] Schedule v2.3.0 planning session

---

## 7. Risk Acceptance

- **Known issue:** `libEGL.so.1` must be available on the user's system
  (bundled via PyInstaller's Qt plugins, but verify on a clean Debian).
- **Known issue:** Lint failure on `main` is pre-existing (994 ruff errors
  across the whole codebase). PR-10 doesn't introduce new lint errors.
- **Acceptable risk:** PR-10 builds on PR-09 which is open but not yet
  merged; if PR-09 needs rework, PR-10 may need rebase.

---

## Sign-off

- **Built by:** Z.ai (Super Z)
- **Reviewed by:** DrAbdulmalek
- **Date:** 2026-07-25
- **Status:** PENDING
