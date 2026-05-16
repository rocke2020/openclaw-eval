# 2026-05-17 — Builtin memory variance across three valid runs

We now have three valid builtin-memory `locomo10.json` runs. All three used the full 10-sample / 1986-QA scope, categories 1-5, `deepseek/deepseek-v4-flash` as the answer model, and `deepseek-v4-flash` as the judge. All three passed the publishability gates: clean manifest, per-sample isolation, `memory_write_verification: configured`, `invariant_held: true`, and `write_detected: true` for every selected sample.

| Run | Date | Harness commit | Artifacts | Score | Notes |
|---|---|---|---|---:|---|
| 1 | 2026-05-13 | `11ea451` | `output/runs/builtin-memory-full-20260513-222431/oo-builtin/` | **1262/1986 = 63.54%** | Original trustworthy row after per-sample isolation was fixed. |
| 2 | 2026-05-16 | `c600be1` | `output/runs/builtin-memory-variance-20260516-102511/oo-builtin/` | **1116/1986 = 56.19%** | Fresh run after restoring strict builtin write tools. Judge had to be rerun with proxy env cleared. |
| 3 | 2026-05-16 | `d430cb6` | `output/runs/builtin-memory-variance-20260516-192805/oo-builtin/` | **1193/1986 = 60.07%** | Fresh agent/workspace. Integrated judge hit the same local SOCKS proxy issue; judge-only rerun succeeded. |

## Per-category scores

| Category | Run 1 | Run 2 | Run 3 |
|---|---:|---:|---:|
| 1 | 201/282 = 71.28% | 175/282 = 62.06% | 181/282 = 64.18% |
| 2 | 218/321 = 67.91% | 172/321 = 53.58% | 197/321 = 61.37% |
| 3 | 70/96 = 72.92% | 66/96 = 68.75% | 62/96 = 64.58% |
| 4 | 702/841 = 83.47% | 645/841 = 76.69% | 670/841 = 79.67% |
| 5 | 71/446 = 15.92% | 58/446 = 13.00% | 83/446 = 18.61% |

## Interpretation

The second run made a third run necessary. At `p = 0.6354` and `n = 1986`, the binomial-only standard error is about 1.08 percentage points, so a 95% half-width is about 2.12 points. Run 2 was 7.35 points below Run 1, far outside what we should hand-wave away as ordinary binomial noise.

Run 3 landed between the first two runs, at 60.07%. That confirms the eval path is working, but it weakens the old single-number baseline. The three-run center is about 59.94%, with a range of 7.35 points. Treating `63.54%` as "the builtin memory score" is too confident.

The right conclusion is narrower:

- builtin memory is still the correct baseline family for builtin-vector, because the write contract is durable markdown memory and the artifacts are valid;
- the baseline should be reported as repeated-run evidence, not a single publishable-looking point estimate;
- builtin-vector should be compared against the same repeated-run protocol, or at least against the full table above, not only against Run 1.

The judge failure in Runs 2 and 3 was environmental, not an eval failure: the OpenAI client picked up a local SOCKS proxy without `socksio` installed. In both cases, `answers.json` already contained 1986 answers, and rerunning judge-only with proxy environment variables cleared produced `judge_grades.json`.
