---
name: full-eval-run
description: Prepare, run, judge, and verify final OpenClaw LoCoMo benchmark runs without contaminating memory state or reporting untraceable metrics. Use when asked to run a full eval, final benchmark row, LoCoMo comparison table, builtin-memory eval, judge an eval run, verify eval artifacts, or turn docs/runbooks/full-eval-run-principles.md into operational execution steps.
---

# Full Eval Run

## Overview

Run strict LoCoMo-style evals only when the scope, runtime isolation, skill isolation, auth, run artifacts, judging, and reporting gates are explicit and verifiable. Treat final benchmark rows as publishable claims: every metric must trace back to generated artifacts.

## Primary Reference

Read [references/full-eval-run-principles.md](references/full-eval-run-principles.md) before executing or accepting any full eval result. Use it as the source of truth for exact commands, required invariants, artifact checks, and reporting rules.

## Workflow

1. Declare the dataset scope before running anything. Distinguish smoke, sampled, and full `locomo10.json` runs.
2. Run a sample smoke eval first for the exact backend/profile/agent pattern you intend to use. Use `locomo10.json --sample <n>` or a tiny `locomo10_small.json` scope, still with `--agent-workspace`, and verify artifacts before any full eval.
3. Only after the smoke passes, run the full eval on all of `locomo10.json`. Never jump directly from config edits to a full final row.
4. Verify the repo is clean with `git status --short`; final rows require no output and `eval_repo_dirty=false`.
5. Use per-sample isolation for every publishable OpenClaw run. Pass a base eval agent plus `--agent-workspace`; the harness provisions `<base-agent>-<sample_id>` and `<base-workspace>-<sample_id>` automatically. Do not delete prior memory or session state to create freshness.
6. Disable and verify skill visibility for the base eval agent and the effective per-sample agents. `modelVisible` and `commandVisible` must be empty.
7. Verify eval-profile gateway, backend, model, memory, and auth settings before ingest.
   For `oo-builtin-vector`, verify both `memory.backend` and actual runtime `memory_search` tool results. `agents.defaults.memorySearch` alone is not sufficient: `memory.backend=qmd` means the run is QMD even if qwen3 embedding is configured.
8. Run ingest and QA into a new `output/runs/<run-group>/<backend-id>/` directory, with `--agent-workspace` configured. Enable canaries for multi-sample final runs unless intentionally recorded as skipped.
9. For long or restarted runs, pass `--resume` with the same run group. The harness may reuse complete ingest artifacts and per-item `qa.checkpoint.jsonl` / `judge.checkpoint.jsonl` records. Resume is allowed only when the same dataset/backend/profile/agent/workspace pattern is being continued.
10. Run the judge against `answers.json` and verify judge totals match answer totals.
11. Accept and report only artifact-backed values from `manifest.json`, summaries, `memory_write_verification.json`, `answers.json`, and `judge_grades.json`.

## Hard Rules

- Never imply a sampled run represents all LoCoMo10.
- Never run a full `locomo10.json` final row until a sample smoke run has passed for the same backend/profile/agent/workspace pattern.
- Never run a publishable OpenClaw final row without per-sample isolation via `--agent-workspace`.
- Never remove `write` or `edit` from the eval profile's durable-memory tool surface. `tools.allow` must be exactly `memory_search`, `memory_get`, `write`, and `edit`; builtin memory persists through file `write`/`edit`.
- Never accept an `oo-builtin-vector` row when `openclaw --profile eval config get memory.backend --json` returns `"qmd"` or session transcripts show `memory_search` results with `provider/model/backend=qmd`.
- Never pass `--user` for primary multi-sample runs.
- Never use `--allow-non-publishable` for final rows.
- Never report scores from `comparison_summary.json` or `comparison_report.html` unless regenerated after judging.
- Never resume into a different backend, profile, agent, workspace, dataset scope, category policy, or judge model unless the changed dimension is explicitly documented and the artifacts are treated as non-publishable until reverified.
- Never claim a condition is clean, enabled, disabled, absent, or verified without running the corresponding probe.
- Do not delete existing eval memory or session files to prepare a run.

## Verification Gate

Before saying a full eval result is valid, confirm:

- a prior sample smoke run passed for the same backend/profile/agent/workspace pattern
- `eval_repo_dirty=false`
- `tools.allow` is exactly `["edit", "memory_get", "memory_search", "write"]` after sorting
- `openclaw_agent` and `backend_config.agent` match the intended base agent for the backend
- for `oo-builtin-vector`, `backend_config.actual_memory_backend` is not `qmd`, and sampled session transcripts show `memory_search` is not `provider=qmd`, `model=qmd`, `mode=search`
- `memory_write_verification` is `configured`
- every selected sample has a per-sample verification entry with `write_detected=true`
- `dataset_qa_count_selected` matches the declared scope
- `judge_grades.json.total` matches `answers.json.summary.total`
- `judge_grades.json.grades | length` matches `answers.json.results | length`

If any gate fails, report the failure as a setup or artifact problem instead of producing a final comparison row.

## Reporting

Name the answer model and judge model next to every score. State scope, backend, token-cost inputs, memory-write evidence, and the exact artifact paths used for the claim.
