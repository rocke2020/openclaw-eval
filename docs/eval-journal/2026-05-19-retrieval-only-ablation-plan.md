# 2026-05-19 — Retrieval-only ablation plan for builtin-vector

## Question

The valid `builtin-vector` full run landed very close to the repeated `builtin-memory` baseline:

- `builtin-vector`: `output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector/`, `1183/1986 = 59.57%`
- closest valid `builtin-memory` run: `output/runs/builtin-memory-variance-20260516-192805/oo-builtin/`, `1193/1986 = 60.07%`

The paired comparison against builtin Run 3 showed a large shared correctness core and near-canceling retrieval differences:

| Pair bucket | Count |
|---|---:|
| Both correct | 955 |
| Builtin-only correct | 238 |
| Vector-only correct | 228 |
| Both wrong | 565 |
| Net vector delta | -10 |

That comparison is useful, but it still mixes two sources of variance:

1. The ingest/write phase may produce different `MEMORY.md` and `memory/*.md` summaries across runs.
2. The QA phase uses different retrieval behavior.

To isolate retrieval, run a QA-only ablation from the exact `builtin-vector` written-memory snapshot.

## Experiment

Use the existing `builtin-vector` result as condition A, and create a new no-vector condition B from copied memory.

### Condition A: existing vector result

Use the already verified full run:

- Run dir: `output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector/`
- Base agent: `eval-locomo-builtin-vector-full-20260518-223504`
- Base workspace: `/Users/rocke_dong/.openclaw-eval/workspace-locomo-builtin-vector-full-20260518-223504`
- Per-sample workspaces: `/Users/rocke_dong/.openclaw-eval/workspace-locomo-builtin-vector-full-20260518-223504-conv-*`
- Score: `1183/1986 = 59.57%`

This run has runtime evidence that `memory_search` used:

- provider: `ollama`
- model: `qwen3-embedding:0.6b`
- backend: `builtin`
- vector store enabled
- hybrid enabled with `vectorWeight=0.8`, `textWeight=0.2`

### Condition B: copied memory, builtin no-vector retrieval

Create new per-sample workspaces copied from condition A's written-memory snapshot, then run QA only with vector retrieval disabled.

Proposed names:

- Run dir: `output/runs/retrieval-ablation-builtin-from-vector-<timestamp>/oo-builtin/`
- Base agent: `eval-locomo-retrieval-ablation-builtin-from-vector-<timestamp>`
- Base workspace: `/Users/rocke_dong/.openclaw-eval/workspace-retrieval-ablation-builtin-from-vector-<timestamp>`
- Per-sample agents: `<base-agent>-conv-*`
- Per-sample workspaces: `<base-workspace>-conv-*`

The copied workspace set must preserve:

- `MEMORY.md`
- `memory/*.md`
- normal workspace instruction files needed by OpenClaw (`AGENTS.md`, `SOUL.md`, `TOOLS.md`, `IDENTITY.md`, `USER.md`, `HEARTBEAT.md`)

It must not copy or mutate:

- original condition A workspaces in place
- original condition A session transcripts
- original condition A output artifacts

## Controls

This experiment controls the written memory by using condition A's exact memory files for condition B.

The remaining differences should be:

- retrieval mode: vector/hybrid vs builtin no-vector keyword retrieval
- answer model sampling during QA
- judge sampling if rejudged, though the same judge model should be used

No ingest should run for condition B. The run is QA-only plus judge.

## Required gates

Before running condition B:

1. `git status --short` must be clean.
2. OpenClaw eval profile must still hide skills:
   `openclaw --profile eval skills check --agent eval-locomo --json`
3. `tools.allow` must still be exactly:
   `memory_search`, `memory_get`, `write`, `edit`
4. Source workspaces must exist for all selected samples:
   `conv-26`, `conv-30`, `conv-41`, `conv-42`, `conv-43`, `conv-44`, `conv-47`, `conv-48`, `conv-49`, `conv-50`
5. Destination workspaces must not pre-exist with memory unless explicitly treated as a resume.
6. Hashes for `MEMORY.md` and `memory/*.md` must match source vs destination before QA starts.
7. No ingest artifacts should be generated for condition B.
8. A one-sample QA smoke must prove the no-vector config actually enters builtin keyword/FTS-only retrieval before the full QA run. Do not infer this from config alone.

After condition B:

1. `answers.json.summary.total == 1986`
2. `judge_grades.json.total == 1986`
3. `len(judge_grades.json.grades) == 1986`
4. Runtime transcripts must show no QMD backend evidence.
5. Runtime transcripts must show no vector provider/model evidence for the no-vector condition; expected no-vector search evidence should be builtin/FTS-only style. If the current OpenClaw profile still initializes `ollama`/`qwen3-embedding:0.6b`, the setup is not a no-vector ablation.
6. Pair keys `(sample_id, qi)` must match condition A exactly.

## Configuration risk

The current eval profile is configured for builtin-vector:

- `agents.defaults.memorySearch.provider=ollama`
- `agents.defaults.memorySearch.model=qwen3-embedding:0.6b`
- `agents.defaults.memorySearch.store.vector.enabled=true`

For condition B, the exact no-vector override must be verified before the full run. The success criterion is runtime evidence, not config shape:

- acceptable: `memory_search` results behave like builtin keyword/FTS-only retrieval, with no embedding provider/model evidence
- unacceptable: `memory_search` results still show `ollama`, `qwen3-embedding:0.6b`, vector scores, or QMD

If a clean per-agent override is not available, stop after the smoke and document the blocker instead of running the full QA ablation.

## Analysis

Run a paired comparison between condition A and condition B:

| Bucket | Meaning |
|---|---|
| both correct | Retrieval choice did not affect final correctness |
| vector-only correct | Vector/hybrid retrieved or framed enough evidence where no-vector did not |
| builtin-only correct | No-vector keyword retrieval avoided vector noise or found exact lexical evidence |
| both wrong | Not solved by retrieval choice; likely write loss, reasoning failure, or judge mismatch |

Also report category deltas:

- Category 1
- Category 2
- Category 3
- Category 4
- Category 5

The main claim should be narrow:

> Given the same OpenClaw-written durable memory snapshot, this ablation estimates the effect of retrieval method only: builtin-vector hybrid retrieval vs builtin no-vector keyword retrieval.

## Expected duration

The documentation and setup can be completed quickly. The full QA-only run may or may not finish within one hour. It avoids ingest, but it still asks all `1986` questions and then judges all answers.

## Non-goals

- Do not delete or reset any existing OpenClaw memory, SQLite store, session, or output artifact.
- Do not treat this as a new full publishable benchmark row; it is a retrieval ablation.
- Do not compare condition B against old builtin-memory runs as the primary result. The primary comparison is condition B against condition A, because they share the same written memory snapshot.
