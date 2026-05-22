# 2026-05-22 — OpenViking plugin bare: score vs token efficiency

> ## ⚠️ ERRATA — 2026-05-22
>
> This entry's score-side claims are withdrawn. Cost-side telemetry is retained.
>
> Subsequent investigation (see errata in [2026-05-21-ov-plugin-bare-results.md](2026-05-21-ov-plugin-bare-results.md)) established that the underlying run failed per-sample isolation: extractions landed in shared `viking://user/default/memories/` and `canary.jsonl` records a **62% cross-sample leak rate (23/37)**. The 70.24% headline is invalid as a benchmark score.
>
> Specifically withdrawn from this entry:
>
> - "**The score is 1395 / 1986 = 70.24%, which is materially above the valid builtin-memory runs.**" — withdrawn. Not a per-sample-isolated row; cannot be compared to builtin runs that were.
> - "**OV improves recall quality**" (in the Headline and Bottom Line) — withdrawn. The score lift cannot be attributed to OV memory quality when cross-sample contamination affected the answer path at 62% leak rate.
> - "**+10.31 percentage points**" / "**+202 correct answers**" deltas vs builtin — withdrawn. Not comparable rows.
> - "Score-wise, OV bare is promising. It wins mainly on factual, temporal, and yes/no categories" — withdrawn. The win pattern may be an artifact of shared-scope retrieval pulling pre-aggregated entity files that span all 10 samples.
>
> Retained as still valid (cost telemetry does not depend on isolation correctness):
>
> - Token cost table (61.6M input-side, 65.8M total, excluding judge).
> - Token efficiency ratios (17,837 answer input/QA, 26,283 answer input/correct answer, **but** the "per correct answer" denominator inherits the invalidated score).
> - Retrieval-call telemetry (6,306 find attempts, 97 embedding tokens/attempt, 5,814 answer-agent input tokens/attempt, 9,765 system input tokens/attempt, 170 ms avg latency).
> - QA prompt distribution skew (median 913, p95 77,430, max 1,147,404).
> - The optimization-target bullets (reduce assembled context, cap retrieved-memory blocks, separate write/read cost, record per-call prompt size in artifacts) — these stand independent of score interpretation.
>
> The cost numbers describe what the OV plugin path consumed during the run window. They are useful as a "what does this plugin cost to operate" baseline for future engineering work. They are not evidence of quality.
>
> ## Headline

`oc-ov-plugin-bare` scored well, but it is not token-efficient enough to treat
as a real-usage win yet.

The score is **1395 / 1986 = 70.24%**, which is materially above the valid
builtin-memory runs. The cost side is much weaker: excluding judge tokens, this
run consumed about **61.6M input-side tokens** and **65.8M input+output tokens**
across the answer agent, OpenViking extraction, and OpenViking embedding work.
Against the efficient builtin-memory run 3, that is about **10.7x input-side
cost** for **+202 correct answers**.

In real usage, the current lesson is: **OV improves recall quality, but the
plugin path pays too much prompt and extraction overhead for the gain.**

## Artifact Scope

- Run: `output/runs/ov-plugin-bare-full-20260520-191844/oc-ov-plugin-bare/`
- Dataset: `locomo10.json`, categories 1-5, 10 samples, 1986 QA.
- Answer model: `deepseek/deepseek-v4-flash` through
  `openclaw/eval-locomo-ov-bare-full-20260520-191844`.
- Judge model: `deepseek-v4-flash`.
- Score source: `judge_grades.json`.
- Answer-token source: `ingest_summary.json` and `qa_summary.json`.
- OV token/retrieval source: `~/.openviking/data/usage_audit.sqlite3` plus
  `~/.openviking/data/log/openviking.log.2026-05-20` and
  `~/.openviking/data/log/openviking.log.2026-05-21`.

Strict artifact caveat: `manifest.json` records `eval_repo_dirty=true`, and
`memory_write_verification.json` has `invariant_held=false` with
`write_detected=false` for all 10 samples. Prior investigation indicates this
is a verifier mismatch for the OV plugin path, but by the strict final-row gate
this remains a directional artifact, not a clean publishable row.

## Score

| Category | Correct | Score |
|---|---:|---:|
| Overall | 1395 / 1986 | **70.24%** |
| 1 | 237 / 282 | 84.04% |
| 2 | 248 / 321 | 77.26% |
| 3 | 64 / 96 | 66.67% |
| 4 | 764 / 841 | 90.84% |
| 5 | 82 / 446 | 18.39% |

Compared with the three valid builtin-memory runs, whose mean is about
**59.94%**, OV bare is **+10.31 percentage points**. Compared with the
efficient builtin-memory run 3, OV bare is **+202 correct answers**.

## Token Cost

I use additive `input_tokens` and `output_tokens` fields. I do **not** use the
summary `total_tokens` field as the primary cost number because it is not
additive in these artifacts; this matches the convention used in the builtin
memory journal.

| Bucket | Input | Output | Notes |
|---|---:|---:|---|
| Answer ingest | 1,240,855 | 84,452 | 272 sessions |
| Answer QA | 35,423,507 | 388,339 | 1986 questions |
| **Answer total** | **36,664,362** | **472,791** | OpenClaw answer agent |
| OV VLM extraction | 24,050,055 | 3,718,804 | `usage_audit.sqlite3`, source `vlm` |
| OV embedding total | 861,617 | n/a | includes retrieval and indexing |
| **System, excluding judge** | **61,576,034** | **4,191,595** | input side plus outputs |

Judge tokens are not available in `judge_grades.json`; `usage` is `null`.

Efficiency ratios:

| Metric | Value |
|---|---:|
| Answer input per QA | 17,837 |
| Answer output per QA | 196 |
| Answer input per correct answer | 26,283 |
| System input per correct answer | 44,141 |
| System input+output per correct answer | 47,145 |
| System input vs efficient builtin run 3 | **10.7x** |
| Extra system input per extra correct answer vs builtin run 3 | **276K** |

The QA prompt distribution is highly skewed: median QA input is only **913**
tokens, but p95 is **77,430** and the max is **1,147,404**. The average is high
because a long tail of turns is extremely expensive.

## Retrieval Calls

OpenViking retrieval is measured from `search.find` telemetry for agents whose
ID matches `eval-locomo-ov-bare-full-20260520-191844`.

| Retrieval metric | Value |
|---|---:|
| `find` attempts | **6,306** |
| Successful `find` requests | 6,288 |
| Error `find` requests | 18 |
| Logged retrieval embedding tokens | 611,980 |
| Vector sub-searches | 21,068 |
| Scored vector hits | 119,942 |
| Returned hits | 74,545 |
| Average retrieval latency | 170 ms |

Most important derived numbers:

| Tokens per retrieval attempt | Value |
|---|---:|
| Retrieval embedding tokens only | **97** |
| Answer-agent input tokens | **5,814** |
| System input tokens, excluding judge | **9,765** |

So the retrieval operation itself is cheap. The real cost is the context that
retrieval causes to be assembled and fed into the answer model, plus OV's
DeepSeek-powered memory extraction/update pipeline.

## Interpretation

Score-wise, OV bare is promising. It wins mainly on factual, temporal, and
yes/no categories, which is exactly where structured extracted memory should
help. It still does not fix adversarial category 5.

Token-wise, this configuration is too expensive for ordinary usage. The
improvement over efficient builtin memory is roughly +10 points, but the
input-side cost is roughly 10.7x. If token efficiency is weighted higher than
raw score, the current OV plugin path is not yet the better default.

The optimization target is not the vector query. Search averages only 97
embedding tokens per retrieval attempt. The target is:

- reduce automatic context assembly size before the answer turn;
- cap or summarize retrieved memory blocks more aggressively;
- stop running expensive extraction/update work after QA-style read-only turns;
- separate ingest-time write cost from answer-time retrieval cost in future
artifacts;
- record retrieval-call counts and per-call prompt/context size directly in
run artifacts, not only in external OV logs.

## Bottom Line

Use `oc-ov-plugin-bare` as evidence that OpenViking can improve memory quality.
Do not use it yet as evidence that OpenViking is production-efficient. For real
usage, the next milestone should be **same or near-same score with a much lower
tokens-per-retrieval profile**, especially below the current **9.8K system input
tokens per retrieval attempt**.
