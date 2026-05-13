---
name: full-eval-run
description: Prepare, run, judge, and verify final OpenClaw LoCoMo benchmark runs without contaminating memory state or reporting untraceable metrics. Use when asked to run a full eval, final benchmark row, LoCoMo comparison table, builtin-memory eval, judge an eval run, verify eval artifacts, or turn docs/full-eval-run-principles.md into operational execution steps.
---

# Full Eval Run

## Overview

Run strict LoCoMo-style evals only when the scope, runtime isolation, skill isolation, auth, run artifacts, judging, and reporting gates are explicit and verifiable. Treat final benchmark rows as publishable claims: every metric must trace back to generated artifacts.

## Primary Reference

Read [references/full-eval-run-principles.md](references/full-eval-run-principles.md) before executing or accepting any full eval result. Use it as the source of truth for exact commands, required invariants, artifact checks, and reporting rules.

## Workflow

1. Declare the dataset scope before running anything. Distinguish smoke, sampled, and full `locomo10.json` runs.
2. Verify the repo is clean with `git status --short`; final rows require no output and `eval_repo_dirty=false`.
3. Use a fresh eval agent and workspace for each primary backend run. Do not delete prior memory or session state to create freshness.
4. Disable and verify skill visibility for the eval agent. `modelVisible` and `commandVisible` must be empty.
5. Verify eval-profile gateway, backend, model, memory, and auth settings before ingest.
6. Run ingest and QA into a new `output/runs/<run-group>/<backend-id>/` directory, with canaries enabled for multi-sample final runs unless intentionally recorded as skipped.
7. Run the judge against `answers.json` and verify judge totals match answer totals.
8. Accept and report only artifact-backed values from `manifest.json`, summaries, `memory_write_verification.json`, `answers.json`, and `judge_grades.json`.

## Hard Rules

- Never imply a sampled run represents all LoCoMo10.
- Never pass `--user` for primary multi-sample runs.
- Never use `--allow-non-publishable` for final rows.
- Never report scores from `comparison_summary.json` or `comparison_report.html` unless regenerated after judging.
- Never claim a condition is clean, enabled, disabled, absent, or verified without running the corresponding probe.
- Do not delete existing eval memory or session files to prepare a run.

## Verification Gate

Before saying a full eval result is valid, confirm:

- `eval_repo_dirty=false`
- `openclaw_agent` and `backend_config.agent` match the intended fresh agent
- `memory_write_verification` is `configured`
- at least one selected sample has `write_detected=true`
- `dataset_qa_count_selected` matches the declared scope
- `judge_grades.json.total` matches `answers.json.summary.total`
- `judge_grades.json.grades | length` matches `answers.json.results | length`

If any gate fails, report the failure as a setup or artifact problem instead of producing a final comparison row.

## Reporting

Name the answer model and judge model next to every score. State scope, backend, token-cost inputs, memory-write evidence, and the exact artifact paths used for the claim.
