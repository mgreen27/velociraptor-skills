"""Failed-chunk review records, waivers and opt-in evidence; no live provider."""

import asyncio
import json
import re
import stat

import pytest
import test_collection_analysis_runtime as runtime_fixtures
from test_collection_analysis_runtime import (
    chunk_output,
    spec,
    successful,
    synthesis_output,
)
from vraptor.analyze import command, coordinator, prompt_debug, recovery, runtime, summary
from vraptor.artifacts import persistence

SCOPE = {"kind": "host", "client_id": "C.1", "request_id": "R1"}


def _failure(task_id="artifact-task-1-chunk-0", **inputs):
    return {
        "task_id": task_id,
        "stage": "chunk",
        "status": "failed",
        "attempts": 1,
        "inputs": {"input_sha256": "a" * 64, "row_start": 1, "row_end": 4, **inputs},
        "attempt_history": [
            {
                "attempt": 1,
                "status": "failed",
                "category": "validation_failed",
                "defects": [{"code": "invalid_reference"}],
            }
        ],
    }


def _record(ledger, key="Artifact.0:artifact-task-1-chunk-0", **inputs):
    ledger.record_failure(
        key,
        _failure(key.split(":", 1)[1], **inputs),
        identity={"artifact": "Artifact.0", "flow_id": "F.1"},
        budget={"validation_correction_attempts": 2, "provider_max_retries": 2},
        next_steps={"retry": "vraptor collect analyze --retry-failed"},
    )
    return key


def test_exhausted_chunk_is_recorded_and_a_waiver_publishes_the_accepted_chunks(tmp_path):
    rows = [
        {"When": str(i), "Command": "PRIVATE_SOURCE_VALUE_" + "x" * 250}
        for i in range(4)
    ]
    plan, chunks = runtime_fixtures.CollectionAnalysisRuntimeTest().build(
        artifact_count=1, rows=rows, limit=150
    )
    assert len(chunks) > 1
    failed_task = next(iter(plan["chunks"]))["task_id"] + "-chunk-0"
    key = f"Artifact.0:{failed_task}"
    path = tmp_path / "failed-chunks.json"
    ledger = recovery.FailedChunkLedger(path, SCOPE)
    calls = []

    def execute(task):
        calls.append(task.task_id)
        if task.metadata["stage"] == "chunk":
            output = "PRIVATE_MODEL_OUTPUT" if task.task_id == failed_task else chunk_output(task)
            return successful(task, output)
        return successful(task, synthesis_output(task))

    def chunk_failed(task, record, prompts):
        assert len(prompts) == 3 and "RETRY CORRECTION" in prompts[-1]
        ledger.record_failure(
            f"Artifact.0:{task.task_id}",
            recovery.task_diagnostics(record),
            identity={"artifact": "Artifact.0", "flow_id": "F.1"},
            budget={"validation_correction_attempts": 2, "provider_max_retries": 2},
            next_steps={"retry": "retry"},
        )

    def run(**callbacks):
        return asyncio.run(
            runtime.execute_analysis_workload_async(
                plan=plan,
                chunk_csv=chunks,
                question="What happened?",
                spec=spec(),
                workdir=tmp_path,
                output_dir=tmp_path,
                execute=execute,
                perform_scope_synthesis=False,
                chunk_recovery=recovery.ChunkRecovery(
                    tmp_path / "recovery.json", "same", reuse=True
                ),
                **callbacks,
            )
        )

    first = run(chunk_failed=chunk_failed)
    assert not command.artifact_analysis_run_is_cacheable(first)
    assert "PRIVATE" not in path.read_text()
    entry = ledger.entries()[key]
    assert (entry["status"], entry["attempts"], entry["failure_count"]) == ("failed", 3, 1)
    assert entry["final"]["category"] == "validation_failed"
    assert [item["status"] for item in entry["attempt_history"]] == [
        "retrying", "retrying", "failed",
    ]
    assert all(
        item["started_at"] <= item["completed_at"] for item in entry["attempt_history"]
    )
    assert re.fullmatch(r"S[0-9]+-R[0-9]+", entry["inputs"]["first_reference"])
    assert re.fullmatch(r"[0-9a-f]{64}", entry["inputs"]["input_sha256"])
    assert entry["inputs"]["row_start"] <= entry["inputs"]["row_end"]

    reloaded = recovery.FailedChunkLedger(path, SCOPE)
    assert reloaded.find(failed_task) == key
    reloaded.waive(key, "Rows reviewed manually in Velociraptor")
    before = len(calls)
    second = run(
        chunk_waiver=lambda task: reloaded.waiver(
            f"Artifact.0:{task.task_id}", recovery.fingerprint(task.prompt)
        )
    )
    assert failed_task not in calls[before:]
    assert second["status"] == "complete_with_failures"
    assert command.artifact_analysis_run_is_cacheable(second)
    waived = next(task for task in second["tasks"] if task["task_id"] == failed_task)
    assert waived["status"] == "waived"
    assert "Rows reviewed manually" in waived["error"]


def test_ledger_survives_reload_and_keeps_history_after_resolution(tmp_path):
    path = tmp_path / "failed-chunks.json"
    key = _record(recovery.FailedChunkLedger(path, SCOPE))
    ledger = recovery.FailedChunkLedger(path, SCOPE)
    _record(ledger)
    assert ledger.entries()[key]["failure_count"] == 2
    ledger.resolve(key)
    entry = recovery.FailedChunkLedger(path, SCOPE).entries()[key]
    assert entry["status"] == "resolved" and entry["resolved_at"]
    assert entry["attempt_history"]
    assert recovery.FailedChunkLedger(path, {**SCOPE, "request_id": "R2"}).entries() == {}


def test_waiver_needs_a_reason_and_lapses_when_the_input_changes(tmp_path):
    ledger = recovery.FailedChunkLedger(tmp_path / "failed-chunks.json", SCOPE)
    key = _record(ledger)
    with pytest.raises(ValueError):
        ledger.waive(key, "   ")
    ledger.waive(key, "Benign installer noise")
    with pytest.raises(ValueError):
        ledger.waive(key, "again")
    assert ledger.waiver(key, "a" * 64) == "Benign installer noise"
    assert ledger.waiver(key, "b" * 64) is None
    ledger.revoke_waivers()
    entry = ledger.entries()[key]
    assert entry["status"] == "failed" and entry["decision"]["revoked_at"]


def test_replanned_artifact_supersedes_chunks_it_no_longer_has(tmp_path):
    ledger = recovery.FailedChunkLedger(tmp_path / "failed-chunks.json", SCOPE)
    kept = _record(ledger, "Artifact.0:artifact-task-1-chunk-0")
    dropped = _record(ledger, "Artifact.0:artifact-task-1-chunk-70")
    ledger.supersede("Artifact.0", {kept})
    assert set(ledger.entries("failed")) == {kept}
    assert ledger.entries()[dropped]["status"] == "superseded"


def test_ledger_drops_resolved_entries_first(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, "FAILED_CHUNK_ENTRY_LIMIT", 2)
    ledger = recovery.FailedChunkLedger(tmp_path / "failed-chunks.json", SCOPE)
    first = _record(ledger, "Artifact.0:artifact-task-1-chunk-0")
    ledger.resolve(first)
    _record(ledger, "Artifact.0:artifact-task-1-chunk-1")
    _record(ledger, "Artifact.0:artifact-task-1-chunk-2")
    assert first not in ledger.entries()
    assert ledger.payload["omitted_chunk_count"] == 1


def test_ledger_keeps_only_identity_references_and_hashes(tmp_path):
    path = tmp_path / "failed-chunks.json"
    ledger = recovery.FailedChunkLedger(path, SCOPE)
    _record(ledger, first_reference="S0001-R1", last_reference="PRIVATE_VALUE", flow_id="F.1")
    entry = next(iter(ledger.entries().values()))
    assert entry["inputs"]["first_reference"] == "S0001-R1"
    assert "last_reference" not in entry["inputs"]
    assert "PRIVATE" not in path.read_text()
    record = persistence.classify_analysis_file(
        path, analysis_root=tmp_path, source_ids=["source-1"]
    )
    assert record["classification"] == "compact_state"


def test_terminal_hunt_failures_survive_the_attempt_cap():
    retrying = [
        {"chunk_id": f"{index:064x}", "ordinal": index, "attempt": 1, "status": "retrying"}
        for index in range(25)
    ]
    terminal = {"chunk_id": "f" * 64, "ordinal": 70, "attempt": 3, "status": "failed"}
    kept = coordinator._cap_attempt_failures([*retrying, terminal])
    assert len(kept) == coordinator.MAX_FAILED_CHUNK_ATTEMPTS_PER_RUN
    assert kept[-1] == terminal
    assert [item["ordinal"] for item in kept] == sorted(item["ordinal"] for item in kept)


def test_failed_chunk_evidence_is_written_only_when_requested(tmp_path):
    record = {
        "attempt_history": [
            {"error": "full validator message", "run": {"output": "raw response"}},
            {"error": "second message", "run": {"output": ""}},
        ]
    }
    assert prompt_debug.capture_failed_chunk(
        key="k", prompts=["prompt"], record=record, source_ids=["source-1"]
    ) is None
    with prompt_debug.session(tmp_path, 0, keep_failed=True):
        reference = prompt_debug.capture_failed_chunk(
            key="Artifact.0:task", prompts=["prompt one", "prompt two"],
            record=record, source_ids=["source-1"],
        )
    assert [(item["attempt"], item["kind"]) for item in reference["files"]] == [
        (1, "prompt"), (1, "response"), (1, "error"), (2, "prompt"), (2, "error"),
    ]
    directory = tmp_path / "debug" / "failed-chunks"
    saved = next(directory.iterdir())
    assert (saved / "failed-001.attempt-001.response.txt").read_text() == "raw response"
    assert stat.S_IMODE((saved / "failed-001.attempt-001.prompt.txt").stat().st_mode) == 0o600
    manifest = json.loads((saved / "manifest.json").read_text())
    assert manifest["chunks"][0]["persistence"]["classification"] == "interoperability_export"


def test_summary_and_failure_result_name_the_failed_chunk():
    chunk = {
        "key": "Artifact.0:artifact-task-1-chunk-70",
        "artifact": "Artifact.0",
        "status": "failed",
        "attempts": 3,
        "category": "validation_failed",
        "defect_codes": ["invalid_reference"],
        "row_start": 6900,
        "row_end": 7000,
        "task_chunk_index": 70,
        "task_chunk_count": 71,
        "first_reference": "S0003-R6901",
        "last_reference": "S0003-R7000",
    }
    line = summary.failed_chunk_line(chunk)
    assert "chunk 71/71 rows 6901-7000 (S0003-R6901..S0003-R7000)" in line
    assert "failed after 3 attempts: validation_failed; invalid_reference" in line
    rendered = summary.render_chat_summary(
        {
            "status": "complete_with_failures",
            "troubleshooting": {
                "diagnostics_file": "analysis-diagnostics.json",
                "failed_stages": [{"stage": "chunk", "task_id": "artifact-task-1-chunk-70"}],
                "failed_chunks_file": "failed-chunks.json",
                "failed_chunks": [chunk],
            },
        }
    )
    assert "Failed chunk record: `failed-chunks.json`" in rendered
    assert "--waive-failed-chunk KEY" in rendered
    assert "Failed `chunk`" not in rendered
    result = command.artifact_failure_result(
        artifact="Artifact.0", question="q", item={"total_rows": 7000},
        request_id="R1", error_class="RuntimeError",
        chunk_counts={"planned_chunks": 71, "accepted_chunks": 70},
        failed_chunks=[chunk],
    )
    assert result["coverage"]["accepted_chunks"] == 70
    assert line in result["limitations"]
    assert "--retry-failed" in result["bounded_follow_up"][0]
    assert "--waive-failed-chunk" in result["bounded_follow_up"][0]
    report = summary.render_artifact_report(result)
    assert "Chunk coverage: 70/71 chunks accepted" in report
    waived = summary.failed_chunk_line({**chunk, "status": "waived", "reason": "Reviewed"})
    assert waived.endswith("waived by operator, not analysed: Reviewed")
