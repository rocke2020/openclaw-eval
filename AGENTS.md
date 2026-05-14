# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python 3.13 harness for strict LoCoMo-style memory benchmarks.

- `main.py` is the single CLI entry point with subcommands: `ingest`, `qa`, `eval`, `judge`, `isolation`.
- `lib/` contains all library modules:
  - `artifacts.py` — run directory helpers, manifest building, HTML report rendering.
  - `backends.py` — backend registry (OpenClaw, OpenViking) and comparison helpers.
  - `openclaw.py` — OpenClaw Responses API client and session management.
  - `openviking.py` — OpenViking CLI adapter.
  - `locomo.py` — LoCoMo dataset loading, formatting, and QA selection.
  - `memory_verify.py` — memory-write verification via file snapshot diffing.
  - `judge_util.py` — LLM grading logic and answer loading.
- `tests/` contains unit tests named `test_*.py`.
- `docs/` contains setup notes; `data/`, `locomo10*.json`, and `output/` hold fixtures, local benchmark data, and run artifacts.

## Build, Test, and Development Commands

- `uv sync` installs the locked Python environment from `pyproject.toml` and `uv.lock`.
- `PYTHONPATH=. uv run pytest` runs the full test suite.
- `PYTHONPATH=. uv run pytest tests/test_eval_locomo.py` runs one test file while iterating.
- `uv run python main.py --help` shows available benchmark CLI modes.
- `uv run python main.py ingest ./locomo10_small.json --run-dir output/runs/dev-smoke --sample 0 --sessions 1-1` runs a small ingest smoke test.

## Eval Environment & Artifacts

Record eval environment metadata next to any published score. The current fixed OpenClaw reference is `OpenClaw 2026.5.7 (eeef486)`, verified with `openclaw --version`.

Run manifests include `openclaw_version`, `eval_repo_commit`, `eval_repo_dirty`, `openclaw_base_url`, `openclaw_profile`, answer agent/model routing, judge model/base URL, dataset hash, and category policy. Do not report scores that cannot be traced to those artifacts.

## Coding Style & Naming Conventions

Use plain Python modules, standard-library types, and explicit helpers. Follow the existing style: 4-space indentation, useful type hints, `snake_case` functions and variables, and `PascalCase` test case classes. Keep changes surgical. Prefer structured JSON/path APIs over ad hoc string parsing.

## Testing Guidelines

Tests use `unittest` style and pytest discovery. Add tests under `tests/test_<module>.py`, with methods named `test_<behavior>`. Cover artifact contracts, category policy, backend selection, and memory verification when those paths change. Do not perform real writes, deletes, or destructive container/database operations in tests.

## Commit & Pull Request Guidelines

Recent history uses short imperative subjects, often `feat:`, `fix:`, and `docs:`. Keep each commit focused. Before opening a PR, run `PYTHONPATH=. uv run pytest`, describe benchmark or artifact impact, link related issues, and include screenshots only for rendered reports or docs pages.

## Security & Data Safety

Never delete database or vector-store data from code, tests, or scripts unless explicitly requested and the target is verified. Treat `data/vectordb/` and `output/runs/` as valuable local state. Keep API tokens and backend credentials out of commits.

For strict memory evaluation, the eval profile should expose no agent skills. Verify with `openclaw --profile eval skills check --agent eval-locomo --json`; `modelVisible` and `commandVisible` should be empty. The profile uses `agents.defaults.skills=[]`; restart the eval gateway after changing it.

Publishable OpenClaw eval rows must use per-sample isolation. Pass a base agent plus `--agent-workspace`; the harness provisions `<base-agent>-<sample_id>` and `<base-workspace>-<sample_id>`. A final row is invalid if `memory_write_verification` is not configured or any selected sample lacks `write_detected=true`.
