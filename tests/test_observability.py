"""Tests for the observability foundation.

Verifies the five required behaviors:
  1. system self-profile capture + read
  2. structured run logging (start → finish, duration computed)
  3. artifact registry (record + list by run)
  4. manual notes (add + list by target)
  5. improvement queue (bump on failure + on warn-or-worse notes)

Plus privacy:
  - redact() replaces sensitive-key values with <REDACTED>
  - debug=True bypasses redaction
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.db.observability import (
    ObservabilityStore,
    RunContext,
    redact,
)


@pytest.fixture
def store(tmp_path: Path) -> ObservabilityStore:
    return ObservabilityStore(data_dir=tmp_path / "obs")


def test_redact_replaces_sensitive_keys():
    payload = {
        "api_key": "ghp_secret",
        "token": "abc",
        "Username": "alice",  # not sensitive
        "session_string": "very-secret",
        "nested": {"PASSWORD": "x", "ok": "y"},
        "items": [{"api_id": 123, "name": "foo"}],
    }
    out = redact(payload)
    assert out["api_key"] == "<REDACTED>"
    assert out["token"] == "<REDACTED>"
    assert out["Username"] == "alice"
    assert out["session_string"] == "<REDACTED>"
    assert out["nested"]["PASSWORD"] == "<REDACTED>"
    assert out["nested"]["ok"] == "y"
    assert out["items"][0]["api_id"] == "<REDACTED>"
    assert out["items"][0]["name"] == "foo"


def test_redact_debug_bypasses():
    payload = {"api_key": "ghp_secret"}
    assert redact(payload, debug=True) == payload


def test_run_start_finish_records_duration(store: ObservabilityStore):
    run = store.start_run(
        component="search.hybrid",
        action="query",
        input_summary={"query": "abc"},
    )
    assert run.status == "running"
    assert run.component == "search.hybrid"
    assert run.action == "query"

    store.finish_run(
        run.run_id,
        status="success",
        output_summary={"hits": 5},
    )
    recent = store.list_recent_runs(limit=10)
    assert len(recent) == 1
    finished = recent[0]
    assert finished["status"] == "success"
    assert finished["duration_ms"] >= 0
    assert json.loads(finished["input_summary"]) == {"query": "abc"}
    assert json.loads(finished["output_summary"]) == {"hits": 5}


def test_run_failure_bumps_queue(store: ObservabilityStore):
    run = store.start_run(component="tagger", action="tag_folder")
    store.finish_run(
        run.run_id,
        status="failed",
        error_summary="permission denied",
    )
    queue = store.list_queue()
    assert len(queue) >= 1
    assert any("tagger" in item["title"] for item in queue)


def test_repeated_failure_increments_queue(store: ObservabilityStore):
    for _ in range(3):
        run = store.start_run(component="tagger", action="tag_folder")
        store.finish_run(run.run_id, status="failed", error_summary="x")
    queue = store.list_queue()
    assert any(item["occurrences"] == 3 for item in queue)


def test_artifact_recorded_and_listed(store: ObservabilityStore):
    run = store.start_run(component="extractor", action="extract")
    store.record_artifact(
        run_id=run.run_id,
        kind="report",
        path="/tmp/out.json",
        component="extractor",
        component_version="2.2.0.dev0",
        input_class="folder",
        success=True,
    )
    arts = store.list_artifacts(run_id=run.run_id)
    assert len(arts) == 1
    assert arts[0]["kind"] == "report"
    assert arts[0]["path"] == "/tmp/out.json"


def test_note_added_and_listed(store: ObservabilityStore):
    note = store.add_note(
        target_kind="file",
        target_id="/tmp/foo.txt",
        body="needs re-tagging",
        severity="warn",
        tags=["tagging"],
    )
    assert note.severity == "warn"
    listed = store.list_notes(target_kind="file", target_id="/tmp/foo.txt")
    assert len(listed) == 1
    assert listed[0]["body"] == "needs re-tagging"
    # Severity warn → improvement queue
    assert any("WARN note" in item["title"] for item in store.list_queue())


def test_run_context_success(store: ObservabilityStore):
    with RunContext("comp", "act", store=store, input_summary={"x": 1}) as run:
        assert run.component == "comp"
    recent = store.list_recent_runs()
    assert recent[0]["status"] == "success"


def test_run_context_failure(store: ObservabilityStore):
    with pytest.raises(ValueError):
        with RunContext("comp", "act", store=store):
            raise ValueError("boom")
    recent = store.list_recent_runs()
    assert recent[0]["status"] == "failed"
    assert "boom" in recent[0]["error_summary"]


def test_system_profile_capture_and_read(store: ObservabilityStore):
    store.capture_system_profile(
        app_version="2.2.0.dev0",
        feature_flags={"semantic_search": False},
        dependency_health={"ollama": "ok", "chromadb": "ok"},
        model_service_availability={"embeddings": "online"},
    )
    prof = store.get_system_profile()
    assert prof is not None
    assert prof["app_version"] == "2.2.0.dev0"
    assert json.loads(prof["feature_flags"]) == {"semantic_search": False}


def test_redaction_in_input_summary(store: ObservabilityStore):
    run = store.start_run(
        component="api",
        action="login",
        input_summary={"api_key": "secret", "username": "alice"},
    )
    recent = store.list_recent_runs()
    parsed = json.loads(recent[0]["input_summary"])
    assert parsed["api_key"] == "<REDACTED>"
    assert parsed["username"] == "alice"


def test_jsonl_mirrors_runs(store: ObservabilityStore, tmp_path: Path):
    run = store.start_run(component="c", action="a")
    store.finish_run(run.run_id, status="success")
    runs_jsonl = store.data_dir / "runs.jsonl"
    assert runs_jsonl.exists()
    lines = runs_jsonl.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1
    parsed = json.loads(lines[-1])
    assert parsed["component"] == "c"
