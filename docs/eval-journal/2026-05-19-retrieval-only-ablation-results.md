# 2026-05-19 — Retrieval-only ablation: results

## Headline

Given the **same** OpenClaw-written durable memory snapshot, switching
retrieval from builtin-hybrid (vector + text, weights 0.8 / 0.2) to
builtin no-vector (FTS only) moves the LoCoMo10 score by **-12 / 1986
questions (-0.61 pp)**. Retrieval choice is a small contributor; the
shared written-memory snapshot is what dominates.

| Condition | Retrieval | Score | Run dir |
|---|---|---:|---|
| A | builtin hybrid (vector on) | 1183 / 1986 = 59.57% | `output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector/` |
| B | builtin no-vector (FTS only) | 1171 / 1986 = 58.96% | `output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/oo-builtin/` |

## Paired comparison (A = vector, B = no-vector)

| Pair bucket | Count |
|---|---:|
| Both correct | 1054 |
| Vector-only correct | 129 |
| No-vector-only correct | 117 |
| Both wrong | 686 |
| Net no-vector delta | **-12** |

The shared correctness core (1054) is 53% of all paired questions. The
two retrieval methods disagree on 246 questions (12.4%), with the
disagreement nearly canceling: 129 vs 117. The shared written-memory
snapshot constrains the answer set so tightly that retrieval method
becomes a small perturbation.

### Per-category

| Cat | Total | A correct | B correct | Both | A-only | B-only | Both wrong |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 — single-hop factual    | 282 | 189 | 189 | 164 | 25 | 25 | 68  |
| 2 — temporal              | 321 | 191 | 195 | 173 | 18 | 22 | 108 |
| 3 — multi-hop reasoning   | 96  | 63  | 66  | 56  | 7  | 10 | 23  |
| 4 — yes/no verification   | 841 | 672 | 654 | 616 | 56 | 38 | 131 |
| 5 — open-ended / advers.  | 446 | 68  | 67  | 45  | 23 | 22 | 356 |

Notable: vector is +18 on category 4 (yes/no verification). No-vector is
+4 on category 2 (temporal) and +3 on category 3 (multi-hop). Other
categories are within noise.

The dominant gap on category 5 (open-ended / adversarial: both-wrong =
356 / 446) is independent of retrieval — the model gets these wrong
regardless of how memory is fetched, consistent with that bucket testing
refusal of false-premise questions rather than recall.

## Gates that passed

1. `git status --short` clean (working tree at commit `3c7abf1`).
2. `openclaw --profile eval skills check --agent eval-locomo` —
   `modelVisible` and `commandVisible` both empty.
3. `tools.allow` = exactly `{memory_search, memory_get, write, edit}`;
   all forbidden tools denied; `tools.elevated.enabled=false`.
4. Source workspaces present for `conv-26, conv-30, conv-41, conv-42,
   conv-43, conv-44, conv-47, conv-48, conv-49, conv-50`.
5. Destination workspaces freshly provisioned (no pre-existing memory).
6. **203 / 203** memory files copied with sha256 source-vs-dest matches
   across all 10 samples (`clone-manifest.json`).
7. No ingest artifacts under condition B (QA-only by design).
8. Runtime evidence smoke: `debug.backend=builtin` on all calls;
   `effectiveMode` not surfaced by this OpenClaw build, so the gate
   relies on backend + score-distribution shape. With
   `memorySearch.store.vector.enabled=false` and
   `memorySearch.query.hybrid.enabled=false`, the builtin engine ran
   without vector store consultation.

   First-pass interpretation of smoke evidence was over-cautious: the
   `provider=ollama` / `model=qwen3-embedding:0.6b` strings stay in
   `details` because they are the *configured* embedding metadata,
   which OpenClaw echoes regardless of whether vector retrieval
   engages. Comparing with a known-good `oo-builtin` baseline at the
   same OpenClaw version confirmed the strings persist in true
   no-vector runs.

## After condition B

- `answers.json.summary.total == 1986` ✓
- `judge_grades.json.total == 1986` ✓
- `len(judge_grades.json.grades) == 1986` ✓
- Runtime transcripts show no QMD backend evidence (`debug.backend`
  is `"builtin"` on every memory_search call) ✓
- Pair keys `(sample_id, qi)` match condition A exactly (paired_total
  = 1986) ✓

## Profile override (applied + restored)

Pre-run snapshot:
`~/.openclaw-eval-profile-snapshots/eval-memorySearch-20260519-125509.json`.

Flips during the run:

| Path | Pre | During condition B | Post |
|---|---|---|---|
| `agents.defaults.memorySearch.store.vector.enabled` | true  | false | true  |
| `agents.defaults.memorySearch.query.hybrid.enabled` | true  | false | true  |
| `agents.defaults.memorySearch.provider`              | ollama | ollama (one mid-run detour to `builtin` proved that's an *embedding* provider, not a retrieval mode — reverted) | ollama |

Gateway restarted twice during the run and once for the restore. Post-
restore `memorySearch` config is bit-equal to the snapshot
(`diff` clean: `RESTORE OK`).

## Side effects intentionally left on disk

Per the global memory-safety rule (never delete OpenClaw memory or
agents without explicit instruction):

1. **Orphan agent (OpenClaw bug)**: the first clone attempt used a
   66-char base agent name. OpenClaw silently truncates agent IDs to
   64 chars, so `conv-26` provisioned successfully under the truncated
   id and `conv-30` collided with it. Left in place:
   - id: `eval-locomo-retrieval-ablation-builtin-from-vector-20260519-1255`
   - workspace:
     `~/.openclaw-eval/workspace-retrieval-ablation-builtin-from-vector-20260519-125509-conv-26`
   - Contents: OpenClaw template files only (no `MEMORY.md`, no
     `memory/*.md`).
2. **Dest agents and workspaces from the actual clone** — these
   carry the cloned memory and the full QA's session transcripts;
   reusable for re-runs of this ablation:
   - agents: `eval-locomo-ret-ablation-20260519-125509-conv-{26,30,41,42,43,44,47,48,49,50}`
   - workspaces: `~/.openclaw-eval/workspace-ret-ablation-20260519-125509-conv-*`
3. **Run artifacts**:
   - `output/runs/retrieval-ablation-builtin-from-vector-20260519-125509/`
     `clone-manifest.json`, `paired-comparison.json`,
     `paired-comparison.md`,
     `oo-builtin/{manifest,answers,qa.jsonl,judge_grades}.json` (+ logs).
   - `smoke/` and `smoke2/` carry the early runtime-evidence probes.

## Tokens (condition B run)

- QA in/out total: `6,609,531 / 1,114,649` (`total_tokens = 24,447,217`).
- Judge: `1986` rows graded with `deepseek-v4-flash` against
  `https://api.deepseek.com/v1`.

## Notes for follow-up

- OpenClaw does not (in 2026.5.7) emit a positive `mode=fts` /
  `mode=hybrid` field in `memory_search` details. A reliable runtime
  smoke gate would benefit from such a field.
- `memorySearch.provider` is strictly an **embedding** provider name.
  Setting it to `"builtin"` returns `Unknown memory embedding provider:
  builtin`. The way to disable vector for retrieval is via
  `store.vector.enabled` + `query.hybrid.enabled`.
- The 64-char agent-id truncation is a silent failure mode. The
  ablation harness now defaults to a base agent prefix
  `eval-locomo-ret-ablation` (40 chars) so `-conv-NN` suffixes fit
  inside the limit; longer prefixes will collide.

## Repro

```bash
# Snapshot + disable vector
openclaw --profile eval config get agents.defaults.memorySearch --json \
  > ~/.openclaw-eval-profile-snapshots/eval-memorySearch-$(date +%Y%m%d-%H%M%S).json
openclaw --profile eval config set agents.defaults.memorySearch.store.vector.enabled false
openclaw --profile eval config set agents.defaults.memorySearch.query.hybrid.enabled false
openclaw --profile eval gateway restart

# Clone condition A memory snapshot
TS=$(date +%Y%m%d-%H%M%S)
RUN_DIR=output/runs/retrieval-ablation-builtin-from-vector-$TS
mkdir -p $RUN_DIR/oo-builtin
PYTHONPATH=. uv run python scripts/retrieval_ablation.py clone \
  output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector \
  --timestamp $TS \
  --dest-base-agent "eval-locomo-ret-ablation-$TS" \
  --dest-base-workspace "$HOME/.openclaw-eval/workspace-ret-ablation-$TS" \
  --output "$RUN_DIR/clone-manifest.json"

# Full QA (about 2 hours at qa-parallel=10) + judge
export OPENCLAW_GATEWAY_TOKEN=$(python3 -c "import json,pathlib; print(json.loads(pathlib.Path('$HOME/.openclaw-eval/openclaw.json').read_text())['gateway']['auth']['token'])")
unset all_proxy http_proxy https_proxy   # httpx needs socksio[extra] for socks5
PYTHONPATH=. uv run python main.py qa locomo10.json \
  --agent "eval-locomo-ret-ablation-$TS" \
  --agent-workspace "$HOME/.openclaw-eval/workspace-ret-ablation-$TS" \
  --openclaw-home "$HOME/.openclaw-eval" \
  --run-dir "$RUN_DIR/oo-builtin" \
  --include-categories 1,2,3,4,5 \
  --qa-parallel 10
PYTHONPATH=. uv run python main.py judge \
  "$RUN_DIR/oo-builtin/answers.json" \
  --output "$RUN_DIR/oo-builtin/judge_grades.json" \
  --model deepseek-v4-flash \
  --base-url https://api.deepseek.com/v1 \
  --token "$DEEPSEEK_API_KEY" --parallel 16

# Paired comparison + restore
PYTHONPATH=. uv run python scripts/retrieval_ablation.py compare \
  output/runs/builtin-vector-full-20260518-223504/oo-builtin-vector/judge_grades.json \
  "$RUN_DIR/oo-builtin/judge_grades.json" \
  --label-a vector --label-b no-vector \
  --output "$RUN_DIR/paired-comparison.json" \
  --markdown "$RUN_DIR/paired-comparison.md"
openclaw --profile eval config set agents.defaults.memorySearch.store.vector.enabled true
openclaw --profile eval config set agents.defaults.memorySearch.query.hybrid.enabled true
openclaw --profile eval gateway restart
```
