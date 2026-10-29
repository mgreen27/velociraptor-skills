# Analysis correction and recovery

Analysis correction is distinct from provider/transport retry. A provider call
must succeed before an output-validation defect can trigger correction. Failed
authentication, cancellation, deterministic token-limit failures and exhausted
transport retries do not receive another call from the correction loop.

The shared analyst TOML supports:

```toml
[analysis_defaults]
validation_correction_attempts = 2
synthesis_correction_attempts = 2
```

Each value counts **extra attempts**, so the defaults permit three total attempts
per chunk or synthesis stage. The range is 0–5; zero disables correction. Non-empty
`AI_SKILLS_ANALYST_AGENT_VALIDATION_CORRECTION_ATTEMPTS` and
`AI_SKILLS_ANALYST_AGENT_SYNTHESIS_CORRECTION_ATTEMPTS` override TOML values.
`vraptor ai config` reports effective values and provenance. Corrections remain
inside the existing scheduler and model token/deadline guards. Provider retries
continue to use `AI_SKILLS_ANALYST_AGENT_MAX_RETRIES` separately.

## Resume failed host analysis

```bash
vraptor analyze --id IR1234 --client C.1234abcd \
  --request-id REQUEST_ID --question 'Was malicious execution observed?' \
  --synthesis full --retry-failed
```

Use the original question, analysis settings, time bounds and case connection.
The exact request is required; the option cannot be combined with reset, force,
preparation or report-only rebuilding. It never recollects evidence.
Generated continuation commands preserve `--synthesis none|full`. When recovering
final synthesis, keep `--synthesis full` (also the default). Explicit
`--synthesis none` skips final review; `--skip-ai` disables all model work.

Accepted artifacts are reused after source and report-hash verification. Failed
artifacts reacquire their existing flow rows once; accepted chunks are restored
from reference-only decisions, revalidated and hydrated against those rows. Only
failed chunks and their dependent synthesis are sent to the model. Source,
question, configuration or prompt changes invalidate reuse. A failed final host
review reuses accepted artifact candidates. Legacy runs without these chunk
checkpoints must review the failed artifact again.

`--reset-artifact` and `--reset-analysis` still explicitly discard accepted work.
Ordinary reruns keep terminal failed artifacts held; use `--retry-failed` to
resume them. Final synthesis can also be resumed by rerunning the saved request.
For a synthesis-only failure with accepted checkpoints, `vraptor summarize
--checkpoint /path/to/request-analysis.json` validates the retained inputs and
runs only final synthesis, without querying flows or rerunning artifact analysis.
Both forms review the saved request's scope. `--reset-artifact` invalidates an
artifact's accepted work; it does not narrow a multi-artifact request to that artifact.

## Troubleshooting and retention

`FINDING` confidence accepts only `low`, `medium`, or `high`; chunk and synthesis
validators normalize surrounding whitespace and casing. Confidence measures
evidence certainty, separately from report priority. Priority-only labels such as
`critical` are rejected, as are numeric scores and unknown labels; no confidence
is inferred or silently substituted. `invalid_confidence` diagnostics include the
allowed values and a safe reason code. Recognized priority-only labels can be
retained as `received`; arbitrary rejected text is excluded from diagnostics.

Every host analysis writes `analysis/analysis-diagnostics.json` under its request.
It records stage/task identity, attempts, provider category, elapsed time,
affected chunk row ranges, structured validator defects, allowed references and
response hashes. Up to 200 task records are retained, prioritizing failures, with
an explicit omitted count. The normal result and report include failed stages,
the diagnostic path and a shell-quoted resume command. Model output, provider
bodies, credentials and source values are excluded. `--debug` adds the existing
provider diagnostics; `--debug-chunk-prompts` explicitly retains evidence-bearing
prompts/responses.

Synthesis distinguishes candidate evidence references from accepted context
references. A context-only row cannot be promoted to `EVIDENCE`, and a candidate
row cannot be emitted as `CONTEXT` unless it was also accepted as context.
Downgraded candidates use `DISPOSITION`; Python creates their lead/context rows.
Wrong-role, unknown-source and wrong-candidate errors include structured defects
and bounded allowed references in correction prompts and diagnostics. If there
are no accepted context references, `RELEVANT_CONTEXT` must contain `None.`.
References are never guessed, silently reassigned or dropped to make review pass.

Supported-candidate mapping errors distinguish `missing_mapped_finding` from
`mapped_finding_evidence_mismatch`. The latter includes the candidate ID, output
finding ID, selected disposition references, missing evidence references and the
allowed intersection of candidate evidence with that output finding. Every
selected disposition reference must appear as an `EVIDENCE` record under the same
output finding ID. Merged findings include the union of selected references from
their supported candidate dispositions; candidate rows are never silently added.

`summarize` writes a separate `synthesis-diagnostics.json` beside its checkpoint.
This is the latest synthesis invocation, including cache hits, not a replacement
for the original `analysis-diagnostics.json`. It records operation ID, provider,
model, timestamps, status, bounded provider-call timing and per-attempt validation
diagnostics. It retains at most 200 task/call records, seven correction attempts
per task and 50 defects/references per diagnostic list; omissions are counted.
No raw source values, response bodies or credentials are retained. The file is
updated before dispatch and after each call so an interrupted run is identifiable.
Cache hits show zero model calls. JSON and text output expose the diagnostics path.
Cache hits regenerate the derived summary using current reporting limits without
changing the accepted checkpoint or calling a model. Diagnostic identifiers are
restricted to protocol references and known vocabulary; arbitrary model-supplied
IDs and labels are excluded even when they contain only letters or spaces.
Checkpoint conflicts preserve the changed checkpoint and retain failure diagnostics.

`artifact-recovery/*.json` retains one current generation of accepted compact
chunk decisions per artifact, with hashes and no copied row fields. Request
checkpoints retain accepted artifact candidates, plans, report hashes and final
dispositions, permitting recovery after switching requests. Current host state
and `analysis-host.md` remain atomically replaced derived views. Request switching
or schema mismatch no longer creates `previous-analysis/state-*` snapshots.
Existing historical snapshots and standalone `run_analyst_agent --replace`
bundles are unaffected. Finder `.DS_Store` metadata is ignored by tree validation.

Artifact reports distinguish review completion over exposed rows from collection
completion. Final review checks the evidence-to-claim link, tactics, confidence
and benign explanations, and cannot promote confidence beyond supporting input
candidates. Deterministic checks enforce references and confidence bounds;
semantic accuracy still requires model qualification. Exact normalized duplicate
limitations are removed, while the final reviewer is instructed to consolidate
equivalent prose without losing distinct coverage gaps.

## Offline validation

```bash
.venv/bin/python -m pytest -q tests/test_analysis_recovery.py tests/test_host_final_review.py tests/test_synthesis_reference_recovery.py tests/test_saved_synthesis_diagnostics.py tests/test_analysis_operator_status.py tests/test_agent_analysis_defaults.py tests/core/test_core_collection_analysis_integration.py tests/core/test_core_host_analysis_state.py
```

Synthetic tests cover correction budgets, terminal failures, failed-chunk reuse,
source/configuration invalidation, corruption, request switching, retained
diagnostics, confidence validation, coverage labels and atomic state publication.
