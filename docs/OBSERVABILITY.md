# Observability Foundation (IntelliFile)

> Local-first, SQLite + JSONL, privacy-aware. No telemetry, no network.

This module provides a lightweight observability + notes foundation
for IntelliFile. It is the smallest useful surface that satisfies the
five required behaviors:

1. **System self-profile** — app version, env, feature flags,
   dependency health, model/service availability.
2. **Structured run logging** — `run_id`, `session_id`, component,
   action, start/end timestamps, status, duration, input/output
   summaries, error summary, redaction level.
3. **Artifact/result registry** — what was produced, where, by which
   component/version, from what class of input, success/failure.
4. **Manual operator/user notes** — attach to runs, files, folders,
   OCR jobs, or actions. Persisted + reviewable. Tags + severity.
5. **Improvement queue** — repeated failures and meaningful notes are
   traced as future improvement items. Small and practical, not a
   full issue tracker.

Plus **privacy-aware defaults**:

- No secret values are ever logged.
- Sensitive field names (token, password, api_key, api_id, api_hash,
  session, auth, credential, private_key) are matched against a regex
  blocklist and replaced with `<REDACTEDED>` before any write.
- Raw payloads are only stored when `debug=True` is explicitly passed.
- File paths are stored as given (local tool, local user — paths are
  not considered sensitive for a local-first file manager).

## Storage layout

```
$XDG_DATA_HOME/intellifile/observability/   (or ~/.local/share/...)
├── observability.db     — SQLite (source of truth)
├── runs.jsonl           — append-only NDJSON mirror of run events
└── notes.jsonl          — append-only NDJSON mirror of note events
```

The JSONL mirror is for `tail -f` / grep workflows; the SQLite db is
the source of truth for queries.

## API surface

```python
from src.db.observability import (
    get_store,          # module-level singleton
    ObservabilityStore, # explicit construction (e.g. for tests)
    RunContext,         # `with RunContext('comp','act') as run:`
    redact,             # explicit redaction helper
)

store = get_store()

# 1. System profile
store.capture_system_profile(
    app_version="2.2.0.dev0",
    feature_flags={"semantic_search": False},
    dependency_health={"ollama": "ok"},
    model_service_availability={"embeddings": "online"},
)

# 2. Structured run logging (context-manager form, auto-finishes)
with RunContext(
    component="search.hybrid",
    action="query",
    input_summary={"query": "abc", "api_key": "ghp_xxx"},  # auto-redacted
) as run:
    # ... do work ...
    pass
# On exit: status='success' (or 'failed' if an exception was raised)

# 2b. Explicit form
run = store.start_run(component="tagger", action="tag_folder",
                     input_summary={"path": "/tmp"})
store.finish_run(run.run_id, status="success",
                output_summary={"tagged": 5})

# 3. Artifact registry
store.record_artifact(
    run_id=run.run_id, kind="report", path="/tmp/out.json",
    component="tagger", component_version="2.2.0.dev0",
    input_class="folder", success=True,
)

# 4. Manual notes
store.add_note(
    target_kind="file",          # run | file | folder | ocr_job | action
    target_id="/tmp/foo.txt",
    body="needs re-tagging",
    severity="warn",             # info | warn | error | block
    tags=["tagging"],
)

# 5. Improvement queue (auto-bumped on failures + warn-or-worse notes)
queue = store.list_queue(status="open")
# Resolve when addressed:
store.resolve_queue_item(item_id, status="resolved")
```

## Reads

```python
store.list_recent_runs(limit=50)
store.list_notes(target_kind="file", target_id="/tmp/foo.txt")
store.list_artifacts(run_id=run_id)
store.list_queue(status="open")
store.get_system_profile()
```

## What this is NOT

- **Not a metrics aggregation system.** No Prometheus, no OpenTelemetry
  exporters, no dashboards. Just a local SQLite + JSONL.
- **Not a remote telemetry pipeline.** Nothing leaves the user's
  machine. There is no upload code path.
- **Not a full issue tracker.** The improvement queue is intentionally
  tiny — it captures repeated failures and meaningful notes as future
  work items, then is meant to be triaged into actual GitHub issues
  periodically.
- **Not UI-exposed yet.** This PR only adds the backend/storage. UI
  surfacing (Activity panel, Notes panel, Health/Diagnostics panel)
  will follow in a separate PR once the storage shape is reviewed.

## Verification

- 12 unit tests in `tests/test_observability.py` cover all five
  behaviors + privacy defaults + the JSONL mirror.
- All tests pass.

## Omni adoption

The same module shape can be copied into Omni's `src/observability/`
(or imported as a shared utility if a shared library is later
extracted). For now, this is IntelliFile-only — per ecosystem policy,
no cross-repo coupling unless via a clearly defined boundary.
