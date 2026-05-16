# Reproducible LoCoMo Memory Eval

Use a separate OpenClaw profile and gateway for publishable numbers:

```bash
uv sync
mkdir -p ~/.openclaw-eval
openclaw --profile eval config set gateway.port 19002 --strict-json
openclaw --profile eval gateway
```

Run ingest and QA against that gateway:

```bash
uv run eval.py ingest ./locomo10.json \
  --base-url http://127.0.0.1:19002 \
  --agent eval-locomo \
  --openclaw-profile eval \
  --run-dir output/runs/locomo-eval-001 \
  --agent-workspace ~/.openclaw-eval/workspace-locomo-eval \
  --tail "[remember what's said, keep existing memory]"

uv run eval.py qa ./locomo10.json \
  --base-url http://127.0.0.1:19002 \
  --agent eval-locomo \
  --openclaw-profile eval \
  --run-dir output/runs/locomo-eval-001 \
  --include-categories 1,2,3,4,5

uv run python judge.py output/runs/locomo-eval-001/answers.json \
  --output output/runs/locomo-eval-001/judge_grades.json \
  --model gpt-4o-mini
```

Strict mode includes categories `1,2,3,4,5` by default. Any exclusion must be passed with `--exclude-categories` and will be recorded in `manifest.json`.

Comparison run:

```bash
uv run eval.py compare ./locomo10.json \
  --run-group output/runs/locomo-memory-comparison-001 \
  --backends oo-builtin,oo-qmd,openviking \
  --include-categories 1,2,3,4,5 \
  --allow-non-publishable
```

`oo-builtin` is the baseline. `oo-qmd` is the OpenClaw QMD variant. `openviking` is a separate adapter that writes memory with `ov add-memory`, retrieves with `ov search`, and records the answer mode as `openviking-search-rag`.

For primary comparison runs, QMD extra paths and session transcript indexing should be disabled unless the run is intentionally labeled as an ablation.

Required artifacts:

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

A run is non-publishable when memory_write_verification is not configured, the agent is `main`, backend config cannot be verified, category policy is missing, the manifest lacks dataset hash or eval commit, or QA artifacts are incomplete.
