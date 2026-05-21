# 2026-05-21 — OpenViking plugin (bare): first full-eval results vs local builtin

## Headline

The new `oc-ov-plugin-bare` row landed at **1395 / 1986 = 70.24%** on
LoCoMo10 with the same answer model (`deepseek-v4-flash`) and the same
1986-QA five-category dataset as the existing local builtin baselines.
That is **+7 to +14 points overall** vs every prior `oc-builtin` /
`oc-builtin-vector` run we have. The OV plugin in OpenClaw's
`contextEngine` slot wins by wide margins on single-hop, multi-hop, and
temporal questions, and loses by 6 points on open-ended (cat 3) against
the strongest builtin run.

This is the first row we have for the OV-plugin path under our usual
answer/judge stack. It is not an exact reproduction of the published
volcengine/OpenViking comparison (see "Comparison class" below).

## TL;DR table

Same dataset (1986 QA, cats 1-5), same answer model
(`deepseek-v4-flash`), same judge (`deepseek-v4-flash` via
`https://api.deepseek.com/v1`), same per-sample agent isolation
(`<base>-<sample_id>` + per-sample workspace).

| Row | Overall | cat 1 | cat 2 | cat 3 | cat 4 | cat 5 |
|---|---|---|---|---|---|---|
| **oc-ov-plugin-bare** (this run) | **70.24%** (1395/1986) | **84.04%** | **77.26%** | 66.67% | **90.84%** | 18.39% |
| oc-builtin full (2026-05-13) | 63.54% (1262/1986) | 71.28% | 67.91% | **72.92%** | 83.47% | 15.92% |
| oc-builtin variance run 1 (2026-05-16) | 56.19% | 62.06% | 53.58% | 68.75% | 76.69% | 13.00% |
| oc-builtin variance run 2 (2026-05-16) | 60.07% | 64.18% | 61.37% | 64.58% | 79.67% | 18.61% |
| oc-builtin-vector full (2026-05-18) | 59.57% (1183/1986) | 67.02% | 59.50% | 65.62% | 79.90% | 15.21% |

Per-category deltas vs the strongest prior baseline
(`oc-builtin full 2026-05-13`):

- cat 1 (single-hop): **+12.8 pp**
- cat 2 (multi-hop): **+9.4 pp**
- cat 3 (open-ended): **-6.2 pp** ← only category where builtin wins
- cat 4 (single-hop temporal): **+7.4 pp**
- cat 5 (adversarial/abstain): **+2.5 pp**

## Setup

- Plugin: `@openclaw/openviking` v2026.4.33, installed into the eval
  profile at `~/.openclaw-eval/extensions/openviking/`. TypeScript source
  compiled locally to ESM-mode dist (no upstream tarball ships a prebuilt
  dist). `runtime-utils.js` patched out of a CommonJS `require()` call.
  `openclaw.plugin.json` patched to declare
  `contracts.tools = [add_resource, add_skill, memory_search,
  memory_recall, memory_store, memory_forget, ov_archive_search,
  ov_archive_expand, ov_search]` — the upstream tip manifest has this
  field; v2026.4.33 didn't, and the current OC plugin loader requires it.
- Eval profile config during the run:
  `plugins.slots.contextEngine = "openviking"`,
  `plugins.entries.memory-core.enabled = false`,
  `plugins.entries.openviking.enabled = true`,
  `plugins.entries.openviking.config = {baseUrl: "http://127.0.0.1:1933",
  agent_prefix: "eval-locomo-ov", isolateAgentScopeByUser: true}`.
  Per-row `tools.allow = {memory_recall, memory_store, memory_forget,
  ov_archive_expand, memory_search}`, snapshot-restored after the run.
- OpenViking server: CLI + server `0.3.17`, `auth_mode=dev`. VLM
  repointed from `qwen3.6-plus-2026-04-02` via Dashscope (account in
  arrears) to `deepseek-v4-flash` via DeepSeek's OpenAI-compatible
  endpoint. Extraction template
  `compression.memory_extraction` is model-agnostic; the only model
  name in the YAML is "Claude" inside an example payload, not a
  directive. Embedding model unchanged: `qwen3-embedding:0.6b` via local
  Ollama.
- Per-sample isolation: OC agent `eval-locomo-ov-bare-full-20260520-191844-conv-{26,30,41-44,47-50}`
  with workspaces under
  `~/.openclaw-eval/workspace-ov-bare-full-20260520-191844-conv-*`.
  OV scope per sample is the plugin formula
  `<agent_prefix>_<oc_agent_id>` = e.g.
  `eval-locomo-ov_eval-locomo-ov-bare-full-20260520-191844-conv-26`,
  unique per sample inside the shared dev account.
- Dataset: `locomo10.json` (sha256 unchanged from prior runs), cats
  1-5, 1986 QA total. Cat 5 was QA-only on the already-ingested agents,
  then merged into the cat-1-4 artifacts under the same run dir.
- Harness change: new `OpenClawOVPluginBackend` in `lib/backends.py`,
  per-row config matrix orchestration in `main.py:_collect_one_backend`,
  pre-flight + write + runtime-evidence probes in `lib/openclaw_plugin.py`,
  `lib/openclaw_profile.py`, `lib/openviking_verify.py`. CLI flags
  `--row-agent`, `--answer-model`, `--openviking-server-base-url`,
  `--openviking-agent-prefix`, `--allow-unverified-hybrid-row`.

## Reading the deltas

- **cat 1 / cat 2 / cat 4 wins (+7 to +13 pp).** OV's `assemble +
  auto-recall + extracted-memory` returns denser, pre-linked records
  for direct-lookup and reasoning questions. Builtin's `MEMORY.md` +
  hybrid retrieval scans verbatim conversation text and tends to surface
  raw context blocks that the agent then has to re-parse on every turn.
  The OV extractor's L0/L1/L2 three-level structure (per its template
  metadata) effectively pre-computes "who, what, when" facts.
- **cat 3 loss (-6.2 pp).** Open-ended questions reward access to the
  raw conversation text. Builtin's durable markdown keeps the original
  phrasing verbatim; OV's extracted memory paraphrases. Some open-ended
  prompts are best answered by quoting back the original message rather
  than recalling a fact, and OV loses signal there.
- **cat 5 (adversarial/abstain) flat-ish.** Both stacks struggle to
  refuse fabricated premises (range 13-19% across builtin runs). OV at
  18.39% sits inside that range. The bottleneck here is the answer
  model's willingness to abstain, not the memory backend. Most cat-5
  failures are the agent confidently answering the wrong-person framing
  in the question (e.g. "What did Caroline realize after her charity
  race?" when Melanie ran the race) by attributing the fact to Caroline
  anyway. The agent often *does* surface the correction text — but the
  judge prompt grades against the gold fact alone, and a "well actually
  it was Melanie who…" preamble does not always survive the judge's
  topic match.

## Cost

| Token bucket | Value | Notes |
|---|---|---|
| OC ingest (answer-agent storing context) | 1.24M in / 84K out | per `ingest_summary.json` |
| OC QA (cat 1-4) | 30.47M in / 322K out | per `qa_summary.json` before merge |
| OC QA (cat 5 top-up) | 4.95M in / 67K out | per cat-5 `qa_summary.json` |
| Judge (cat 1-4) | ~3M | rough |
| Judge (cat 5 re-run) | ~3M | rough |
| **OV server VLM extraction (deepseek)** | **23.78M total (20.4M in / 3.4M out, 1222 calls)** | OV's `vlm` slot, used for memory extraction Phase 2 |
| **Grand total deepseek burn** | **~67M tokens** | |

Published OV-bare comparison reported 4.26M total input tokens with
`seed-2.0-code`. Our 67M is roughly 15.6x more, driven by:

1. `deepseek-v4-flash` writes longer responses than `seed-2.0-code` at
   each agent turn.
2. The OV plugin runs a `commit(wait=true) → memory_extractor` Phase 2
   on every committed session, which we now use deepseek for too. That
   doubles the per-session token cost vs a hypothetical extraction-free
   pipeline.
3. The QA prompts include OV's pre-assembled `<relevant-memories>`
   block on every turn, growing prompt size.

Wall time: ingest 4h48m, QA cat 1-4 ~50m, cat 5 top-up ~18m, judging
~12m. Total ~6.0 hours for the combined run.

## Comparison class

The manifest will record `comparison_class = "approximation"` because
three of the four published-row variables drift:

| Variable | Published | This run |
|---|---|---|
| Dataset filter | 1540 cases (cats 1-4, cat 5 removed) | 1986 cases (cats 1-5) — wider on purpose, to match our local builtin baselines |
| OV server | 0.1.18 | 0.3.17 |
| Answer model | `seed-2.0-code` | `deepseek/deepseek-v4-flash` |
| Judge | unspecified | `deepseek-v4-flash` |

The headline 70.24% number is therefore **not** a reproduction of the
published 52.08%. It is a `directional rerun under approximation
class`. The right way to read this row is: *holding our local stack
fixed, how does the OV plugin compare to our own builtin baselines?*
The 70.24 vs 56-64 spread answers that.

If exact-reproduction of the published table is the goal later, we
need: (a) pin OV server to 0.1.18, (b) pick `seed-2.0-code` as the
answer model (currently requires byteplus credentials, none on this
host), (c) judge-model parity, (d) re-narrow the dataset filter to cats
1-4 only. Each of those is one PR.

## Variance caveat

`oc-builtin` runs at the same config produced 56.19 / 60.07 / 63.54
across three full runs — a 7.35 pp spread. Until we have at least one
re-run of `oc-ov-plugin-bare` at the same config we cannot say how much
of the +7-to-+14 lift is the OV plugin and how much is sampling noise
across the agent + extractor + judge stack. A single variance re-run
is cheap (one more ingest+QA+judge cycle, ~6 hours of wall time,
similar token cost). Recommend running it before promoting the row to
publishable.

## Caveats / honest debt

- **Write-verification probe records false negatives.**
  `memory_write_verification.json` lists `write_detected=false` for all
  10 samples. The probe calls `ov session list --agent-id <id> --user
  <eval_user>`, but the OV plugin stores under `--user default` (the
  plugin does not forward our per-sample OC user to OV's user-tier
  scope). Memories ARE stored — verified during smoke via `ov find
  "Caroline adoption"` returning 3 hits with scores 0.69 / 0.66 / 0.54,
  and during the full run via 1,222 successful `session.commit` calls
  and 196 OV-side `Extracted N memories` log lines. The probe needs to
  switch to `ov find` with a sample-content canary, or pass `--user
  default`. Filed as a follow-up.
- **Runtime-evidence scanner sees zero tool calls + zero hooks per
  sample.** The plugin operates as a *context-engine* (server-side
  lifecycle hooks invoked by OC itself before each turn) rather than
  via model-visible tool calls. The OC agent transcripts the scanner
  reads do not include the plugin's internal HTTP calls. Either the
  scanner needs an OC-side hook telemetry source, or runtime evidence
  must be sourced from `~/.openviking/data/log/openviking.log`
  directly. Filed.
- **Judge proxy bug surfaced mid-eval.** The user's shell exports
  `http_proxy` / `https_proxy` / `all_proxy` for company VPN tooling.
  httpx's default `trust_env=True` picked those up; the proxy was
  unreachable; the judge logged "Connection error." against every cat-5
  grade and returned 0/446. Fixed in `lib/judge_util.py` by passing
  `httpx.AsyncClient(trust_env=False)` to AsyncOpenAI. Cat-5 was then
  re-judged cleanly. Cat-1-4 judging from the original run was not
  affected — that batch ran successfully end-to-end.
- **`oc-ov-plugin-augmented` (the +memory-core row) is held behind a
  `--allow-unverified-hybrid-row` flag.** The published "+memory-core"
  row's exact tool surface is unverified; widening `tools.allow` to
  include both OV and OC builtin memory tools risks producing a hybrid
  row that doesn't match the published config. The plan tracks this as
  Open Question O4.
- **OV server VLM is on deepseek, not the configured Dashscope.** The
  user's Alibaba ModelStudio account is in arrears. The repoint is in
  `~/.openviking/ov.conf` with a backup at
  `~/.openviking/ov.conf.bak-pre-deepseek-20260520-191120`. Reverse the
  repoint to compare deepseek-extraction vs qwen-extraction once the
  account is restored.

## Artifacts

- Plan: `docs/design/openviking-memory-eval-plan.md`
- Run dir: `output/runs/ov-plugin-bare-full-20260520-191844/`
  - `oc-ov-plugin-bare/manifest.json` — observed live config snapshot,
    `comparison_class="approximation"`, `category_policy=1,2,3,4,5`,
    `dataset_qa_count_selected=1986`
  - `oc-ov-plugin-bare/qa.jsonl` — 1986 records (1540 cat 1-4 + 446 cat 5
    appended from the merged cat-5 run)
  - `oc-ov-plugin-bare/judge_grades.json` — 1395 / 1986 = 70.24%
  - `oc-ov-plugin-bare/report.html` — regenerated with all 5 categories
  - `oc-ov-plugin-bare/memory_write_verification.json` — known false
    negatives (see caveats)
  - `oc-ov-plugin-bare/openviking_runtime_evidence.json` — known
    coverage gap (see caveats)
  - `oc-ov-plugin-bare/canary.jsonl` — cross-sample contamination
    canaries + adversarial isolation cases
  - `oc-ov-plugin-bare/openviking_cross_scope_isolation.json` —
    cross-agent scope probe
- Eval-harness commit: branch `dev`, see commit adding the OV plugin
  backend and Phase 1-3 modules.
- OV plugin install state: `~/.openclaw-eval/extensions/openviking/.ov-install-state.json`
  records `requestedRef=v0.3.14`, `releaseId=2026.4.33`, install path
  recorded as `path` install from `~/.openclaw/extensions/openviking`.

## What to do next

1. **Variance re-run** of `oc-ov-plugin-bare` at the same config, fresh
   row agents, fresh OV scope. If the second run lands within ±2 pp of
   70.24%, the lift over builtin is robust. If it swings into the
   builtin variance band (56-64%), we need to look for OV-side
   nondeterminism in the extractor.
2. **Fix the write-verification probe** so the publishability gate stops
   recording false negatives. Either switch to `ov find <sample
   canary>` or pass `--user default` to `ov session list`.
3. **Land the runtime-evidence path from OV logs** so we have a
   first-class signal that the plugin engaged, independent of OC agent
   transcripts.
4. **Resolve hybrid-row Q (O4)** before unblocking
   `oc-ov-plugin-augmented`. Concretely: read the OV plugin's own
   `__tests__/` for the assumed combined-row tool surface, or ask
   upstream.
5. **Cat-3 follow-up.** OV's only weak category vs builtin. Worth
   inspecting a sample of cat-3 failures to see whether the loss is
   structural (paraphrased memory eating the answer) or just
   recoverable with a "quote relevant memory verbatim" tweak to OV's
   `assemble` prompt.
