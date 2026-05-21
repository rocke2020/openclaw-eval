# 2026-05-22 — OpenViking plugin bare: cat 1-4 score and token efficiency

## Why Cat 1-4

Mem0's April 2026 LoCoMo report uses the four standard recall categories:
single-hop, multi-hop, open-domain, and temporal memory recall, and reports
**91.6%** overall with **6,956 mean tokens/query**:
https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm

That excludes our category 5 adversarial/abstain questions, so this note slices
`oc-ov-plugin-bare` the same way.

## Artifact Scope

- Run: `output/runs/ov-plugin-bare-full-20260520-191844/oc-ov-plugin-bare/`
- Included categories: 1, 2, 3, 4.
- Excluded category: 5.
- QA count: 1540.
- Answer model: `deepseek/deepseek-v4-flash` through OpenClaw.
- Judge model: `deepseek-v4-flash`.
- Score source: `judge_grades.json`.
- Answer-token source: `ingest_summary.json` plus category-filtered `qa.jsonl`.
- Retrieval source: `~/.openviking/data/log/openviking.log.2026-05-20`, filtered
  for `search.find` telemetry from
  `eval-locomo-ov-bare-full-20260520-191844`.

Strict caveat: the parent run still has `eval_repo_dirty=true` and the OV write
verifier mismatch described in the full-run notes. Treat this as a directional
cat 1-4 analysis, not a clean final benchmark row.

## Score

| Category | Correct | Score |
|---|---:|---:|
| Overall cat 1-4 | **1313 / 1540** | **85.26%** |
| 1 | 237 / 282 | 84.04% |
| 2 | 248 / 321 | 77.26% |
| 3 | 64 / 96 | 66.67% |
| 4 | 764 / 841 | 90.84% |

Compared with Mem0's reported **91.6%** on its cat 1-4 LoCoMo setup, this OV
plugin run is **6.34 percentage points lower**. This is not an exact
apples-to-apples reproduction because the answer model, judge, dataset
implementation, and memory implementation differ.

## Cat 1-4 Token Efficiency

### Answer-Model Tokens

These are exact from the run artifacts. I use additive `input_tokens` and
`output_tokens`, not the artifact `total_tokens` field.

| Bucket | Input | Output |
|---|---:|---:|
| Ingest, all 272 sessions | 1,240,855 | 84,452 |
| QA, cat 1-4 only | 30,472,061 | 321,783 |
| **Answer total, cat 1-4** | **31,712,916** | **406,235** |

Per-query efficiency:

| Metric | Value |
|---|---:|
| QA-only input tokens/query | 19,787 |
| Ingest-amortized answer input tokens/query | **20,593** |
| Ingest-amortized answer output tokens/query | 264 |
| Answer input tokens/correct answer | 24,153 |

Against Mem0's reported **6,956 mean tokens/query**, this run's
ingest-amortized answer input is about **3.0x larger**. QA-only input is about
**2.8x larger**.

### QA Retrieval Calls

OpenViking `search.find` telemetry for the cat 1-4 phase:

| Retrieval metric | Value |
|---|---:|
| `find` calls | **5,186** |
| Retrieval calls/query | **3.37** |
| Retrieval embedding tokens | 597,582 |
| Embedding tokens/retrieval call | **115** |
| Vector sub-searches | 17,336 |
| Returned hits | 61,256 |
| Average retrieval latency | 181 ms |

Derived token ratios:

| Metric | Value |
|---|---:|
| QA-only answer input/retrieval call | 5,875 |
| Ingest-amortized answer input/retrieval call | **6,115** |
| Retrieval embedding tokens/retrieval call | **115** |

This is the important efficiency split: **the vector retrieval call itself is
cheap; the expensive part is the context assembled around it and sent to the
answer model.**

## OV Extraction Cost Caveat

The OV usage audit stores VLM and embedding usage at daily granularity, while
this run crossed midnight and category 5 was merged later on 2026-05-21. That
means the current artifacts do not support a clean exact split of OV extraction
tokens by category.

For this cat 1-4 note, the exact claims are therefore limited to:

- answer-model tokens from `ingest_summary.json` and category-filtered
  `qa.jsonl`;
- retrieval-call counts and retrieval embedding tokens from OV telemetry.

Any full system-level cat 1-4 token number that includes OV extraction would be
an estimate unless the harness writes per-category or per-phase OV usage
artifacts.

## Reading

On score, OV bare is competitive but behind Mem0's reported cat 1-4 LoCoMo
number: **85.26% vs 91.6%**.

On token efficiency, OV bare is clearly behind the Mem0 target. Even before
counting OV extraction/update overhead, it uses roughly **20.6K answer input
tokens/query**, about **3x** Mem0's **6,956 mean tokens/query** claim. The
retrieval primitive is not the bottleneck: **115 embedding tokens/retrieval** is
small. The bottleneck is how much recalled material and session context reaches
the answer turn.

The next useful experiment is a cat 1-4-only OV run with hard caps on assembled
memory context, plus first-class per-phase usage artifacts:

- answer prompt tokens/query;
- retrieval calls/query;
- retrieved-memory tokens/query;
- OV extraction/update tokens/session;
- OV extraction/update tokens/query if QA turns still trigger writes.

That would make the Mem0-style comparison much cleaner.
