# Review instructions

Rules for automated pull request review. The Claude review workflow
(`.github/workflows/claude-review.yml`) reads this file from the pull request's
base branch; Claude Code Review reads it from the default branch and applies the
exclusions and nit cap only when that branch is protected. Project rules are in
[AGENTS.md](AGENTS.md); this file sets what a review reports and how severely.
Keep it short, because every review reads it.

## What Important means here

Important is a defect to fix before merge:

- Wrong results, a crash, lost data or a regression in the `vraptor` runtime, a
  `utils/` script, a launcher or a skill's documented workflow.
- Lost or changed Velociraptor provenance. Flow, hunt, client, artifact, scope
  and coverage identity stay exact, because Velociraptor is the evidence
  authority.
- Remote collection, hunt creation, retries, cancellation or other server
  mutation that can run without the operator authorization in the
  [operation authorization reference](docs/reference/velociraptor-operation-authorization.md).
- Secrets, credentials, API-client YAML, customer or case data, private
  infrastructure details or local runtime state committed, logged or written
  to reports.
- Content that `config/public-deny-patterns.tsv` forbids: private names, hosts,
  identities or token shapes (`./utils/validate-public-export.py` checks it).
- A `SKILL.md`, reference, doc or `README.md` that contradicts code, CLI flags
  or defaults changed in the same PR.
- A behavior test deleted, weakened or skipped without equivalent coverage.
  Removing redundant tests, or tests that only pin prose, spelling or layout,
  is fine when the PR explains it.
- Untrusted evidence or model output used in a shell command, VQL query or file
  path without quoting or validation.

## Always check

- Changed CLI flags, defaults, outputs or file layouts are updated in the
  affected `SKILL.md`, references, docs and `README.md`, and stale text is
  removed.
- Skill folder and file names stay unchanged (a rename unlinks saved
  selections), and each `SKILL.md` frontmatter `name` matches its folder.
- Velociraptor and prep-dfir-tools `SKILL.md` files stay within 500 lines and
  30,000 bytes.
- Portable tests go in `tests/core` and need no server or network.
- Files under `config/sync-manifest.tsv` rows are maintained upstream. Note it
  in the summary when a PR edits one directly and its description does not say
  so, or adds an upstream test file without a manifest row.
- A hand-ported upstream change to a file in `config/sync-held.tsv` records the
  new fingerprint in that row.
- Removed or renamed code leaves no references in `utils/`, `skills/`, the root
  `vraptor` and `dfir` launchers, or tests that load modules by file path.

## Do not report

- Formatting, import order, naming or other style preferences; ruff and CI
  cover lint.
- Problems in unchanged code, unless this PR makes them reachable or worse.
- Missing tests for documentation-only changes.
- The format of the PR description.
- Concerns you cannot tie to a concrete input or code path.

## Cap the nits

Report at most three nits per review, and none on a re-review.
