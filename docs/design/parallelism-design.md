# Parallelism Design

## Overview

The eval harness parallelizes across three pipeline stages with independent concurrency controls.

## Controls

| Flag | Default | Stage | Scope |
|---|---|---|---|
| `--ingest-parallel` | 4 | Ingest | Samples ingested concurrently |
| `-p/--qa-parallel` | 5 | QA | Samples queried concurrently |
| `--judge-parallel` | 8 | Judge | LLM grading requests in flight |

## Safety Invariants

### Per-sample isolation is mandatory

Each sample gets its own OpenClaw agent + workspace + SQLite memory database. The harness always provisions per-sample agents when `--agent-workspace` is set, so parallel ingest is safe. Without `--agent-workspace` (smoke runs only), the harness falls back to the base agent and forces sequential ingest.

### QA parallelism is inter-sample only

Questions within one sample run **sequentially** because:
- All questions in a sample share one `(agent, user_key)` session
- The session is reset (archived) after each question to prevent Q(N)'s response from leaking into Q(N+1)'s context
- Concurrent questions to the same session would race on the reset and corrupt the transcript

Different samples have independent sessions and can safely run in parallel.

### Judge parallelism is unconstrained

Judge calls are stateless LLM API requests (question + expected + response → CORRECT/WRONG). No shared state, no ordering dependency.

## Gateway Constraint

The OpenClaw gateway enforces `maxConcurrent: 4` for agent requests. This means:
- Ingest: capped at 4 (matches gateway limit)
- QA: default 5 means at most 1 request queues inside the gateway
- Effective throughput ceiling is 4 concurrent LLM calls regardless of harness settings

## Architecture Diagram

```
main.py eval
│
├── Ingest (--ingest-parallel 4, requires --agent-workspace)
│   ├── sample-A ──[session_1 → session_2 → ... → session_N]──→ workspace-A/
│   ├── sample-B ──[session_1 → session_2 → ... → session_N]──→ workspace-B/
│   ├── sample-C ──[sequential within, parallel across]─────────→ workspace-C/
│   └── ...
│
├── QA (--qa-parallel 5)
│   ├── sample-A ──[Q1 → reset → Q2 → reset → ... → QN]───→ answers
│   ├── sample-B ──[Q1 → reset → Q2 → reset → ... → QN]───→ answers
│   └── ...  (inter-sample parallel, intra-sample sequential)
│
└── Judge (--judge-parallel 8)
    ├── grade(Q1) ─┐
    ├── grade(Q2) ─┤
    ├── grade(Q3) ─┼──→ judge_grades.json → comparison_report.html
    └── ...        ┘    (fully parallel, stateless)
```

## Why NOT Intra-sample QA Parallelism

Within one sample, all questions target the same `(agent, user_key)`:
1. The gateway maintains one session per `(agent, user)` pair
2. `_maybe_reset_session` archives the session `.jsonl` after each question
3. Concurrent questions would race on session file operations
4. The gateway may interleave responses into the shared session transcript

This would require a stateless query mode in the gateway (pure memory retrieval without session context), which does not exist today.
