# `mobile/` — Experimental, Not Part of Product Core

> ⚠️ **Status: Experimental / Unsupported**
>
> This directory and its companion `buildozer.spec` (at the repo root) are
> **not** part of the current IntelliFile product core. They are kept for
> historical reference and as an exploration of a possible future thin
> mobile client. They are **not actively maintained** and **not a release
> target**.

## What this is

- A Kivy-based thin client (`mobile/main.py`) that talks to the FastAPI
  backend when reachable and falls back to local browsing otherwise.
- A `buildozer.spec` (at repo root) configured to build an Android APK
  from `mobile/main.py`.

## What this is NOT

- **Not a first-class product target.** IntelliFile is a **local-first
  desktop file manager for personal use** (PySide6 desktop GUI + FastAPI
  service + optional Next.js web UI). Android / Kivy is **not** the
  product direction for the foreseeable future.
- **Not tested in CI.** No workflow builds or tests this code path.
- **Not included in any release.** No APK is published from this repo.
- **Not a medical tool.** Even if IntelliFile were to grow a mobile
  client, it would remain a **general-purpose** file manager — no
  medical scope.

## Why it's still here

- It demonstrates the API-first architecture works for thin clients.
- Deleting history is irreversible. Quarantine + clear docs is safer.

## If you want to revive it

1. Update `buildozer.spec` to current Kivy / python-for-android versions.
2. Add a CI workflow that at least imports `mobile/main.py` to catch
   syntax regressions.
3. Decide explicitly that mobile is a product target and update the
   top-level README + `ECOSYSTEM_STATE.md` accordingly.
4. Until that happens, treat this directory as read-only.

## Related

- Top-level README — product identity is desktop-first local file
  manager.
- `buildozer.spec` (repo root) — same experimental status.
- `docs/RELEASE_CHECKLIST_v2.2.0.md` — desktop release only; no mobile
  release checklist exists.
