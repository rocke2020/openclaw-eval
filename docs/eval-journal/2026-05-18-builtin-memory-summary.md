# 2026-05-18 — Builtin memory summary across three valid runs

We now have three valid builtin-memory `locomo10.json` runs. All three used the full 10-sample / 1986-QA scope, categories 1-5, `deepseek/deepseek-v4-flash` as the answer model, and `deepseek-v4-flash` as the judge. All three passed the publishability gates: clean manifest, per-sample isolation, `memory_write_verification: configured`, `invariant_held: true`, and `write_detected: true` for every selected sample.

| Run | Date | Harness commit | Artifacts | Score | Notes |
|---|---|---|---|---:|---|
| 1 | 2026-05-13 | `11ea451` | `output/runs/builtin-memory-full-20260513-222431/oc-builtin/` | **1262/1986 = 63.54%** | Original trustworthy row after per-sample isolation was fixed. |
| 2 | 2026-05-16 | `c600be1` | `output/runs/builtin-memory-variance-20260516-102511/oc-builtin/` | **1116/1986 = 56.19%** | Fresh run after restoring strict builtin write tools. Judge had to be rerun with proxy env cleared. |
| 3 | 2026-05-16 | `d430cb6` | `output/runs/builtin-memory-variance-20260516-192805/oc-builtin/` | **1193/1986 = 60.07%** | Fresh agent/workspace. Integrated judge hit the same local SOCKS proxy issue; judge-only rerun succeeded. |

## Per-category scores

| Category | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| 1 | 201/282 = 71.28% | 175/282 = 62.06% | 181/282 = 64.18% |
| 2 | 218/321 = 67.91% | 172/321 = 53.58% | 197/321 = 61.37% |
| 3 | 70/96 = 72.92% | 66/96 = 68.75% | 62/96 = 64.58% |
| 4 | 702/841 = 83.47% | 645/841 = 76.69% | 670/841 = 79.67% |
| 5 | 71/446 = 15.92% | 58/446 = 13.00% | 83/446 = 18.61% |

## Token usage

Per-run answer-model token totals, summed from `usage` records in `ingest.jsonl` (272 sessions) and `qa.jsonl` (1986 questions). These are the tokens reported by the answer model at the final turn of each ingest/QA call; the per-record `total_tokens` is larger because OpenClaw aggregates additional internal tool-call turns, which are not split out here. Judge tokens are not separately tracked in the artifacts.

| Run | Ingest input | Ingest output | QA input | QA output | Combined input | Combined output |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 4,789,772 | 449,570 | 12,104,097 | 1,749,922 | **16,893,869** | **2,199,492** |
| 2 | 1,459,267 | 283,317 | 3,968,610 | 1,010,753 | **5,427,877** | **1,294,070** |
| 3 | 1,572,187 | 333,651 | 4,194,673 | 1,060,112 | **5,766,860** | **1,393,763** |

Run 1's input volume is roughly 3× Run 2 and Run 3. The gap is uniform across ingest and QA, holds in the median (not driven by outliers), and is already present on every sample's `session_1` (e.g., `conv-26` session_1 ingest: Run 1 = 18,306 input tokens, Run 3 = 5,992) — so it is not memory accumulating across sessions or "more search per question". It is a fixed per-turn overhead, traced in the next section. It is most likely score-neutral overhead — Run 1's higher score is best read as run-to-run variance, not as a token-spend dividend.

## Root cause of the Run 1 token gap

The only behavior change in `lib/` between Run 1's commit (`11ea451`) and Run 2's (`c600be1`) is `_remove_bootstrap_template()` in `lib/agent_provision.py:127-133`, which deletes `BOOTSTRAP.md` from each per-sample workspace before ingest. `BOOTSTRAP.md` is OpenClaw's "first-run, wake up and figure out who you are" template; when present it tells the agent to read `IDENTITY.md`, `USER.md`, `SOUL.md`, and `AGENTS.md` (≈13.5 KB of template content combined in `~/.openclaw/workspace-eval/`) on first activation. Those tool-read results enter the OpenClaw session's stored context, so they get re-fed as input on every subsequent ingest and QA turn within that sample's session, which is exactly the pattern we see: a flat ~12K-token overhead per turn that does not depend on session index.

Other candidate causes were ruled out:

- The `tools.allow` change at `c600be1` (added `write`, `edit`) would, if anything, add tokens via larger tool schemas — it cannot explain a *drop* of ~12K tokens per turn between Run 1 and Run 2.
- Memory accumulating across sessions within a sample was ruled out by the session_1 evidence above (Run 1's session_1 has no prior memory and is still 3× larger than Run 3's session_1).
- `openclaw_version` is identical (`OpenClaw 2026.5.7 (eeef486)`) on all three manifests, so OpenClaw-side prompt-construction differences are not in play.
- The harness's user-message construction (`lib/locomo.py:66-71`, `lib/openclaw.py:121-142`) is unchanged across the three commits; the harness sends the same dataset text + tail and records OpenClaw's returned `usage` verbatim.

A separate codex consult on the same artifacts reached the same conclusion independently.

The BOOTSTRAP-read residue is generic agent-persona template content (`IDENTITY.md`, `USER.md`, `SOUL.md`, `AGENTS.md`) — none of it is LoCoMo-relevant context. The most defensible reading is that it is mostly inert overhead from the answer model's perspective: it inflates per-turn input by ~12K tokens but does not meaningfully change what the model knows about the LoCoMo conversations it is being asked about. Under that reading, Run 1 is still essentially apples-to-apples with Runs 2/3 — just paid for at roughly 3× the token cost — and the score gap between Run 1 and Runs 2/3 should be read as ordinary run-to-run variance (model sampling nondeterminism, per-question ordering effects), not as a token-spend dividend or a different eval setup.

The only operational implication is cost, not score: future builtin-memory runs should be on commits at or after `c600be1` so that per-turn input is not paying for template-read residue.

## Interpretation

The second run made a third run necessary. At `p = 0.6354` and `n = 1986`, the binomial-only standard error is about 1.08 percentage points, so a 95% half-width is about 2.12 points. Run 2 was 7.35 points below Run 1, far outside what we should hand-wave away as ordinary binomial noise.

Run 3 landed between the first two runs, at 60.07%. That confirms the eval path is working, but it weakens the old single-number baseline. The three-run center is about 59.94%, with a range of 7.35 points. Treating `63.54%` as "the builtin memory score" is too confident: the binomial-only SE clearly understates real run-to-run variance once model sampling nondeterminism and per-question ordering effects are in play, and the 7.35-point spread across three otherwise comparable runs is the honest evidence of that.

The right conclusion is narrower:

- builtin memory is still the correct baseline family for builtin-vector, because the write contract is durable markdown memory and the artifacts are valid;
- the baseline should be reported as repeated-run evidence, not a single publishable-looking point estimate;
- builtin-vector should be compared against the same repeated-run protocol, or at least against the full table above, not only against Run 1.

The judge failure in Runs 2 and 3 was environmental, not an eval failure: the OpenAI client picked up a local SOCKS proxy without `socksio` installed. In both cases, `answers.json` already contained 1986 answers, and rerunning judge-only with proxy environment variables cleared produced `judge_grades.json`.
