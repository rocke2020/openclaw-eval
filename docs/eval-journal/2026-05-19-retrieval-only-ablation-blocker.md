# 2026-05-19 — Retrieval-only ablation: blocker after smoke

## Outcome

Stopped per the plan's explicit fallback (gate #8 in
`2026-05-19-retrieval-only-ablation-plan.md`). The condition B memory
snapshot was cloned successfully and a one-sample QA smoke ran, but the
runtime evidence shows the configured "no-vector" override did not
disengage vector retrieval. No full QA ablation ran.

## Run identifiers

- Source (condition A): `output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector/`
- Dest run group: `output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/`
- Dest base agent: `eval-locomo-ret-ablation-20260519-125509`
- Dest base workspace: `/Users/rocke_dong/.openclaw-eval/workspace-ret-ablation-20260519-125509`
- Clone manifest: `output/runs/.../clone-manifest.json` (203 files cloned, all sha256 matched)
- OpenClaw: `OpenClaw 2026.5.7 (eeef486)`
- Repo commit at run start: `33ac31a` (clean working tree)

## Gates that passed

1. `git status --short` clean (after committing the QA fix `33ac31a`).
2. `openclaw --profile eval skills check --agent eval-locomo` — both
   `modelVisible` and `commandVisible` empty.
3. `tools.allow` exactly `{memory_search, memory_get, write, edit}`,
   `tools.elevated.enabled=false`, forbidden tools all denied.
4. Source workspaces present for `conv-26, conv-30, conv-41, conv-42,
   conv-43, conv-44, conv-47, conv-48, conv-49, conv-50` under
   `~/.openclaw-eval/workspace-locomo-builtin-vector-full-20260518-223504-*`.
5. Destination workspaces did not pre-exist with memory.
6. `MEMORY.md` and `memory/*.md` sha256 hashes matched source vs
   destination after clone (203 files, 10 samples).
7. No ingest artifacts written for condition B (clone is QA-only by
   design).

## Profile override applied

Pre-run snapshot saved to
`~/.openclaw-eval-profile-snapshots/eval-memorySearch-20260519-125509.json`.

Flips applied via `openclaw --profile eval config set` then
`openclaw --profile eval gateway restart`:

- `agents.defaults.memorySearch.store.vector.enabled`: `true → false`
- `agents.defaults.memorySearch.query.hybrid.enabled`: `true → false`

`provider=ollama` and `model=qwen3-embedding:0.6b` were left in place —
those are the embedding configuration and have no obvious "off" knob in
the current schema.

## Smoke run

One-sample, three-question QA against the dest base agent:

```
uv run python main.py qa locomo10.json \
  --agent eval-locomo-ret-ablation-20260519-125509 \
  --agent-workspace ~/.openclaw-eval/workspace-ret-ablation-20260519-125509 \
  --openclaw-home ~/.openclaw-eval \
  --run-dir output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/smoke \
  --sample 0 --count 3 --include-categories 1,2,3,4,5 --qa-parallel 1
```

All three answers came back; three `memory_search` tool calls landed in
`conv-26`'s session transcripts.

## Runtime evidence (the blocker)

Per-call details from
`~/.openclaw-eval/agents/eval-locomo-ret-ablation-20260519-125509-conv-26/sessions/*.jsonl.*`:

| call | provider | model | debug.backend | hits | searchMs | result `score` examples |
|---|---|---|---|---|---|---|
| 1 | ollama | qwen3-embedding:0.6b | builtin | 3 | 3744 | 0.557, 0.512, 0.506 |
| 2 | ollama | qwen3-embedding:0.6b | builtin | 3 | 299  | 0.664, 0.655, 0.617 |
| 3 | ollama | qwen3-embedding:0.6b | builtin | 3 | 298  | 0.581, 0.551, 0.550 |

Two independent signals say vector retrieval is still engaged:

- **Result `score` values are cosine-similarity-shaped** (0.50–0.66
  range), not keyword/FTS-shaped (BM25 integer ranks or 0..1 with much
  wider distribution).
- **Latency pattern is embedding-cold-then-cached** (3744ms first call,
  then ~298ms). Pure builtin keyword/FTS search would run uniformly fast
  (~10–50ms).

`debug.effectiveMode` is reported as `"n/a"` on every call — the
runtime does not surface a vector-vs-keyword mode field that the smoke
detector can rely on, only `provider` / `model` / `debug.backend` /
`results[].score`.

## Why the plan's smoke gate fired

The plan listed acceptable evidence as "builtin keyword/FTS-only" and
unacceptable evidence as "`memory_search` results still show `ollama`,
`qwen3-embedding:0.6b`, vector scores, or QMD." Both unacceptable
markers are present after the override.

Adding `store.vector.enabled=false` and `query.hybrid.enabled=false`
appears to be insufficient to disengage vector retrieval — at least
without also unsetting `provider`/`model` or otherwise switching to a
different `memorySearch` engine. Any deeper override touches more of
the profile and is exactly the "no clean per-agent override available"
case the plan tells us to stop on.

## Restored state

- `agents.defaults.memorySearch.store.vector.enabled` → `true`
- `agents.defaults.memorySearch.query.hybrid.enabled` → `true`
- Gateway restarted; health 200; full memorySearch JSON now bit-equal
  to the pre-run snapshot.

## Side effects left on disk

These were created during the run and are intentionally not deleted
(global memory-safety rule: never delete OpenClaw memory or agents
without explicit instruction):

1. **Orphan agent (OpenClaw silently truncated a 66-char agent ID to
   64 chars):**
   - id: `eval-locomo-retrieval-ablation-builtin-from-vector-20260519-1255`
   - workspace:
     `~/.openclaw-eval/workspace-retrieval-ablation-builtin-from-vector-20260519-125509-conv-26`
   - Has only OpenClaw template files; no MEMORY.md, no memory/*.md.
   - Resulted from the first clone attempt's first sample succeeding
     before the second sample collided. Re-run used a shorter prefix.
2. **Dest agents and workspaces from the actual clone** (10 samples):
   `eval-locomo-ret-ablation-20260519-125509-conv-{26,30,41,42,43,44,47,48,49,50}`
   under `~/.openclaw-eval/agents/` and
   `~/.openclaw-eval/workspace-ret-ablation-20260519-125509-conv-*`.
   These carry condition A's cloned MEMORY.md + memory/*.md and are the
   only artifacts that would be reused if a follow-up attempt finds a
   working no-vector override.
3. **Smoke artifacts** under
   `output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/smoke/`
   (3-question answers + manifest + checkpoint). These show three
   successful `[ERROR] 401` calls and then three successful answers
   after `OPENCLAW_GATEWAY_TOKEN` was sourced from
   `~/.openclaw-eval/openclaw.json` (`gateway.auth.token`).
4. **Profile snapshot:**
   `~/.openclaw-eval-profile-snapshots/eval-memorySearch-20260519-125509.json`.

## What would unblock a real retrieval-only ablation

1. Identify whether OpenClaw has a per-agent or per-profile override
   that fully bypasses the vector path at retrieval time without
   altering the embedding provider — e.g., a `memorySearch.mode=text`
   knob or a backend selection that does not consult ollama at all.
   The runtime would need to surface this as an unambiguous evidence
   field (something like `debug.effectiveMode: "text"` or a
   `mode: "fts"` in details) so the smoke gate can read a positive,
   not just an absence of negative signals.
2. With that knob in hand, re-run the same workflow:
   `scripts/retrieval_ablation.py clone …` (the existing dest agents
   and workspaces can be reused; the cloned memory is intact),
   one-sample smoke, runtime evidence check, full QA + judge, paired
   comparison via `scripts/retrieval_ablation.py compare`.

Until then, the harness is ready but the experiment cannot
distinguish retrieval-method effects from embedding noise.

## Files added by this run

- `lib/ablation.py`, `scripts/retrieval_ablation.py`,
  `tests/test_ablation.py` (committed in `7269f66`,
  `33ac31a`).
- `output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/`
  (clone manifest + smoke artifacts).
- `docs/eval-journal/2026-05-19-retrieval-only-ablation-blocker.md` (this
  file).
