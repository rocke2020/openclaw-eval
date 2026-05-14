# 2026-05-13 — Three full evals, one trustworthy benchmark

## TL;DR

Three full `locomo10.json` runs (10 samples, 1986 QA, categories 1–5, judge `deepseek-v4-flash`) were produced over 36 hours. Only the last one (**C / 222431**) is a valid per-sample-isolated LoCoMo row. The earlier two are not publishable — they share the same shared-workspace flaw, and the score gap between them measures writing-policy, not memory-system quality.

| Run | Date | Harness commit | Per-sample isolation | Artifacts | Score | Publishable |
|---|---|---|---|---|---|---|
| A | 2026-05-12 | `fa02730` (pre-flag) | none — flag did not exist | `output/runs/builtin-memory-full-20260512-225733/` | **55.99%** | no |
| B | 2026-05-13 | `cf0ef97` (broken plumbing) | flag set, but backend ignored override | `output/runs/builtin-memory-full-20260513-111321/` | **73.31%** | no |
| C | 2026-05-13 | `11ea451` (plumbing fixed) | per-sample agent + workspace, session reset between QAs | `output/runs/builtin-memory-full-20260513-222431/` | **63.54%** | **yes** |

Same model (`deepseek/deepseek-v4-flash`). Same dataset. Same judge. The only run that survives the isolation gates is C.

## Per-category breakdown

| Cat | A (invalid) | B (invalid) | C (valid) |
|-----|---|---|---|
| 1 (single-hop)  | 56.4% | 85.8% | **71.3%** |
| 2 (temporal)    | 48.3% | 85.4% | **67.9%** |
| 3 (open-domain) | 52.1% | 72.9% | **72.9%** |
| 4 (adversarial) | 80.1% | 95.0% | **83.5%** |
| 5 (multi-hop)   | 16.6% | 15.9% | **15.9%** |

C is the honest number. The inflated B is what you get when the model can read raw conversation history at QA time; the depressed A is what you get when narrative-style memory writes hurt retrieval. C strips both confounds and reports what builtin memory actually delivers under proper isolation.

## Why A and B are invalid

Both A and B share one flaw: **all 10 samples wrote into a single base workspace.**

- **A** (pre-flag): there was no `--per-sample-agent` concept; the harness used one `agent: eval-locomo-builtin-full` and one `workspace-locomo-builtin-full/` for everything. Files like `2023-06-16.md` got overwritten by whichever sample touched them last.
- **B** (flag set, plumbing broken at `cf0ef97`): the CLI accepted `--per-sample-agent` and the harness *logged* per-sample agent names, but `OpenClawBackend.ingest/answer` did not yet forward the `agent` override to the wire (fixed in `d525884`). The base agent was used for every call, so writes again landed in the shared `workspace-locomo-builtin-full-20260513-111321/`. The 10 per-sample workspaces created by provisioning were empty after the run — `memory_write_verification.json` shows `write_detected: false` for every sample, which is the loud signal that B is invalid.

In both runs, the memory subsystem cannot have been tested in isolation: cross-sample overwrites are possible, the QA agent shares its session and workspace with all other samples, and `memory_write_verification` either rubber-stamped a shared write (A) or failed outright (B).

## Why A < B even though both are contaminated

Two separable mechanisms compound, both unrelated to the memory system being measured:

### 1. Writing policy (already in this journal — A vs B)

A's workspace shipped a pre-filled `IDENTITY.md` ("Echo, memory keeper, warm, observant"); the agent produced narrative chat recaps. B's workspace shipped the bootstrap template with placeholders; the agent produced atomized fact bullets. Retrieval on bullets beats retrieval on prose.

Same source conversation `2022-03-20`, after ingest:

A `~/.openclaw-eval/workspace-locomo-builtin-full/memory/2022-03-20.md`
```
# March 20, 2022
## Group Chat: James & John

James told John he created a game avatar and joined a new gaming platform —
really enjoys exploring and chatting with other gamers, feels part of a cool
online community. They talked about how gaming brings people together
regardless of background.

**John's new hobby:** Bought a metal detector and walks along beaches…
```

B `~/.openclaw-eval/workspace-locomo-builtin-full-20260513-111321/memory/2022-03-20.md`
```
# 2022-03-20
## Group Chat - John & James (9:26 pm)

**John (gaming):**
- Gaming helps him escape stress and calms him down
- Bought a metal detector; walks along beaches searching for treasures
- Found mostly bottle caps, but also coins and once a gold ring
- Wants a pet someday but not ready yet

**James:**
- Made a game avatar and joined a new gaming platform — loving the community
- …
```

| | A | B |
|---|---|---|
| MEMORY.md size  | 338 KB | 31 KB |
| MEMORY.md lines | 1,533 | 461 |
| Style | Diary-style prose paragraphs, emotional inferences ("dream come true") | Dense fact bullets, role-disambiguated entities |
| Same-name handling | None | Explicit (`John (basketball — different from the community/politics John)`) |

A's MEMORY.md is 10× larger but its facts are buried inside narrative. B's is an index.

### 2. Long-context advantage from missing session reset (B alone)

B sits another step ahead of A because of the same broken plumbing that left per-sample workspaces empty. `_call_answer` was supposed to call `backend.answer(..., agent=sample_agent)`, then `_maybe_reset_session(sample_args, user_key)` was supposed to archive the session after each QA. With the override unwired, the live OpenClaw session was keyed by `(base_agent, eval-conv-XX)` while `_maybe_reset_session` looked under `(sample_agent, eval-conv-XX)` — a no-op against a session that didn't exist. The real session therefore accumulated **every ingest turn plus every prior QA** within each user's thread.

Token evidence (QA first-call input tokens — the cold-cache load of the accumulated session):

| sample  | A first-QA in | B first-QA in | C first-QA in |
|---------|---|---|---|
| conv-26 | (n/a, sequential) | **47,746** | 21,938 |
| conv-43 | | **61,256** | 19,232 |
| conv-47 | | **95,061** | 23,665 |
| conv-49 | | **72,669** | 14,091 |

B's first QA for conv-47 cost 95K input tokens — that is the entire ingest thread sitting in working context. The model answered subsequent questions by scrolling back through the raw conversation log, bypassing memory retrieval entirely. C's first QA cost only ~14–24K (bootstrap + MEMORY.md + question) and stays bounded across the run.

A had the writing-policy disadvantage but not the long-context advantage (its session reset behavior in the pre-flag harness still terminated within-sample threads). That is why A < B even though both share the same workspace-level contamination.

## Why C is the only trustworthy row

C runs on `11ea451`, which lands two gates that are now both required:

1. **Per-sample agent wiring honored** (`d525884`, `OpenClawBackend.ingest/answer` forward the `agent` override). Each sample's writes land in its own `workspace-locomo-builtin-full-20260513-222431-conv-XX/`.
2. **Session reset between QAs actually fires** (the reset is now keyed by the same per-sample agent the backend used). The QA agent cannot smuggle accumulated session content from question to question.

Verification gates that C passes and A/B fail:

| Gate | A | B | C |
|---|---|---|---|
| `memory_write_verification.invariant_rule` | n/a | "all" | "all" |
| `memory_write_verification.invariant_held` | rubber-stamped (writes hit shared dir) | **false** (per-sample workspaces empty) | **true** |
| Per-sample workspace populated | no | no | yes (all 10) |
| Session reset between QAs | partial | broken (no-op) | working |
| Cross-sample file overwrite possible | yes | yes | no |

C's score (63.54%) is what builtin memory delivers when the harness genuinely forces every answer through the memory subsystem. Categories 1, 2, and 4 are bounded by the lossy summarization in MEMORY.md writes (specific dates, counts, and proper nouns drop out); category 5 is unchanged across all three runs, which suggests multi-hop is bottlenecked by something other than write policy or isolation.

## Independent confirmation (historical, A vs B only)

Codex (consult mode) and a Claude `general-purpose` subagent reviewed six same-date file pairs in parallel without seeing each other's output. Both picked B as the winner on retrieval quality, cited the same line-level evidence, and flagged A's process-noise meta-notes ("Updated MEMORY.md") and emotional inferences as retrieval-hostile.

Codex also caught: **B's `2023-06-16.md` records the wrong sample's conversation** (Jon/Gina rather than John/Maria) — cross-sample file overwrite, exactly the failure mode that the per-sample-agent fix exists to prevent. This is the artifact-level evidence that B's writes were not isolated, predating the token-level evidence above.

## What this means going forward

- **The benchmark row is C (63.54%).** Cite this number, not A and not B. A and B are kept on disk only as audit trail for this postmortem.
- **The harness now enforces per-sample isolation as the only mode** (commit `da1a507`): the `--per-sample-agent` flag has been removed, isolation activates whenever `--agent-workspace` is set, and `memory_write_verification` uses the strict `"all"` rule. A future regression cannot silently re-create the A or B failure modes — `invariant_held` will go false and the run will be marked non-publishable.
- **Productive next moves target the memory subsystem itself**, not the harness: categories 1/2/4 are where lossy summarization on the write side drops specific facts. Improving fidelity there is the path to raising 63.54%.

## Pointers

- Harness fixes: `lib/backends.py` (forward `agent` override, `d525884`); `main.py` (per-sample isolation is the only mode, `da1a507`).
- Run principles: `.codex/skills/full-eval-run/references/full-eval-run-principles.md`.
- A artifacts: `output/runs/builtin-memory-full-20260512-225733/oo-builtin/`.
- B artifacts: `output/runs/builtin-memory-full-20260513-111321/oo-builtin/` (`memory_write_verification.json` shows `write_detected: false` for every sample — the loud invalidation signal).
- C artifacts: `output/runs/builtin-memory-full-20260513-222431/oo-builtin/` (`memory_write_verification.invariant_held: true`, rule `"all"`, all 10 per-sample workspaces populated).
