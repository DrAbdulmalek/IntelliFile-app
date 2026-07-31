"""
Lightweight observability + notes foundation for IntelliFile.

Local-first, SQLite + JSONL, privacy-aware. No telemetry, no network.
Designed to be small enough to remain maintainable.

Five components:
  1. system self-profile      — app version, env, feature flags, dep health
  2. structured run logging   — run_id, component, action, status, duration
  3. artifact/result registry — what was produced, where, by what, from what
  4. manual operator notes    — attached to runs/files/folders/actions
  5. improvement queue        — repeated failures + meaningful notes
                                traced as future improvement items

Privacy defaults:
  - No secret values are ever logged.
  - File paths are stored as given (local tool, local user).
  - Sensitive field names are matched against a regex blocklist and
    redacted to <REDACTED> before any write.
  - Raw payloads are only stored when debug=True is explicitly passed.

Storage layout (under the user's local app data dir):
  <app_data>/observability/
    observability.db     — SQLite (runs, artifacts, notes, queue, profile)
    runs.jsonl           — append-only NDJSON mirror of run events
    notes.jsonl          — append-only NDJSON mirror of note events

The JSONL mirror is for tailing/grepping; the SQLite db is the source
of truth for queries.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import secrets
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────

_SCHEMA_VERSION = 1

# Field-name patterns that must be redacted from any payload.
# Note: build the pattern without (?i) inline flags (Python 3.11+ rejects
# global flags not at the start of an alternation). We use re.IGNORECASE
# at compile time instead.
_SENSITIVE_KEY_PATTERNS = [
    r"token",
    r"password",
    r"passwd",
    r"secret",
    r"api[_-]?key",
    r"api[_-]?id",          # telegram api_id pairs with api_hash
    r"api[_-]?hash",
    r"session",
    r"auth",
    r"credential",
    r"private[_-]?key",
]
_SENSITIVE_RE = re.compile("|".join(_SENSITIVE_KEY_PATTERNS), re.IGNORECASE)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_run_id() -> str:
    # 16-char hex; sortable enough for human reading, unique enough for runs
    return secrets.token_hex(8)


def _default_data_dir() -> Path:
    """Return the default observability data directory.

    Respects XDG_DATA_HOME on Linux; falls back to ~/.local/share.
    On other platforms, uses ~/AppData/Local (Windows-style) or ~/Library
    (macOS-style) — but IntelliFile is Linux-first so this is a minor concern.
    """
    if sys.platform.startswith("linux") or sys.platform == "darwin":
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    else:
        base = str(Path.home() / "AppData" / "Local")
    p = Path(base) / "intellifile" / "observability"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ─── Redaction ─────────────────────────────────────────────────────────────


def redact(obj: Any, debug: bool = False) -> Any:
    """Return a redacted copy of ``obj``.

    - If ``debug`` is True, no redaction is applied (caller takes
      responsibility).
    - Otherwise, any dict key whose name matches the sensitive-key
      regex is replaced with the literal string ``<REDACTED>``.
    - Lists and nested dicts are recursed.
    - Non-dict, non-list objects are returned as-is.
    """
    if debug:
        return obj
    if isinstance(obj, dict):
        return {
            k: ("<REDACTED>" if _SENSITIVE_RE.search(str(k)) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


# ─── Dataclasses ───────────────────────────────────────────────────────────


@dataclass
class RunRecord:
    """A single run of a component action."""

    run_id: str
    session_id: str | None = None
    component: str = ""           # e.g. "smart_tagger", "search.hybrid"
    action: str = ""              # e.g. "tag_folder", "query"
    start_ts: str = ""
    end_ts: str = ""
    status: str = "running"       # running | success | failed | cancelled
    duration_ms: int = 0
    input_summary: dict = field(default_factory=dict)
    output_summary: dict = field(default_factory=dict)
    error_summary: str = ""
    redaction_level: str = "default"  # default | debug

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArtifactRecord:
    """An output produced by a run."""

    artifact_id: str
    run_id: str
    kind: str = ""                # file | index | report | tag_set | ...
    path: str = ""                # where it was stored
    component: str = ""
    component_version: str = ""
    input_class: str = ""         # e.g. "folder", "image", "pdf"
    success: bool = True
    created_ts: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class NoteRecord:
    """A manual operator/user note attached to something."""

    note_id: str
    target_kind: str = ""         # run | file | folder | ocr_job | action
    target_id: str = ""           # run_id, file path, folder path, etc.
    severity: str = "info"        # info | warn | error | block
    tags: list[str] = field(default_factory=list)
    body: str = ""
    created_ts: str = ""


@dataclass
class QueueItem:
    """A tracked future improvement item."""

    item_id: str
    source: str = ""              # "repeated_failure" | "note" | "manual"
    component: str = ""
    title: str = ""
    detail: str = ""
    occurrences: int = 1
    last_seen_ts: str = ""
    status: str = "open"          # open | resolved | wontfix


# ─── Schema ────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT,
    component TEXT NOT NULL,
    action TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    input_summary TEXT,   -- JSON
    output_summary TEXT,  -- JSON
    error_summary TEXT,
    redaction_level TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_component ON runs(component);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_start_ts ON runs(start_ts);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT,
    path TEXT,
    component TEXT,
    component_version TEXT,
    input_class TEXT,
    success INTEGER DEFAULT 1,
    created_ts TEXT,
    extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_component ON artifacts(component);

CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    target_kind TEXT,
    target_id TEXT,
    severity TEXT,
    tags TEXT,           -- JSON array
    body TEXT,
    created_ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_notes_target ON notes(target_kind, target_id);
CREATE INDEX IF NOT EXISTS idx_notes_severity ON notes(severity);

CREATE TABLE IF NOT EXISTS improvement_queue (
    item_id TEXT PRIMARY KEY,
    source TEXT,
    component TEXT,
    title TEXT,
    detail TEXT,
    occurrences INTEGER DEFAULT 1,
    last_seen_ts TEXT,
    status TEXT DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON improvement_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_component ON improvement_queue(component);

CREATE TABLE IF NOT EXISTS system_profile (
    profile_id INTEGER PRIMARY KEY CHECK (profile_id = 1),
    app_version TEXT,
    python_version TEXT,
    platform TEXT,
    captured_ts TEXT,
    feature_flags TEXT,           -- JSON
    dependency_health TEXT,       -- JSON
    model_service_availability TEXT  -- JSON
);
"""


# ─── Store ─────────────────────────────────────────────────────────────────


class ObservabilityStore:
    """SQLite + JSONL store for runs, artifacts, notes, and queue items.

    Single-process, thread-safe via a coarse lock around writes. Reads
    are non-locking (SQLite handles concurrent readers).
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or _default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "observability.db"
        self.runs_jsonl = self.data_dir / "runs.jsonl"
        self.notes_jsonl = self.data_dir / "notes.jsonl"
        self._lock = __import__("threading").Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        with self._lock, self._conn() as c:
            c.executescript(_SCHEMA)
            c.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(_SCHEMA_VERSION)),
            )
            c.commit()

    # ── Runs ──────────────────────────────────────────────────────────

    def start_run(
        self,
        component: str,
        action: str,
        session_id: str | None = None,
        input_summary: dict | None = None,
        debug: bool = False,
    ) -> RunRecord:
        run = RunRecord(
            run_id=_new_run_id(),
            session_id=session_id,
            component=component,
            action=action,
            start_ts=_utc_now_iso(),
            input_summary=redact(input_summary or {}, debug=debug),
            redaction_level="debug" if debug else "default",
        )
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO runs
                   (run_id, session_id, component, action, start_ts, status,
                    input_summary, redaction_level)
                   VALUES (?, ?, ?, ?, ?, 'running', ?, ?)""",
                (
                    run.run_id, run.session_id, run.component, run.action,
                    run.start_ts, json.dumps(run.input_summary, ensure_ascii=False),
                    run.redaction_level,
                ),
            )
            c.commit()
        self._append_jsonl(self.runs_jsonl, run.to_dict())
        return run

    def finish_run(
        self,
        run_id: str,
        status: str = "success",
        output_summary: dict | None = None,
        error_summary: str = "",
        debug: bool = False,
    ) -> None:
        end_ts = _utc_now_iso()
        # Compute duration from the stored start_ts
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT start_ts FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                return
            start_ts = row["start_ts"]
            try:
                start_dt = datetime.fromisoformat(start_ts)
                end_dt = datetime.fromisoformat(end_ts)
                duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
            except Exception:
                duration_ms = 0
            out_red = redact(output_summary or {}, debug=debug)
            c.execute(
                """UPDATE runs SET end_ts = ?, status = ?, duration_ms = ?,
                   output_summary = ?, error_summary = ? WHERE run_id = ?""",
                (
                    end_ts, status, duration_ms,
                    json.dumps(out_red, ensure_ascii=False),
                    error_summary[:2000], run_id,
                ),
            )
            c.commit()
            updated_row = c.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if updated_row:
            self._append_jsonl(
                self.runs_jsonl,
                {k: updated_row[k] for k in updated_row.keys()},
            )
        # Repeated-failure → improvement queue
        if status == "failed":
            self._bump_queue(
                source="repeated_failure",
                component="",
                title=f"Run failed: {updated_row['component']}/{updated_row['action']}"
                if updated_row else "Run failed",
                detail=error_summary[:500],
            )

    # ── Artifacts ─────────────────────────────────────────────────────

    def record_artifact(
        self,
        run_id: str,
        kind: str,
        path: str,
        component: str = "",
        component_version: str = "",
        input_class: str = "",
        success: bool = True,
        extra: dict | None = None,
        debug: bool = False,
    ) -> ArtifactRecord:
        art = ArtifactRecord(
            artifact_id=_new_run_id(),
            run_id=run_id,
            kind=kind,
            path=path,
            component=component,
            component_version=component_version,
            input_class=input_class,
            success=success,
            created_ts=_utc_now_iso(),
            extra=redact(extra or {}, debug=debug),
        )
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO artifacts
                   (artifact_id, run_id, kind, path, component, component_version,
                    input_class, success, created_ts, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    art.artifact_id, art.run_id, art.kind, art.path,
                    art.component, art.component_version, art.input_class,
                    int(art.success), art.created_ts,
                    json.dumps(art.extra, ensure_ascii=False),
                ),
            )
            c.commit()
        return art

    # ── Notes ─────────────────────────────────────────────────────────

    def add_note(
        self,
        target_kind: str,
        target_id: str,
        body: str,
        severity: str = "info",
        tags: list[str] | None = None,
    ) -> NoteRecord:
        note = NoteRecord(
            note_id=_new_run_id(),
            target_kind=target_kind,
            target_id=target_id,
            severity=severity,
            tags=tags or [],
            body=body,
            created_ts=_utc_now_iso(),
        )
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT INTO notes
                   (note_id, target_kind, target_id, severity, tags, body, created_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    note.note_id, note.target_kind, note.target_id,
                    note.severity, json.dumps(note.tags, ensure_ascii=False),
                    note.body, note.created_ts,
                ),
            )
            c.commit()
        self._append_jsonl(self.notes_jsonl, asdict(note))
        # Severity warn/error/block → improvement queue
        if severity in {"warn", "error", "block"}:
            self._bump_queue(
                source="note",
                component="",
                title=f"{severity.upper()} note on {target_kind}:{target_id}",
                detail=body[:500],
            )
        return note

    # ── Improvement queue ─────────────────────────────────────────────

    def _bump_queue(
        self,
        source: str,
        component: str,
        title: str,
        detail: str,
    ) -> None:
        """Either create or increment an existing queue item."""
        # Match by (source, title) — keeps the queue small
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT item_id, occurrences FROM improvement_queue "
                "WHERE source = ? AND title = ? AND status = 'open'",
                (source, title),
            ).fetchone()
            now = _utc_now_iso()
            if row:
                c.execute(
                    """UPDATE improvement_queue
                       SET occurrences = ?, last_seen_ts = ?, detail = ?
                       WHERE item_id = ?""",
                    (row["occurrences"] + 1, now, detail, row["item_id"]),
                )
            else:
                c.execute(
                    """INSERT INTO improvement_queue
                       (item_id, source, component, title, detail,
                        occurrences, last_seen_ts, status)
                       VALUES (?, ?, ?, ?, ?, 1, ?, 'open')""",
                    (_new_run_id(), source, component, title, detail, now),
                )
            c.commit()

    def resolve_queue_item(self, item_id: str, status: str = "resolved") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE improvement_queue SET status = ? WHERE item_id = ?",
                (status, item_id),
            )
            c.commit()

    # ── System profile ────────────────────────────────────────────────

    def capture_system_profile(
        self,
        app_version: str,
        feature_flags: dict,
        dependency_health: dict,
        model_service_availability: dict,
    ) -> None:
        payload = {
            "app_version": app_version,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "captured_ts": _utc_now_iso(),
            "feature_flags": json.dumps(feature_flags, ensure_ascii=False),
            "dependency_health": json.dumps(dependency_health, ensure_ascii=False),
            "model_service_availability": json.dumps(
                model_service_availability, ensure_ascii=False
            ),
        }
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO system_profile
                   (profile_id, app_version, python_version, platform,
                    captured_ts, feature_flags, dependency_health,
                    model_service_availability)
                   VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload["app_version"], payload["python_version"],
                    payload["platform"], payload["captured_ts"],
                    payload["feature_flags"], payload["dependency_health"],
                    payload["model_service_availability"],
                ),
            )
            c.commit()

    # ── Reads ─────────────────────────────────────────────────────────

    def list_recent_runs(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM runs ORDER BY start_ts DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def list_notes(
        self, target_kind: str | None = None, target_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        q = "SELECT * FROM notes"
        params: list = []
        clauses = []
        if target_kind:
            clauses.append("target_kind = ?")
            params.append(target_kind)
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_ts DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def list_queue(self, status: str = "open") -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM improvement_queue WHERE status = ? "
                    "ORDER BY last_seen_ts DESC",
                    (status,),
                ).fetchall()
            ]

    def list_artifacts(self, run_id: str | None = None, limit: int = 50) -> list[dict]:
        q = "SELECT * FROM artifacts"
        params: list = []
        if run_id:
            q += " WHERE run_id = ?"
            params.append(run_id)
        q += " ORDER BY created_ts DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, params).fetchall()]

    def get_system_profile(self) -> dict | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM system_profile WHERE profile_id = 1"
            ).fetchone()
            return dict(r) if r else None

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _append_jsonl(path: Path, obj: dict) -> None:
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"Failed to append to {path}: {e}")


# ─── Module-level singleton ────────────────────────────────────────────────

_default_store: ObservabilityStore | None = None


def get_store() -> ObservabilityStore:
    """Return the process-wide default ObservabilityStore."""
    global _default_store
    if _default_store is None:
        _default_store = ObservabilityStore()
    return _default_store


# ─── Context manager helper ────────────────────────────────────────────────


class RunContext:
    """``with RunContext('comp', 'action') as run:`` — auto-finishes on exit.

    On exception, the run is marked 'failed' with the error summary set
    to ``repr(exc)``.
    """

    def __init__(
        self,
        component: str,
        action: str,
        session_id: str | None = None,
        input_summary: dict | None = None,
        debug: bool = False,
        store: ObservabilityStore | None = None,
    ):
        self._store = store or get_store()
        self._debug = debug
        self.run = self._store.start_run(
            component=component,
            action=action,
            session_id=session_id,
            input_summary=input_summary,
            debug=debug,
        )

    def __enter__(self) -> RunRecord:
        return self.run

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self._store.finish_run(self.run.run_id, status="success")
        else:
            self._store.finish_run(
                self.run.run_id,
                status="failed",
                error_summary=repr(exc)[:2000],
                debug=self._debug,
            )
        return False  # do not suppress


__all__ = [
    "ArtifactRecord",
    "NoteRecord",
    "ObservabilityStore",
    "QueueItem",
    "RunContext",
    "RunRecord",
    "get_store",
    "redact",
]
