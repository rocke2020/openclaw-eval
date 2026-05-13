# 2026-05-13 — Why two "same-logic" mixed-memory runs scored 17 points apart

## TL;DR

Two single-base-agent runs on the full `locomo10.json` (10 samples, 1986 QA, categories 1-5, judge `deepseek-v4-flash`) produced very different scores:

| Run | Date | Artifacts | Score |
|---|---|---|---|
| A | 2026-05-12 | `output/runs/builtin-memory-full-20260512-225733/` | **55.99%** |
| B | 2026-05-13 | `output/runs/builtin-memory-full-20260513-111321/` | **73.31%** |

Same model (`deepseek/deepseek-v4-flash`). Same dataset. Same harness logic in spirit (single base agent, all 10 samples writing to one shared workspace). Neither is a valid per-sample-isolated LoCoMo row.

The score gap is not from model or harness wiring — it is from **how the agent wrote memory**. A's workspace shipped a pre-filled `IDENTITY.md` ("Echo, memory keeper, warm, observant"); the agent produced narrative chat recaps. B's workspace shipped the bootstrap-template `IDENTITY.md` with placeholders; the agent produced atomized fact bullets. Retrieval on bullets beats retrieval on prose.

## Per-category breakdown

| Cat | A | B | Δ |
|-----|---|---|---|
| 1 (single-hop)  | 56.4% | 85.8% | +29.4 |
| 2 (temporal)    | 48.3% | 85.4% | +37.1 |
| 3 (open-domain) | 52.1% | 72.9% | +20.8 |
| 4 (adversarial) | 80.1% | 95.0% | +14.9 |
| 5 (multi-hop)   | 16.6% | 15.9% | -0.7  |

Multi-hop (cat 5) is identically broken in both. The gap lives in factual recall (cats 1/2), where retrieval density matters.

## Side-by-side evidence

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
- Dogs: Max and Daisy ❤️
  - Shared photo: both dogs running in a field, one holding a ball
  - …
```

A example QA: *"When did Melanie run a charity race?"*
- A: "in **May 2023** — it came up in a conversation she had with Caroline on **May 25, 2023**" (conflates event date with conversation date)
- B: "on **Saturday, May 20, 2023** — she mentioned it… saying it was 'last Saturday'" (correctly separates the two)

## MEMORY.md long-term file

| | A | B |
|---|---|---|
| Size  | 338 KB | 31 KB |
| Lines | 1,533 | 461 |
| Style | Diary-style prose paragraphs, emotional inferences ("dream come true", "hard work paying off") | Dense fact bullets, role-disambiguated entities |
| Same-name handling | None | Explicit (`John (basketball — different from the community/politics John)`) |

A's MEMORY.md is 10× larger but its facts are buried inside narrative. B's is an index.

## Confounding variables that did NOT explain the gap

- Model: identical (`deepseek/deepseek-v4-flash`).
- OpenClaw runtime: identical (`2026.5.7 eeef486`, package.json dated 5月 9).
- Agent template (`AGENTS.md`): identical bytes (7835 each, `diff` empty).
- Eval profile invariants: `memorySearch.sources=["memory"]`, `startupContext.enabled=false`, `plugins.slots.memory="memory-core"` — all consistent.
- Skills exposed: 0 modelVisible, 0 commandVisible in both runs.

## Confounding variables that DID differ (but are not the dominant driver)

| | A | B |
|---|---|---|
| Harness commit | pre-`cf0ef97` | `cf0ef97` (retry, parallelism, reset_between_attempts) |
| Parallelism | serial 1 / 1 | ingest 4 / qa 5 |
| Wall time | ~7 hours | ~1 hour |
| Ingest output tokens | 746,865 (avg 2,745 / session) | 198,798 (avg 730 / session) |
| Silent ingest gaps | 1 "No response from OpenClaw" | 60 (22% of sessions) |
| Canary | enabled (30 records, ran after QA) | disabled |

These shift behavior but do not explain why B's surviving writes are categorically more structured.

## Dominant driver: agent persona seeded by IDENTITY.md

A `~/.openclaw-eval/workspace-locomo-builtin-full/IDENTITY.md` (pre-filled from an earlier run that ran bootstrap once):
```
- **Name:** Echo
- **Creature:** A curious digital assistant — part memory keeper, part helpful companion
- **Vibe:** Warm, observant, thoughtful — remembers the little things
- **Emoji:** 🧠
```

B `~/.openclaw-eval/workspace-locomo-builtin-full-20260513-111321/IDENTITY.md` (fresh template):
```
- **Name:**
  _(pick something you like)_
- **Creature:**
  _(AI? robot? familiar? ghost in the machine? something weirder?)_
- **Vibe:**
  _(how do you come across? sharp? warm? chaotic? calm?)_
- **Emoji:**
  _(your signature — pick one that feels right)_
```

A's agent loaded a warm-observant-memory-keeper persona and wrote memory in that voice: chronological recap, soft inferences, emotional color, meta-notes like `### Updated MEMORY.md / - Added November 7, 2022 entry`. B's agent had no persona to inhabit and fell back to utilitarian note-taking: bullets, timestamps, entity-first, bolded proper nouns.

Same model, different system context → different writing policy → different retrieval performance.

## Independent confirmation

Codex (consult mode, `deepseek-v4-flash`'s 200-IQ adversarial counterpart) and a Claude `general-purpose` subagent reviewed the same six same-date file pairs in parallel without seeing each other's output. Both:
- Picked B as the winner on retrieval quality.
- Cited the same line-level evidence (timestamps, bullet structure, entity disambiguation).
- Flagged A's process-noise meta-notes ("Updated MEMORY.md") and emotional inferences ("expert hiker now", "dream come true") as retrieval-hostile.

Codex caught one additional finding I missed: **B's `2023-06-16.md` records the wrong sample's conversation** (Jon/Gina rather than the John/Maria conversation A captured). That is a cross-sample memory contamination consistent with the per-sample-agent wiring bug fixed on 2026-05-13 (see `lib/backends.py`): all 10 samples wrote into one base workspace, so a 2023-06-16 session from one sample overwrote another sample's same-date file.

## What this means for the benchmark

Neither A nor B is a valid LoCoMo per-sample-isolated row. Both share the same flawed wiring (all samples → one base workspace). The score *gap* between them is a measurement of the **writing-policy axis**, not the memory-system axis.

For future runs:
- Lock IDENTITY.md state before measuring. Either always-empty (fresh template) or always-populated (single canonical persona). Don't let workspace seed state drift between runs.
- After the per-sample-agent fix lands, redo the full eval with isolated agents and an explicitly-chosen IDENTITY policy.
- Treat MEMORY.md size as a regression signal: if it crosses ~100 KB per sample, the agent is journaling instead of indexing.

## Pointers

- Harness fix: `lib/backends.py` `OpenClawBackend.ingest/answer` now honor `args.agent` override.
- Run principles: `docs/full-eval-run-principles.md`.
- A artifacts: `output/runs/builtin-memory-full-20260512-225733/oo-builtin/`.
- B artifacts: `output/runs/builtin-memory-full-20260513-111321/oo-builtin/`.
