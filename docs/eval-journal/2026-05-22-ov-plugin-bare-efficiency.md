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
> - "**+10.31 percentage points**" / "**+202 correct answers**" deltas vs builtin — withdrawn. Not comparable rows.
>
> Restored as directional (2026-08-05) — per-category *patterns* observed on this run, not isolation-valid absolute scores:
>
> - "OV improves recall quality on direct-recall categories" and the per-category win pattern (cat 1 84.04%, cat 2 77.26%, cat 4 90.84% strong; cat 3 66.67% middling; cat 5 18.39% broken) — restored as a directional observation of what this run produced. The absolute per-category numbers remain non-isolation-valid (62% cross-sample leak); the pattern is cited as run-output, not as a clean benchmark comparison. The original concern that the pattern may be an artifact of shared-scope retrieval pulling pre-aggregated entity files is noted but not disqualifying for directional use.
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

`oc-ov-plugin-bare` produced a per-category profile that is strong on the
direct-recall categories and broken on the adversarial category, but the run is
not token-efficient enough to treat as a real-usage win, and its absolute
scores are not isolation-valid (see errata above).

Directionally: **categories 1, 2, and 4 are where the OV plugin path wins**
(84.04% / 77.26% / 90.84%), **category 3 is middling** (66.67%), and **category
5 stays broken** (18.39%). Full per-category table and reading in
[Score & Interpretation](#score--interpretation) below.

The cost side is much weaker: excluding judge tokens, this run consumed about
**61.6M input-side tokens** and **65.8M input+output tokens** across the
answer agent, OpenViking extraction, and OpenViking embedding work.

In real usage, the current lesson is: **OV improves recall quality on
direct-lookup and temporal categories, but the plugin path pays too much
prompt and extraction overhead for the gain.**

## Score & Interpretation

Category key (LoCoMo taxonomy, verified against `locomo10.json` questions):

- **Cat 1** — single-hop factual (e.g. "What did Caroline research?")
- **Cat 2** — multi-hop (e.g. "When did Caroline go to the LGBTQ support group?")
- **Cat 3** — open-ended (e.g. "What fields would Caroline be likely to pursue?")
- **Cat 4** — temporal / state-change (e.g. "What did Melanie realize after the charity race?")
- **Cat 5** — adversarial / abstain (fabricated premises the agent should refuse)

Per-category scores from this run (`judge_grades.json`):

| Cat | Meaning | Correct | Score |
|---|---|---:|---:|
| Overall | — | 1395 / 1986 | 70.24% |
| 1 | single-hop factual | 237 / 282 | 84.04% |
| 2 | multi-hop | 248 / 321 | 77.26% |
| 3 | open-ended | 64 / 96 | 66.67% |
| 4 | temporal / state-change | 764 / 841 | 90.84% |
| 5 | adversarial / abstain | 82 / 446 | 18.39% |

Directional reading:

- **Cat 1 (single-hop factual) 84.04%** and **cat 4 (temporal) 90.84%** are the
  strongest categories — direct-lookup and "who/what/when" questions that OV's
  pre-linked extracted records serve well.
- **Cat 2 (multi-hop) 77.26%** is also strong; assembled memory returns denser
  records than builtin's verbatim-conversation scan.
- **Cat 3 (open-ended) 66.67%** is the middling category — open-ended prompts
  reward verbatim conversation text, and OV's paraphrased extracted memory loses
  signal there.
- **Cat 5 (adversarial/abstain) 18.39%** stays broken; the bottleneck is the
  answer model's willingness to abstain, not the memory backend.

These per-category *patterns* are observations from this run. The absolute
per-category scores (and the Overall 70.24%) are not isolation-valid (62%
cross-sample leak, see errata) and must not be cited as clean benchmark
numbers; the +10.31pp / +202-correct deltas vs builtin rows are withdrawn as
non-comparable.

Token-wise, this configuration is too expensive for ordinary usage. The
input-side cost is roughly 10.7x the efficient builtin-memory run 3 (see
[Token Cost](#token-cost)). If token efficiency is weighted higher than raw
score, the current OV plugin path is not yet the better default.

The optimization target is not the vector query. Search averages only 97
embedding tokens per retrieval attempt. The target is:

- reduce automatic context assembly size before the answer turn;
- cap or summarize retrieved memory blocks more aggressively;
- stop running expensive extraction/update work after QA-style read-only turns;
- separate ingest-time write cost from answer-time retrieval cost in future
artifacts;
- record retrieval-call counts and per-call prompt/context size directly in
run artifacts, not only in external OV logs.

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

## Bottom Line

Use `oc-ov-plugin-bare` as directional evidence that OpenViking improves memory
quality on direct-recall categories — **cat 1 84.04%, cat 2 77.26%, cat 4
90.84%** — while **cat 3 66.67%** is middling and **cat 5 18.39%** stays
broken. Do not cite the absolute per-category scores as isolation-valid (see
errata). Do not use it yet as evidence that OpenViking is production-efficient.
For real usage, the next milestone should be **same or near-same per-category
profile with a much lower tokens-per-retrieval profile**, especially below the
current **9.8K system input tokens per retrieval attempt**.
