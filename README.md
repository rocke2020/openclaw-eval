# openclaw-eval

Strict LoCoMo-style memory benchmark harness for OpenClaw and OpenViking.

The benchmark measures the full loop:

```text
memory write -> retrieval -> answer -> judge
```

It does not preload gold memories. Ingest sends conversations through the backend's normal memory-write path, QA asks normal questions later, and artifacts record the route, dataset hash, category policy, memory-write evidence, answers, and judge output.

## Target Output

The primary goal is a trustworthy experiment table comparing memory configurations by task completion rate and total input-token cost. Table shapes and row names below are examples only; final groups must match the actual pipeline runs.

```text
Experimental Group                         Task Completion Rate   Cost: Input Tokens (Total)
OpenClaw builtin memory-core               ...
OpenClaw QMD memory, memory-core disabled  ...
OpenViking memory plugin, memory-core disabled ...
OpenViking memory plugin, memory-core enabled  ...
OpenViking memory plugin, QMD memory enabled ...
```

Every number in the final table must trace back to reproducible run artifacts: `manifest.json`, `memory_write_verification.json`, `answers.json`, `judge_grades.json`, and token usage summaries. Do not report completion rates or costs that were not produced by the pipeline.

The table must also name the dataset scope. A sampled run is valid for pipeline validation, but final claims should say exactly what was run, such as `locomo10_small.json`, `locomo10.json --sample 0 --sessions 1-4`, or all of `locomo10.json`. Do not imply that a subset result represents the full LoCoMo10 file.

## Setup

```bash
uv sync
mkdir -p ~/.openclaw-eval
openclaw --profile eval config set gateway.port 19002 --strict-json
openclaw --profile eval gateway
```

The harness defaults to `http://127.0.0.1:19002`, `--openclaw-profile eval`, and `--agent eval-locomo`.

## Strict Run

```bash
uv run python eval.py ingest ./locomo10.json \
  --base-url http://127.0.0.1:19002 \
  --agent eval-locomo \
  --openclaw-profile eval \
  --run-dir output/runs/dev-smoke \
  --sample 0 \
  --sessions 1-4 \
  --agent-workspace ~/.openclaw-eval/workspace-locomo-eval

uv run python eval.py qa ./locomo10.json \
  --base-url http://127.0.0.1:19002 \
  --agent eval-locomo \
  --openclaw-profile eval \
  --run-dir output/runs/dev-smoke \
  --sample 0 \
  --include-categories 1,2,3,4,5

uv run python judge.py output/runs/dev-smoke/answers.json \
  --output output/runs/dev-smoke/judge_grades.json \
  --model gpt-4o-mini
```

Category `5` is included by default. Exclusions must be explicit with `--exclude-categories`, and the manifest records both `include_categories` and `exclude_categories`.

## Output Files

Each strict run writes:

```text
manifest.json
ingest.jsonl
ingest_summary.json
memory_write_verification.json
qa.jsonl
qa_summary.json
answers.json
judge_grades.json
report.html
```

`answers.json` is the stable judge input. `memory_write_verification.json` records whether `MEMORY.md` or `memory/*.md` changed under `--agent-workspace`.

## Backend Comparison

```bash
uv run python eval.py compare ./locomo10.json \
  --run-group output/runs/locomo-memory-comparison-001 \
  --backends oo-builtin,oo-qmd,openviking \
  --include-categories 1,2,3,4,5 \
  --allow-non-publishable
```

`oo-builtin` is always the baseline row. `oo-qmd` is an OpenClaw memory backend variant. `openviking` uses the OpenViking adapter and records answer mode `openviking-search-rag`.

For the primary comparison, QMD extra paths and transcript indexing should stay off unless the run is explicitly marked as an ablation.

## Publishability

A run is not publishable if `memory_write_verification.status` is `not_configured`, the eval agent is `main`, backend config cannot be verified, QMD extra paths or transcript indexing are enabled for a primary comparison, category exclusions are not declared, the manifest lacks dataset hash or eval commit, or QA artifacts are incomplete.

## LoCoMo10

`locomo10.json` contains 10 conversation samples, 272 sessions, 5,882 messages, 910 images, and 1,986 QA pairs.
