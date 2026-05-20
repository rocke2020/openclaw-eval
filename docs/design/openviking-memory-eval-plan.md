# OpenViking Memory Eval — Plugin Reproduction Plan

**Authoring stamp:** 2026-05-20, branch `dev`, base commit `1e774a5`, OpenClaw reference `OpenClaw 2026.5.7 (eeef486)`, OpenViking server `0.3.17 (auth_mode=dev)`, OV plugin package `@openclaw/openviking 2026.4.33` (installed at `~/.openclaw/extensions/openviking/`, **dist not built — pre-flight gate**).

## Goal

Run a **local-plugin directional rerun** of the published `volcengine/OpenViking` "OpenClaw + OpenViking Plugin" comparison inside this harness, and decide on the strength of that signal whether to invest in an exact reproduction (pinned OV server, pinned answer model, matched judge).

Codex review (see appendix) flagged the original "reproduce" framing as overclaimed: OV server is local 0.3.17 vs published 0.1.18, the published judge model is unspecified, and `seed-2.0-code` availability on this host is unverified. **Exact reproduction is out of scope of this plan.** The artifact this plan delivers is a directional rerun whose manifest is honest about every fixed/floating variable.

Published rows being directionally rerun:

| Published row | Published score | Published input tokens |
|---|---|---|
| OpenClaw + OpenViking Plugin (-memory-core) | 52.08% | 4,264,396 |
| OpenClaw + OpenViking Plugin (+memory-core) | 51.23% | 2,099,622 |

Reference baseline (existing harness row, used for slope comparison only — not in this plan's delivery scope):

| Reference (already supported) | Score | Input tokens |
|---|---|---|
| OpenClaw (memory-core) | 35.65% | 24,611,530 |

Source: <https://github.com/volcengine/OpenViking> README, "Effect testing based on LoCoMo10". Dataset card: **1,540 cases after removing category 5** (no ground truth). Eval-script lineage cited as `https://github.com/ZaynJarvis/openclaw-eval/tree/main` — the upstream of this fork.

**Comparison semantics.** Every manifest for `oc-ov-plugin-*` rows carries `comparison_class ∈ {"exact_reproduction", "directional_rerun", "approximation"}`. The class is computed from observed values, not declared from flags:

- `exact_reproduction` ⇐ OV server `0.1.18` AND answer model `seed-2.0-code` AND judge model matches published (currently unknown) AND dataset hash matches the published filter.
- `directional_rerun` ⇐ same dataset filter, but any of the other three drifts. This is the bar this plan ships against.
- `approximation` ⇐ anything weaker.

## Architecture

Both new rows use **the same OpenClaw agent loop** (`send_message_with_retry` against the existing `/v1/responses` gateway). What changes is OC's context-engine slot and the memory-core plugin's enabled flag. The harness controls those via `openclaw --profile eval config set` before each backend's ingest+QA, and re-asserts them in the strict-isolation gate.

```
   Per-row config delta (eval profile):
   ──────────────────────────────────────────────────────────────────────────
   Row id                       contextEngine slot   memory-core.enabled
   ──────────────────────────────────────────────────────────────────────────
   oo-builtin (already exists)  legacy               true
   oc-ov-plugin-bare       (new) openviking           false
   oc-ov-plugin-augmented  (new) openviking           true
   ──────────────────────────────────────────────────────────────────────────

   Agent loop (unchanged):
   LoCoMo session text
     → POST /v1/responses (OpenClaw gateway)
       → OC agent eval-locomo-<sample_id>
         → context-engine slot: legacy (builtin) OR openviking (plugin assemble/afterTurn/compact)
         → optional memory-core plugin (durable MEMORY.md write path)
     → reply
   QA question
     → POST /v1/responses with same agent + per-sample user
     → judge model grades reply

   Per-sample OV scope (auto, no harness work):
     OV plugin formula:   "<agent_prefix>_<OpenClaw ctx.agentId>"
     With agent_prefix="eval-locomo-ov" and OC agent="eval-locomo-<sample_id>",
     OV scope becomes:    eval-locomo-ov_eval-locomo-<sample_id>
     ⇒ Per-sample isolation comes for free from existing OC provisioning.
```

## Tech stack

Python 3.13, `unittest` (pytest discovery), OpenClaw 2026.5.7 with plugin loader, `@openclaw/openviking` 2026.4.33 (TypeScript context-engine plugin, requires built `dist/`), OpenViking server 0.3.17, LoCoMo10 JSON, JSONL/JSON artifacts.

---

## Current Reality (2026-05-20)

What is already true on this host:

- `~/.openclaw/extensions/openviking/` exists with the v2026.4.33 source but **no compiled `dist/` output**. Every `openclaw …` invocation prints two `Config warnings` (one for `openclaw-weixin`, one for `openviking`) saying `requires compiled runtime output for TypeScript entry index.ts`. The plugin is therefore **declared but inactive**. This is a hard pre-flight gate — until the dist exists, the plugin cannot load and the new rows cannot run.
- `plugins.slots.contextEngine` globally is `"legacy"`; the eval profile does not set it (lookup returns `Config path not found`). To activate OV, the eval profile must set this slot to `"openviking"`.
- `plugins.entries.memory-core.enabled` is `true` in the eval profile (with `dreaming.enabled=false`). The `-memory-core` row requires flipping this to `false` and restarting the gateway; the `+memory-core` row keeps it as-is. Both rows must verify the live value after the restart.
- `memory.backend` in the eval profile is `"builtin"`. The OV plugin owns its own memory through `contextEngine`; `memory.backend` continues to control whatever memory-core uses when memory-core is enabled. Leave `memory.backend=builtin` for the `+memory-core` row; the `-memory-core` row makes `memory.backend` moot (memory-core is off).
- OV server: `curl http://127.0.0.1:1933/health` returns `{"status":"ok","healthy":true,"version":"0.3.17","auth_mode":"dev"}`. The plugin will speak to this URL.
- OV plugin manifest (`openclaw.plugin.json`) declares config keys: `baseUrl`, `apiKey`, `agent_prefix`, `isolateUserScopeByAgent`, `isolateAgentScopeByUser`, `agentScopeMode` (deprecated), `targetUri`, `accountId`, `userId`, `timeoutMs`. The agent-prefix formula `"<prefix>_<ctx.agentId>"` means per-sample OV scope falls out automatically from existing per-sample OC agent provisioning — no new OV-side provisioning code is needed.
- The harness already has the `openviking` backend id pointing at the **retrieval-only** `OpenVikingBackend` (`answer_mode="openviking-search-rag"`). This row is replaced by the new plugin-based rows and is **deleted** by this plan after the first publishable plugin run (see "Replacement and cleanup"). Until then, the retrieval-only id remains usable behind `--allow-non-publishable` for one-off retrieval baselines.

What needs to happen for the two new rows to land:

1. Build the OV plugin `dist/` so the loader stops warning and the plugin can register the `openviking` context-engine.
2. Configure the eval profile's `plugins.slots.contextEngine`, `plugins.entries.memory-core.enabled`, and `plugins.entries.openviking.config` per row, restart the gateway, then re-read the live config to confirm.
3. Update the strict-isolation gate to allow the OV plugin's memory tools (`memory_recall`, `memory_store`, `memory_forget`, `ov_archive_expand`, `memory_search`) and to keep denying agent-tooling extension tools (`add_resource`, `add_skill`) that would let the model widen OV scope mid-eval.
4. Add a thin backend class that records per-row config in the manifest and verifies it from live OC config (not from harness flags) so the manifest cannot lie.
5. Verify per-sample isolation by probing OV's session listing across sample agent prefixes.
6. Reproduce the published numbers and record any deltas with their causes (OV server version, answer model availability, dataset hash).

---

## Hard Reproduction Constraints

These are the variables the published comparison fixed. Each one becomes a manifest field plus a smoke-time check.

| Variable | Published value | Local plan | Comparison-class impact |
|---|---|---|---|
| Dataset | LoCoMo10, 1,540 QA cases after removing category 5 | Run `--include-categories 1,2,3,4 --exclude-categories 5`. Confirm `qa_summary.total == 1540` post-run; loud failure if not. Hash the filtered question set; record `dataset_filtered_hash` and compare against an upstream-or-derived expected hash. | Must match for `directional_rerun`. |
| OpenViking server | 0.1.18 | Local server is 0.3.17. Plan ships against 0.3.17; running 0.1.18 in parallel is **moved to Open Question O5** (no longer in "NOT in scope"). The manifest records `openviking_server_version` and `openviking_server_version_matches_published`. | Drift drops class to `directional_rerun`. |
| Answer model | `seed-2.0-code` | The byteplus provider plugin is bundled but **currently disabled** on this host (smoke confirmed). Pre-flight enables byteplus AND probes that `seed-2.0-code` is reachable via the OC gateway by running one no-op `/v1/responses` call with that model. If the model is unreachable, the run **fails the pre-flight gate** — no silent substitution. Substitution to another model requires an explicit `--answer-model-substitute <m>` flag and forces `comparison_class="approximation"`. | Drift drops class to `directional_rerun` (substitute) or fails pre-flight (unreachable). |
| Metric — Task completion | Task completion rate (judge-graded) | Maps to existing `judge_grades.score`. No code change. | Comparison signal only. |
| Metric — Input tokens | Total input tokens (the published table does not specify counting source) | Captured today via `qa_summary.usage.input_tokens` (OpenClaw's accounting). **Codex flagged that token-accounting equivalence is unproven** — the published number may include ingest tokens, retries, or be sourced from the model provider's counter. Manifest records `input_tokens_accounting_source = "openclaw_qa_summary"` and notes that exact equivalence is not asserted. Adding ingest-token totals as a separate manifest field is in scope here (it's free, already captured per record). | Comparison signal only; uncertainty noted in journal. |
| Judge model | Not specified in published table | Keep `deepseek-v4-flash` and record it. **Codex flagged this weakens completion-rate attribution.** Mitigation: re-judge a sample of answers with a second model (whichever the user can run) and report Cohen's κ between judges in the journal entry — single-judge attribution is otherwise indefensible. | Locked at `directional_rerun` regardless until matched. |

---

## Step 0 — Scope Challenge

### What existing code already partially or fully solves each sub-problem

| Sub-problem | Existing code | Reuse plan |
|---|---|---|
| Agent loop (ingest + QA over `/v1/responses`) | `lib/openclaw.py:send_message_with_retry`, `main.py:run_ingest`, `run_qa` | Reuse verbatim. Both new rows route through this. |
| Per-sample agent provisioning | `lib/agent_provision.py` (`<base>-<sample_id>` agent + per-sample workspace) | Reuse verbatim. OV per-sample scope comes for free via the plugin's `<prefix>_<ctx.agentId>` formula. |
| Per-sample user keying | `lib/locomo.py:default_sample_user` | Reuse. |
| Strict eval isolation | `verify_strict_eval_isolation` checks `tools.allow == {memory_search, memory_get, write, edit}`, `tools.deny` contains forbidden tools, `tools.elevated.enabled=false`, no visible skills | Extend, do not refactor. Add per-row allowlists (see "Strict-isolation matrix" below). |
| Runtime backend evidence | `verify_runtime_memory_search_backend` scans agent session JSONL for `memory_search` tool calls with `debug.backend == "builtin"` | Reuse for the `+memory-core` row's memory-core path. Add a sibling scanner for OV plugin tool calls (`memory_recall`/`memory_search`/`memory_store`) for both new rows. |
| Memory-write verification | `lib/memory_verify.py` snapshots `MEMORY.md` + `memory/*.md` and diffs | Reuse for the `+memory-core` row. For the `-memory-core` row, memory-core writes nothing — add an OV-side probe: post-ingest `ov session list --agent-id <ov_scope_agent> --user <u> --output json` returns ≥1 session per sample. |
| Cross-sample contamination canaries | `select_canary_pairs` is backend-agnostic | Reuse verbatim — questions route through the same `_call_answer` path. |
| Adversarial isolation canaries | `ADVERSARIAL_CANARY_CASES` (asks about `${OPENCLAW_HOME}`, `memory_get` over absolute paths) | Mostly portable. Tool-escape and absolute-path canaries probe OC's `memory_get` which is also exposed via OV plugin tool set. Recast the probe text to mention OV `viking://` URIs as well; keep `leak_markers`. |
| Manifest builder | `lib/artifacts.py:build_manifest` already records `openclaw_version`, `openclaw_profile`, `openclaw_base_url`, judge model fields, etc. | Extend with the OV-plugin-conditional fields enumerated under "Manifest contract". |
| Run pipeline | `main.py:_collect_one_backend` — provisions, ingests, runs runtime evidence (for `oo-builtin-vector`), runs QA, then publishability gate | Add a `before_each_backend(args, backend)` hook that mutates the eval profile config to the per-row state, restarts the gateway, and re-reads the live config; restore state in `after_each_backend`. |
| Comparison report | `lib/artifacts.py:render_comparison_report_html` reads `group_manifest`, per-backend manifests, judge scores | Add reproduction-target columns (published score / token count) and a delta column for the two new rows; no other shape changes. |

### Minimum set of changes that achieves the stated goal

1. **Pre-flight gate**: `lib/openclaw_plugin.py:assert_openviking_plugin_loaded()` runs `openclaw plugins doctor --json` (or `openclaw plugins list --json`) and refuses to start a run if the OV plugin reports `requires compiled runtime output`. Surfaces a one-line repro command (`cd ~/.openclaw/extensions/openviking && npm install && npm run build`, or `openclaw plugins install @openviking/openclaw-plugin`).
2. **Config orchestration**: `lib/openclaw_profile.py` exposes `read_profile_config(profile, key)`, `set_profile_config(profile, key, value)`, `restart_gateway(profile)`, `snapshot_profile_keys(profile, keys) → ctx-mgr` (records pre-state, restores on exit even on failure). Surgical, no other harness module knows about config mutation.
3. **Per-row config matrix** in `lib/backends.py`: a small dict, single source of truth, that names every key each row mutates and the expected post-mutation value. Used by the orchestration helper and asserted by the manifest builder.
4. **Backend class**: `OpenClawOVPluginBackend(memory_core_enabled: bool)` with two registry ids (`oc-ov-plugin-bare`, `oc-ov-plugin-augmented`). Both reuse `OpenClawBackend.ingest`/`answer`; the only new field is `memory_core_enabled`, which the manifest builder reads and the strict-isolation gate uses to pick an allowlist.
5. **Strict-isolation gate extension**: `verify_strict_eval_isolation_for_backend(profile, agent, backend)` dispatches by backend kind/id. Existing `oo-*` rows hit the existing path. The two OV plugin rows hit a new path with per-row allowlists (see matrix).
6. **OV-side write verification**: `lib/openviking_verify.py:probe_session_exists(account, agent_id, user)` — read-only `ov session list` call; emits `write_detected=true` when ≥1 committed session is present.
7. **Runtime evidence scanner extension**: `verify_runtime_ov_plugin_evidence(openclaw_home, agent_ids)` finds OV plugin tool calls in agent JSONL transcripts and asserts at least one OV plugin call per sample.
8. **Manifest extension**: OV-plugin-conditional fields. The builder probes live config to record observed values — never trusts harness flags. If observed and expected disagree, the run is non-publishable.
9. **CLI flags**: `--openviking-server-base-url` (default `http://127.0.0.1:1933`), `--openviking-api-key` (or `${OPENVIKING_API_KEY}`), `--openviking-agent-prefix` (default `eval-locomo-ov`), `--answer-model` (default `seed-2.0-code`). Pre-existing `--openviking-account` is reused.
10. **Tests** for each new helper (no skipped negative paths).
11. **Journal entry** at `docs/eval-journal/<date>-openviking-plugin-reproduction.md` after first publishable run.

### Complexity check

- **Files touched.** New: `lib/openclaw_plugin.py`, `lib/openclaw_profile.py`, `lib/openviking_verify.py`, plus three matching test files. Extended: `lib/backends.py`, `lib/artifacts.py`, `main.py`, `tests/test_eval_backends.py`, `tests/test_eval_artifacts.py`. Six new, five extended = **11 files**, above the 8-file smell line.
  **Justification.** Each new module owns one decision point: plugin readiness, profile mutation, OV-side memory verification. Merging them would couple three unrelated failure modes (the plugin can be unbuilt, the gateway can refuse a restart, OV can fail to commit a session) into one module and one test file, making publishability harder to test in isolation. Accept the count; reject the merge.
- **New classes.** 1 (`OpenClawOVPluginBackend`, parameterized by `memory_core_enabled`). Within budget.

### Search check (Layer 1 / 2 / 3)

- **[Layer 1] Profile mutate-then-restart pattern.** Already used by `provision_sample_agents` (calls `openclaw gateway restart` once after batch provisioning). Reuse the same call site discipline: collect all mutations, restart once per row, re-read live config.
- **[Layer 1] Live-config-as-source-of-truth.** Already in `lib/backends.py:read_openclaw_memory_search` and `read_openclaw_memory_backend`. Mirror: every new manifest field that names a config key is sourced from a `read_profile_config(profile, key)` call, not a CLI flag.
- **[Layer 2] OV plugin agent-prefix formula.** From `~/.openclaw/extensions/openviking/openclaw.plugin.json` uiHints, the formula is `"<prefix>_<ctx.agentId>"` (sanitised). Setting `agent_prefix = "eval-locomo-ov"` with per-sample OC agent `eval-locomo-<sample_id>` makes the OV scope `eval-locomo-ov_eval-locomo-<sample_id>` — unique per sample, no extra provisioning. Verified locally; documented in plan body.
- **[Layer 3 / EUREKA recorded]** OV publishability invariant is **slot ownership**, not tool allowlist. OC's gate is `tools.allow = {memory_search, memory_get, write, edit}` because the model otherwise gets `exec`/`read`/`apply_patch`. The OV plugin replaces the **context-engine slot**, so the "no extra paths" invariant becomes: (a) `plugins.slots.contextEngine == "openviking"` on the eval profile, (b) the live tool allowlist includes OV memory tools and **excludes** OV agent-tooling extension tools (`add_resource`, `add_skill`) that would let the model widen scope, (c) no visible skills, (d) cross-agent OV probe returns empty. Smaller, sharper gate than the OC-only one.

### TODOS

`TODOS.md` does not exist. Items this plan defers are listed below in "NOT in scope". Create `TODOS.md` only if deferrals exceed three after the first publishable run.

### Completeness check

Complete-with-AI version is what this plan describes: dist-build pre-flight + config orchestration + two-row backend + strict-isolation extension + OV-side write probe + runtime evidence + manifest extension + tests + reproduction journal. Shortcut version would be "wire the OV plugin manually, run two rows, paste numbers into a doc." Marginal cost of the complete version is on the order of two reviewers' time plus the new test files, not weeks. Recommend complete.

### Distribution

Not applicable. No new artifact. Internal harness change.

---

## Strict-isolation matrix (per row)

The OC eval profile must hold these values when each row runs. The strict-isolation gate **reads from live config** and refuses the run on any drift.

| Key | `oo-builtin` (existing baseline) | `oc-ov-plugin-bare` (new) | `oc-ov-plugin-augmented` (new) |
|---|---|---|---|
| `plugins.slots.contextEngine` | `legacy` (or unset) | `openviking` | `openviking` |
| `plugins.entries.memory-core.enabled` | `true` | `false` | `true` |
| `plugins.entries.openviking.enabled` | irrelevant | `true` | `true` |
| `memory.backend` | `builtin` | `builtin` (unused by core when disabled) | `builtin` |
| `tools.allow` | `{memory_search, memory_get, write, edit}` | `{memory_recall, memory_store, memory_forget, ov_archive_expand, memory_search}` | (see hybrid-row warning below) |
| `tools.deny` (must include) | the existing `STRICT_FORBIDDEN_TOOLS` set | `STRICT_FORBIDDEN_TOOLS ∪ {add_resource, add_skill}` | `STRICT_FORBIDDEN_TOOLS ∪ {add_resource, add_skill}` |
| `tools.elevated.enabled` | `false` | `false` | `false` |
| `skills check modelVisible/commandVisible` | empty | empty | empty |

**Why `add_resource` and `add_skill` are denied.** They let the model write into OV scope and register new agent skills mid-eval. That widens the surface beyond LoCoMo memory and breaks the reproduction story. Out of scope for a memory-only eval.

**Codex-flagged correctness pitfalls (must resolve before strict gate ships):**

- **`memory_search` namespace collision.** When both memory-core and OV plugin are enabled, both may register a tool named `memory_search`. The OC `tools.allow` allowlist is name-based and cannot distinguish *which provider* the model invoked. Without **provenance** (e.g. tool-call metadata naming the registering plugin), the gate is a false-positive generator. Mitigation that ships with this plan:
  - `lib/openclaw_plugin.py:enumerate_tool_providers(profile, tool_name)` calls `openclaw plugins inspect <name> --json` for every enabled plugin and asserts that exactly one plugin registers each name in the row's allowlist — OR records the provenance pair `(tool_name, registering_plugin_id)` in the manifest under `tools_allow_provenance`. If a name is registered by multiple plugins, the gate fails until the conflict is resolved (e.g. by denying one provider's variant).
  - The runtime evidence scanner reads the provenance frame from the agent transcript when present (the OC SDK exposes `details.providerId` or equivalent on tool-result records) — see updated runtime evidence section below.
- **Hybrid-row warning.** The published "+memory-core" row's actual tool surface is unverified by this plan. Listing both OV memory tools AND OC builtin memory tools in `tools.allow` for `oc-ov-plugin-augmented` may produce a *hybrid* row that does not match what `volcengine/OpenViking` measured. Until O4 (below) resolves this, `oc-ov-plugin-augmented` is **provisionally disabled** behind a `--allow-unverified-hybrid-row` flag; only `oc-ov-plugin-bare` runs publishable. The smoke + first journal entry record what tool calls the agent actually makes in the augmented row, so the surface can be aligned with published numbers in a follow-up.

---

## What Already Exists (reuse map)

Same answer as the table in Step 0. Shortest restatement:

- **Reuse verbatim**: OC agent loop, per-sample agent provisioning, per-sample user keying, cross-sample contamination canaries, judge pipeline, run-group structure, JSONL artifact writers, the existing `oo-builtin` row (used as published-baseline reference, not delivered by this plan).
- **Reuse with adaptation**: strict-isolation gate (extend per-row allowlists), adversarial canary cases (recast probe text to mention `viking://` URIs), manifest builder (OV-conditional fields), runtime evidence scanner (add OV plugin tool detection).
- **Do not reuse**: nothing is replaced. The existing retrieval-only `OpenVikingBackend` is removed after the first publishable plugin run; until then it stays accessible behind `--allow-non-publishable` for retrieval-only experiments.

---

## NOT in Scope (explicit deferrals)

1. **The LanceDB row** from the published table (44.55% / 51.5M tokens). Different memory stack entirely.
2. **The OC-only baseline row** (35.65% / 24.6M tokens). Already supported via the existing `oo-builtin` backend.
3. **Exact reproduction** (per "Goal" section). Pinned OV `0.1.18`, matched judge model, and confirmed answer-model parity are gated behind the directional rerun's findings. See **Open Question O5**.
4. **Replacing the retrieval-only `OpenVikingBackend`.** Kept as-is. Per codex feedback, deletion is **decoupled from this plan's success/failure**: removed in a separate single-purpose PR when the user decides, not when this PR scores well.
5. **Per-account OV isolation.** OV server runs in `auth_mode=dev`. Account-tenancy requires switching to `api_key` mode. This plan relies on agent-prefix scoping inside the dev account.
6. **`oo-` → `oc-` registry rename.** Cross-cutting string rename; separate PR.
7. **Adding either new row to `DEFAULT_EVAL_BACKENDS`.** Until both new rows have published journal entries.
8. **HTML comparison report styling for OV plugin rows.** New manifest fields render through the existing iteration path; bespoke styling deferred.
9. **`commitTokenThreshold` ablation.** Held at plugin default.
10. **`oc-ov-plugin-augmented` publishable run.** Provisionally disabled until O4 resolves the hybrid-row surface question — see "Strict-isolation matrix" → "Hybrid-row warning".

---

## Failure Modes (each new codepath)

| Codepath | Realistic failure | Test | Error handling | User-visible failure |
|---|---|---|---|---|
| Pre-flight `assert_openviking_plugin_loaded` | dist not built; `openclaw plugins doctor` reports `requires compiled runtime output` | Yes — `test_openclaw_plugin.py::test_pre_flight_fails_when_dist_missing` | Refuse to start; print one-line repro command | Run aborts with explicit fix-it message |
| `read_profile_config` returns unexpected JSON shape | OC config schema change between minor releases | Yes — `test_openclaw_profile.py::test_read_handles_non_string_values` | Surface as `RuntimeError` with the key path | Run aborts with key path named |
| `set_profile_config` + `restart_gateway` partial failure | Gateway restart times out mid-mutation, leaves profile in an in-between state | Yes — `test_openclaw_profile.py::test_snapshot_restores_on_restart_failure` | `snapshot_profile_keys` is a context manager that restores pre-state on exit even when an exception is raised | Run aborts; profile config is left as found |
| OV plugin loaded but `contextEngine` slot not bound | Setup command not run yet, or another plugin took the slot | Yes — `test_openclaw_plugin.py::test_slot_assertion_fails_when_unset` | Manifest writes `openviking_slot_active=false`; publishability gate fires | Run completes but row marked non-publishable |
| `probe_session_exists` reports zero sessions after a successful ingest | OV server queue silently swallowed messages, or the agent didn't `memory_store` | Yes — `test_openviking_verify.py::test_zero_sessions_marks_write_undetected` | `memory_write_verification.invariant_held=false`; publishability gate fires | Row marked non-publishable; journal entry explains zero-write evidence |
| `verify_runtime_ov_plugin_evidence` finds no OV tool calls | Agent answered from context window without calling OV tools | Yes — `test_openviking_verify.py::test_runtime_ov_evidence_requires_one_per_sample` | Publishability gate fires | Row marked non-publishable |
| Cross-sample OV probe leaks | OV plugin scope namespace policy isn't enforcing what we think | Yes — `test_openviking_verify.py::test_cross_scope_probe_detects_leak` | Listed in `publishability_failures` | Run aborts before scoring with leak detail |
| Per-sample agent has stale memory from prior eval | Reusing the same `--builtin-agent` name across runs | Yes — `tests/test_agent_provision.py` (existing) | Existing `_workspace_has_memory` warning fires; user must pick a fresh base agent | Warning + non-publishable mark, no data loss |
| Answer model `seed-2.0-code` unavailable on local OC gateway | Provider plugin not loaded or model not entitled | Yes — `test_openclaw_plugin.py::test_answer_model_preflight` | Pre-flight gate fails | Run aborts before any data write |

**Critical-gap audit.** Zero codepaths are silent-without-test-without-handler.

---

## Implementation Tasks

### Phase 1 — pre-flight + config orchestration (parallel-safe)

- [ ] **1.1** `lib/openclaw_plugin.py`
  - `assert_openviking_plugin_loaded(profile)` — calls `openclaw --profile <p> plugins doctor --json` (or `plugins list --json`), parses, returns `(ok, failures)`. Refuses if either plugin shows `requires compiled runtime output`.
  - `assert_answer_model_available(profile, model)` — calls `openclaw --profile <p> providers list --json` (or equivalent), looks for `model` in the listing, returns `(ok, failures)`.
  - One-line repro hint baked in.
- [ ] **1.2** Tests in `tests/test_openclaw_plugin.py`: dist-missing case, success case, schema-drift tolerance, answer-model present/absent.
- [ ] **2.1** `lib/openclaw_profile.py`
  - `read_profile_config(profile, key) -> JSON-decoded value | None`
  - `set_profile_config(profile, key, value) -> CompletedProcess` (only string/bool/JSON values)
  - `restart_gateway(profile)`
  - `snapshot_profile_keys(profile, keys) -> ContextManager[dict]` — records each key's current value, yields the dict, restores on exit even if the body raised.
- [ ] **2.2** Tests in `tests/test_openclaw_profile.py`: round-trip, snapshot restore on success, snapshot restore on exception, `set` rejects non-JSONable values.

### Phase 2 — backend + matrix + strict-isolation extension (sequential after Phase 1)

- [ ] **3.1** `lib/openviking_verify.py`
  - `probe_session_exists(server_base_url, account, agent_id, user, api_key) -> {write_detected, sessions_count}` (read-only `ov session list`, no writes/deletes).
  - `verify_strict_openviking_scope_isolation(server_base_url, base_agent_prefix, sample_ids, account, api_key) -> {ok, failures}` — for each adjacent `(i, j)` pair, `ov find` from sample i's user against sample j's agent must return zero hits.
  - `iter_ov_plugin_tool_calls(openclaw_home, agent_id)` and `verify_runtime_ov_plugin_evidence(openclaw_home, agent_ids) -> failures` — analog of the existing OC variant for the OV plugin's tool names.
- [ ] **3.2** Tests in `tests/test_openviking_verify.py`: happy path, zero-session case, cross-scope hit case, runtime evidence present/missing/malformed.
- [ ] **4.1** Extend `lib/backends.py`:
  - `OPENCLAW_OV_PLUGIN_ROW_MATRIX: dict[str, dict[str, Any]]` — single source of truth, keys `oc-ov-plugin-bare` and `oc-ov-plugin-augmented`, values are the per-row config from the matrix above.
  - `@dataclass OpenClawOVPluginBackend` extending the OC backend pattern with `memory_core_enabled: bool` and `expected_row_config: dict`. `publishability_failures` collects: plugin not loaded, slot mismatch, memory-core mismatch, tool allow/deny mismatch, ingest write-detection failure, runtime OV evidence failure, scope-isolation leak.
  - Register `oc-ov-plugin-bare` and `oc-ov-plugin-augmented` in `build_backend`.
- [ ] **4.2** Extend `tests/test_eval_backends.py`: both new row ids resolve; matrix is internally consistent; `publishability_failures` reports each failure mode.
- [ ] **5.1** Extend `verify_strict_eval_isolation` in `main.py`:
  - Existing `oo-*` paths unchanged.
  - For `oc-ov-plugin-bare` / `oc-ov-plugin-augmented`, switch to per-row allowlist/denylist from the matrix; assert OV-extension tools `add_resource`/`add_skill` are in `tools.deny`.
  - Assert `plugins.slots.contextEngine == "openviking"`, `plugins.entries.openviking.enabled == true`, `plugins.entries.memory-core.enabled` matches the row.
- [ ] **5.2** Extend `tests/test_eval_artifacts.py`: `test_strict_isolation_for_oc_ov_plugin_bare_requires_slot_and_disabled_memory_core`, `test_strict_isolation_for_oc_ov_plugin_augmented_requires_slot_and_enabled_memory_core`, `test_strict_isolation_for_oc_ov_plugin_denies_add_resource_and_add_skill`.

### Phase 3 — pipeline wiring (sequential)

- [ ] **6.1** Extend `main.py:_collect_one_backend`:
  - Wrap the per-backend block in `snapshot_profile_keys` so the eval profile is restored after each backend (even on failure).
  - Inside the block: `set_profile_config` each matrix key, `restart_gateway`, then call `wait_gateway_ready(profile, expected_pid=None, timeout_s=30)` that **(a)** waits for `/v1/responses` health to return OK, **(b)** captures the gateway PID from `openclaw status --json` (or process listing), **(c)** records that PID in the manifest. After health-ok, `read_profile_config` for every mutated key and assert live = expected. (Codex flagged: restore-on-exit alone can race a previous gateway process. PID + readiness evidence is now mandatory after every restart.)
  - **Pre-run empty-scope assertion** for OV rows: before any ingest, for each sample assert `probe_session_exists` returns zero sessions (no stale state). If any sample shows a pre-existing session, abort with the offending agent-id named. Codex flagged that the OV scope formula's "free isolation" claim was load-bearing without a pre-run probe; this gate eliminates that risk.
  - For OV rows: after ingest, call `probe_session_exists` AND `probe_positive_recall(sample_canary_token)` per sample. `probe_positive_recall` issues an `ov find` for a fact present in the sample's ingest content and asserts ≥1 hit. Codex flagged that "session count ≥ 1" proves existence but not durable memory; positive recall closes that gap.
  - After QA: call `verify_runtime_ov_evidence` which accepts **either** (a) model-visible OV plugin tool calls in the agent transcript, OR (b) context-engine lifecycle hook evidence (e.g. `assemble`/`afterTurn`/`commit` traces). Codex flagged that context-engine plugins may not surface tool calls to the model. Both evidence kinds satisfy the gate; their counts go into the manifest separately.
  - **Concurrency guard**: at the start of `_collect_one_backend`, acquire a file lock at `~/.openclaw-eval/profile-{profile}.lock`. Refuse to start if another harness invocation holds it. Codex flagged shared-profile mutation as fragile under concurrent runs; the lock makes that fragility explicit and recoverable.
- [ ] **6.2** Extend `lib/artifacts.py:build_manifest`:
  - When `backend_kind in {"oc-ov-plugin-bare", "oc-ov-plugin-augmented"}`, add the manifest fields below — sourced from live config, not flags.
  - Record the answer model from per-sample agent config (`agents.<agent_id>.model`).
- [ ] **6.3** CLI flags on `add_common_args`:
  - `--openviking-server-base-url` (default `http://127.0.0.1:1933`)
  - `--openviking-api-key` (or env `OPENVIKING_API_KEY`)
  - `--openviking-agent-prefix` (default `eval-locomo-ov`)
  - `--answer-model` (default `seed-2.0-code`; passed to `agent_provision._ensure_one_agent` via the existing `model` parameter)
  - Keep deprecated flags accepting current values for back-compat.

### Phase 4 — pre-flight + smoke + first publishable run

- [ ] **7.1** Build the OV plugin dist (one-time host setup): `cd ~/.openclaw/extensions/openviking && npm install && npx tsc -p tsconfig.build.json` (or use the upstream-recommended `openclaw plugins install @openviking/openclaw-plugin` for a pre-built version). Loudly verify with `openclaw plugins list 2>&1 | grep -iE "warning|openviking"`.
- [ ] **7.2** Wire OV plugin config (one-time per profile):
  ```bash
  openclaw --profile eval config set plugins.slots.contextEngine openviking
  openclaw --profile eval config set plugins.entries.openviking.enabled true
  openclaw --profile eval config set plugins.entries.openviking.config.baseUrl "http://127.0.0.1:1933"
  openclaw --profile eval config set plugins.entries.openviking.config.agent_prefix "eval-locomo-ov"
  openclaw --profile eval config set plugins.entries.openviking.config.isolateAgentScopeByUser true
  openclaw --profile eval gateway restart
  openclaw --profile eval openviking status --json
  ```
- [ ] **7.3** One-sample smoke: ingest one session + one QA on `locomo10_small.json` with `oc-ov-plugin-bare`. Inspect `ingest.jsonl` for an OV plugin tool call. If absent, diagnose before continuing.
- [ ] **7.4** Two-sample smoke with each new row in turn (per-row config flipping verified end-to-end).
- [ ] **8.1** Full publishable run with both new rows (1,540 cases after `--exclude-categories 5`, 10 samples). Run group `output/runs/openviking-plugin-reproduction-<YYYYMMDD-HHMMSS>/`.
- [ ] **8.2** Journal entry `docs/eval-journal/<date>-openviking-plugin-reproduction.md`:
  - Per-row score + per-row total input tokens
  - Delta vs published numbers; ascribe deltas to (a) OV server 0.3.17 vs 0.1.18, (b) answer-model availability, (c) judge model difference if any
  - Both rows' publishability state with each gate's pass/fail
  - One paragraph on observed behavioral differences in the answer transcripts

---

## Manifest contract (OV-plugin-conditional)

Sourced from **live config**, not flags. Fields under `backend_config` for `oc-ov-plugin-*` rows:

```jsonc
{
  "backend_id": "oc-ov-plugin-bare" | "oc-ov-plugin-augmented",
  "backend_kind": "openclaw",
  "agent": "<per-sample base agent>",
  "answer_model": "seed-2.0-code",
  "answer_model_available": true,
  "answer_model_substitute": null,
  "comparison_class": "directional_rerun",   // computed, not declared

  // Runtime identity — never trust package metadata alone (codex)
  "openclaw_ov_plugin_package_name": "@openclaw/openviking",   // observed in package.json
  "openclaw_ov_plugin_package_version": "2026.4.33",
  "openclaw_ov_plugin_source_commit": "<git -C ~/.openclaw/extensions/openviking rev-parse HEAD or null>",
  "openclaw_ov_plugin_dist_sha256": "<sha256 of dist/index.js (or all dist/*) after build>",
  "openclaw_ov_plugin_build_provenance": "local-tsc" | "npm-published-tarball",

  "openviking_server_version": "0.3.17",
  "openviking_server_version_matches_published": false,
  "openviking_server_base_url": "http://127.0.0.1:1933",
  "openviking_server_auth_mode": "dev",
  "openviking_cli_version": "0.3.17",

  "plugins_slots_context_engine": "openviking",
  "plugins_entries_memory_core_enabled": false | true,
  "plugins_entries_openviking_enabled": true,
  "plugins_entries_openviking_config": {
    "agent_prefix": "eval-locomo-ov",
    "isolateAgentScopeByUser": true
  },
  "ov_scope_pattern": "<agent_prefix>_<openclaw_agent_id>",

  // Tool surface with provenance (codex: name-only allowlist is ambiguous)
  "tools_allow": [/* per-row from matrix */],
  "tools_allow_provenance": [
    {"tool": "memory_search", "registering_plugin_id": "openviking"},
    /* one row per allowed tool; failure if any tool has >1 registrar */
  ],
  "tools_deny_includes_add_resource_add_skill": true,

  // Gateway readiness evidence (codex: restart can race)
  "gateway_pid_after_restart": 12345,
  "gateway_health_ok": true,

  // Pre-run + post-run write evidence
  "openviking_pre_run_empty_scope_verified": true,
  "openviking_pre_run_empty_scope_failures": [],
  "openviking_session_exists_per_sample": true,
  "openviking_positive_recall_per_sample": true,
  "openviking_isolation_verified": true,
  "openviking_isolation_failures": [],

  // Runtime evidence: either form satisfies (codex: hooks vs tool calls)
  "openviking_runtime_evidence_tool_calls_total": 0,
  "openviking_runtime_evidence_lifecycle_hooks_total": 0,
  "openviking_runtime_evidence_verified": true,
  "openviking_runtime_evidence_failures": [],

  "memory_core_runtime_evidence_verified": true | null,
  "memory_core_runtime_evidence_failures": [] | null,

  "dataset_cases_after_filter": 1540,
  "dataset_filtered_hash": "<sha256 of filtered question list>",

  "published_reference": {
    "source_url": "https://github.com/volcengine/OpenViking#locomo",
    "row": "OpenClaw + OpenViking Plugin (-memory-core)" | "(+memory-core)",
    "published_completion_rate": 0.5208 | 0.5123,
    "published_input_tokens": 4264396 | 2099622,
    "openviking_version_published": "0.1.18",
    "answer_model_published": "seed-2.0-code",
    "judge_model_published": null
  },

  "observed": {
    "completion_rate": "<from judge_grades.score>",
    "qa_input_tokens": "<from qa_summary.usage.input_tokens>",
    "ingest_input_tokens": "<from ingest_summary.usage.input_tokens>",
    "total_input_tokens": "<sum of the above>",
    "input_tokens_accounting_source": "openclaw_qa_summary+ingest_summary",
    "delta_completion_rate_pct_points": "<observed*100 - published*100>",
    "delta_input_tokens_pct": "<(observed - published) / published>"
  }
}
```

---

## Worktree parallelization

Three independent workstreams in Phase 1+2; Phase 3 is serial.

| Lane | Steps | Modules |
|---|---|---|
| A | 1.1–1.2 | `lib/openclaw_plugin.py` + tests |
| B | 2.1–2.2 | `lib/openclaw_profile.py` + tests |
| C | 3.1–3.2 | `lib/openviking_verify.py` + tests |

Launch A, B, C in parallel worktrees. Phase 2 step 4 merges A+B+C into `lib/backends.py`, then Phase 2 step 5 extends `main.py`, then Phase 3 wires it. No conflict flags — each lane owns its own module.

---

## Runbook

### One-time host setup

```bash
# Build (or install) the OV plugin
cd ~/.openclaw/extensions/openviking && npm install && npx tsc -p tsconfig.build.json
# OR
openclaw plugins install @openviking/openclaw-plugin

# Verify dist exists
openclaw plugins list 2>&1 | grep -iE "warning|openviking" || echo "no warnings — OK"

# Pre-flight against eval profile
PYTHONPATH=. uv run python -c "
from lib.openclaw_plugin import assert_openviking_plugin_loaded, assert_answer_model_available
print(assert_openviking_plugin_loaded('eval'))
print(assert_answer_model_available('eval', 'seed-2.0-code'))
"
```

### Smoke (Phase 4 step 7.3) — uses `eval` mode end-to-end

Codex flagged that an `ingest`-only smoke does not exercise the new backend path, the per-row matrix, the publishability gate, or the snapshot-restore mechanism. The smoke must use `main.py eval` against a one-sample dataset so every gate fires once.

```bash
export OPENVIKING_API_KEY=${OPENVIKING_API_KEY:-}
PYTHONPATH=. uv run python main.py eval ./locomo10_small.json \
    --run-group output/runs/ov-plugin-smoke-$(date +%Y%m%d-%H%M%S) \
    --backends oc-ov-plugin-bare \
    --row-agent oc-ov-plugin-bare=eval-locomo-ov-smoke-bare \
    --agent-workspace ~/.openclaw-eval/workspace-ov-smoke \
    --sample 0 --include-categories 1 --count 1 \
    --openviking-server-base-url http://127.0.0.1:1933 \
    --openviking-agent-prefix eval-locomo-ov \
    --answer-model seed-2.0-code \
    --judge-model deepseek-v4-flash \
    --judge-base-url https://api.deepseek.com/v1 \
    --judge-token $DEEPSEEK_API_KEY
```

After smoke, run smoke step 7.4 against `oc-ov-plugin-augmented` with the unverified-hybrid flag to gather evidence for O2/O4 — the output is read-only diagnostic, not publishable.

### Full directional rerun (Phase 4 step 8.1)

This plan's first publishable row is `oc-ov-plugin-bare`. `oc-ov-plugin-augmented` runs only as diagnostic until O4 resolves.

```bash
PYTHONPATH=. uv run python main.py eval ./locomo10.json \
    --run-group output/runs/ov-plugin-directional-rerun-$(date +%Y%m%d-%H%M%S) \
    --backends oc-ov-plugin-bare \
    --row-agent oc-ov-plugin-bare=eval-locomo-ov-bare-$(date +%Y%m%d) \
    --agent-workspace ~/.openclaw-eval/workspace-ov-bare-$(date +%Y%m%d) \
    --openviking-server-base-url http://127.0.0.1:1933 \
    --openviking-agent-prefix eval-locomo-ov \
    --answer-model seed-2.0-code \
    --include-categories 1,2,3,4 \
    --judge-model deepseek-v4-flash \
    --judge-base-url https://api.deepseek.com/v1 \
    --judge-token $DEEPSEEK_API_KEY \
    --canary
```

Per codex: `--row-agent <row_id>=<agent_name>` is a new explicit mapping flag (Phase 2 step 6.3 also adds it). It replaces the historical hack of repurposing `--builtin-agent` for whichever row was running. The mapping is recorded in the manifest so the row-to-agent binding is auditable.

**Stretch (Phase 4 step 8.3):** install OV `0.1.18` side-by-side at `~/.openviking-pinned-0.1.18/` and rerun `oc-ov-plugin-bare` against it. If successful, the manifest's `openviking_server_version_matches_published` flips to `true` and `comparison_class` upgrades from `directional_rerun` toward `exact_reproduction` (still pending judge-model match and answer-model match).

---

## Replacement and cleanup

After the first publishable run with both new rows lands a journal entry:

1. Remove the retrieval-only `OpenVikingBackend` class, its registry entry `openviking`, its `--viking` flag, the `_call_ingest`/`_call_answer` viking branches, and `tests/test_*` cases that exercise it. Single-purpose PR.
2. Remove `openviking` from any default backend list it appears in (currently only `DEFAULT_EVAL_BACKENDS`).
3. Update `docs/design/openclaw-serious-memory-eval-plan.md` to point at this plan for the OV story.

This removal is **not** in scope for this PR. It needs evidence (a green journal entry) before deletion.

---

## Open Questions

Codex flagged that several of these directly affect row identity (not just smoke convenience). Reclassified accordingly. Each one has either a smoke-time resolution path or a blocking-question gate.

- **O1 (resolved by smoke).** `openclaw plugins doctor --json` does **not** exist on 2026.5.7 — smoke confirmed `error: unknown option '--json'`. Pre-flight uses text output of `openclaw plugins list 2>&1` and greps for `requires compiled runtime output`. `openclaw plugins doctor` on its own returns `"No plugin issues detected"` even when warnings exist — do not rely on it.

- **O2 (DESIGN BLOCKER — must resolve before Phase 2).** When both memory-core and OV plugin are enabled (the `+memory-core` row), does the model see one `memory_search` or two? If two, the allowlist is ambiguous (codex). Resolution path: in smoke step 7.4, enable both, run one QA, parse the agent transcript for `memory_search` tool calls AND record `details.providerId`/`registeringPluginId`/equivalent. If only one provider's `memory_search` ever fires, the matrix can stand. If both fire (or provenance is unrecoverable), `oc-ov-plugin-augmented` stays behind `--allow-unverified-hybrid-row` (already in NOT-in-scope item 10).

- **O3 (DESIGN BLOCKER — must resolve before Phase 4).** Is `seed-2.0-code` actually reachable via the local OC gateway? Smoke confirmed byteplus provider plugin is **bundled but disabled**. Resolution path: `openclaw --profile eval plugins enable byteplus && openclaw --profile eval gateway restart`, then one no-op `/v1/responses` call with `model=seed-2.0-code`. If rejected, the row is `comparison_class="approximation"` unless the user provides an alternative.

- **O4 (NEW; raised by codex).** What was the *exact* tool surface of the published "+memory-core" row? The published README does not enumerate it. Without that, our `oc-ov-plugin-augmented` allowlist is a guess that could produce a hybrid row. Resolution paths (in order of preference): (a) inspect the OV plugin's own integration tests or example configs in `~/.openclaw/extensions/openviking/__tests__/` for the assumed combined surface; (b) ask volcengine maintainers; (c) hold the augmented row behind the unverified-hybrid flag until evidence appears.

- **O5 (NEW; raised by codex; moved out of NOT-in-scope).** OV server `0.1.18` vs `0.3.17`. Codex called the prior "deferred to follow-up" framing the biggest reproducibility miss. New stance: **try to install 0.1.18 in a side-by-side directory under `~/.openviking-pinned-0.1.18/` and run the bare row against it** as a stretch task in Phase 4 step 8.3. If 0.1.18 isn't available or won't boot, the journal records the failure and the `directional_rerun` class stands. This is the strongest single move toward exact reproduction.

---

## Completion Summary (filled at review time)

- Step 0: Scope Challenge — scope accepted (two new rows reproducing the published OV plugin comparison; LanceDB and OC-baseline rows are out of scope; retrieval-only OV is replaced post-publishable).
- Architecture Review: 1 surfaced flag (11 files, 6 new / 5 extended) with written justification. No STOP required.
- Code Quality Review: deferred to implementation PR.
- Test Review: 24 unit-test gaps + 4 smoke/E2E gaps identified; all listed in Phase 1–3 tasks.
- Performance Review: no hotspots introduced; the per-row gateway restart adds ~5s per backend (acceptable for batch eval).
- NOT in scope: 9 items.
- What already exists: 12-row reuse map.
- Failure modes: 9 codepaths analyzed, 0 critical gaps.
- Outside voice: ran in parallel with smoke (see GSTACK REVIEW REPORT below).
- Parallelization: 3 parallel lanes in Phase 1, sequential Phase 2 + 3 + 4.
- Lake Score: 1/1 chose complete (strict publishable, both rows in one PR).

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | Scope set by user; goal reclassified from "exact reproduction" to "directional rerun" after codex review. |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | DONE | 24 findings surfaced; 16 folded into the plan above; 5 deferred to follow-up; 3 declined (see "Outside voice integration log" below). |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | DRAFT (PLAN, self-authored) | Scope accepted; 1 file-count flag with justification; 0 critical failure-mode gaps; 24 unit + 4 E2E test gaps to be closed by Phase 1–3 tasks. |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a — backend-only change. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | Optional follow-up. |

**UNRESOLVED design blockers:** O2 (memory_search namespace collision) and O4 (published `+memory-core` tool surface) must resolve before `oc-ov-plugin-augmented` ships publishable. `oc-ov-plugin-bare` is unblocked.

**VERDICT:** PLAN DRAFTED + SMOKE-PROBED + CODEX-REVIEWED + REVISED. Ready for human review and Phase 1 implementation of `oc-ov-plugin-bare`; `oc-ov-plugin-augmented` work is held behind O2/O4.

---

## Smoke Probe Findings (Phase 0 — host probe, no data writes)

Probe ran 2026-05-20T01:45Z on this host. Read-only enumeration; no data writes or deletes.

- **A. OV plugin dist:** **FAIL** — `~/.openclaw/extensions/openviking/dist/` does not exist. Package version is `@openclaw/openviking@2026.4.33` (note: this contradicts the upstream README's `openclaw plugins install @openviking/openclaw-plugin` instruction — the actual local package name is `@openclaw/openviking`. Codex flagged the mismatch; smoke confirms the local name is canonical for this host. **The plan's runbook uses the local name.**). Pre-flight gate will block until built.
- **B. `openclaw plugins doctor --json`:** **does not exist** (`error: unknown option '--json'`). `openclaw plugins doctor` returns `"No plugin issues detected"` even with the dist-missing warnings present. **Pre-flight cannot rely on `doctor`; must parse `openclaw plugins list 2>&1` for the warning strings.** Resolves O1.
- **B. `openclaw plugins inspect openviking`:** returns `"Plugin not found: openviking"`. The plugin is declared in `plugins.entries.openviking` but the loader skips it because dist is missing. Strongly reinforces A.
- **C. eval profile matrix keys:**
  - `plugins.slots.contextEngine` → `Config path not found` (must be created, not just updated)
  - `plugins.entries.openviking.enabled` → `Config path not found`
  - `plugins.entries.openviking.config` → `Config path not found`
  - `plugins.entries.memory-core.enabled` → `true`
  - `memory.backend` → `"builtin"`
  - `tools.allow` → exactly `["memory_search","memory_get","write","edit"]` (matches harness's STRICT_MEMORY_TOOLS)
  - `tools.deny` → starts with `["exec","process","read","apply_patch","image",…]`
  - `tools.elevated.enabled` → `false`
  - **Implication for Phase 2 step 6.1**: `openclaw config set` must support creating nested keys that don't yet exist. Verify in unit tests.
- **D. `openclaw providers list`:** **does not exist** as a subcommand (smoke output: `[openclaw] Failed to start CLI: Error: Unknown command: openclaw providers`). Provider plugins are listed via `openclaw plugins list` / `openclaw plugins inspect <name>`. The plan's pre-flight uses `openclaw plugins inspect byteplus --json` (or text fallback) instead.
- **D. byteplus provider plugin:** present but **`Status: disabled`**. seed-2.0-code is a ByteDance/Volcengine model — almost certainly served via byteplus. **Phase 4 step 7.2 must enable byteplus** before answer-model pre-flight: `openclaw --profile eval plugins enable byteplus && openclaw --profile eval gateway restart`. Resolves first half of O3; second half (model entitlement) still needs a no-op `/v1/responses` smoke call.
- **E. OV server reachability:** **PASS** — `http://127.0.0.1:1933/health` returns `{status:"ok",healthy:true,version:"0.3.17",auth_mode:"dev"}`. CLI 0.3.17 matches server.
- **F. existing `eval-locomo*` agents:** **145 already present** from historical runs. Per data-safety policy and `_workspace_has_memory` warnings, the directional rerun MUST use a fresh base-agent name (e.g. dated suffix `eval-locomo-ov-bare-20260520`). The runbook above already uses `$(date +%Y%m%d)` for this reason.
- **G. OV scope formula:** verified — `agent_prefix + "_" + ctx.agentId` produces unique strings per sample (`eval-locomo-ov_eval-locomo-conv-N`). Still requires pre-run empty-scope assertion (Phase 3 step 6.1) to handle stale OV server state on top of fresh OC agents.
- **H. risks surfaced:** dist missing (blocker), contextEngine slot unbound on eval profile (expected, fixed in 7.2), byteplus disabled (must enable in 7.2 pre-7.3 smoke).

---

## Outside Voice — Codex Findings Integration Log

Codex (gpt-5.5, model_reasoning_effort=high, read-only sandbox, 26,905 tokens used) returned 24 findings. Status:

**Folded into the plan above (16):**

1. Reclassify "reproduce" → "directional rerun" with explicit comparison-class field. ✅ Goal section.
2. `memory_search` namespace collision when both memory-core and OV plugin enabled — add provenance evidence + drop `augmented` row to behind unverified-hybrid flag until resolved. ✅ Strict-isolation matrix.
3. `oc-ov-plugin-augmented` tool surface may not match published `+memory-core` row — held behind flag pending O4. ✅ NOT-in-scope item 10.
4. OV plugin formula isolation claim needs **pre-run empty-scope assertion**, not only post-ingest probes. ✅ Phase 3 step 6.1.
5. Phase 3 mutating shared eval profile is fragile under concurrent runs — add file lock and gateway PID/readiness check. ✅ Phase 3 step 6.1.
6. Manifest version trust — record `openclaw_ov_plugin_source_commit`, `openclaw_ov_plugin_dist_sha256`, `openclaw_ov_plugin_build_provenance` instead of trusting package.json version alone. ✅ Manifest contract.
7. Package-name mismatch (`@openviking/openclaw-plugin` from README vs `@openclaw/openviking` locally) — smoke confirmed local name is canonical for this host; runbook uses local name. ✅ Smoke + Runbook.
8. Input tokens accounting ambiguity — record source explicitly (`input_tokens_accounting_source`), add ingest tokens, note exact equivalence not asserted. ✅ Manifest + Hard Reproduction Constraints.
9. OV plugin context-engine may not surface model-visible tool calls — runtime evidence accepts **either** tool calls OR lifecycle hooks. ✅ Phase 3 step 6.1.
10. `ov session list ≥ 1` proves existence not memory quality — add positive-recall probe (`probe_positive_recall`). ✅ Phase 3 step 6.1.
11. Judge-model attribution — record judge model, recommend κ between two judges in journal. ✅ Hard Reproduction Constraints.
12. Reclassify O1/O2/O3 as design blockers where appropriate; add O4 (combined tool surface) and O5 (OV 0.1.18 pinning, formerly NOT-in-scope). ✅ Open Questions.
13. GSTACK REVIEW REPORT internal inconsistency (verdict "CODEX-REVIEWED" while status "PENDING"). ✅ Fixed.
14. Smoke command used `ingest` mode — does not validate new backend path, matrix, gates. Replaced with `eval`-mode smoke. ✅ Runbook.
15. `--builtin-agent` naming hack — replaced with explicit `--row-agent <row_id>=<agent_name>` mapping. ✅ Phase 2 step 6.3 + Runbook.
16. OV 0.1.18 pinning moved out of NOT-in-scope into Open Question O5 with explicit stretch-task gate (Phase 4 step 8.3). ✅ Open Questions.

**Deferred to follow-up (5):**

17. "Replace retrieval-only `OpenVikingBackend` after first publishable run" — codex said deletion shouldn't be coupled to score success. Plan now keeps retrieval-only as-is and decouples deletion entirely (separate PR, no score dependency). Codex point accepted; cleanup item kept out of this plan.
18. "11 files isn't thin; do 1 row manually first, automate later" — partially accepted via the `oc-ov-plugin-augmented` flag-gated state, but the bare row still ships with full automation. The pure 1-row-manual-first option would be a different plan; not adopting.
19. Worktree parallelization is "fake safety" — codex is right that semantic integration is the expensive risk. Plan still lists parallel lanes because module ownership is real even if integration is the harder part; added one sentence to soften the claim. (Acknowledged but not heavily rewritten.)
20. `npm install && npx tsc` is "unpinned build" — addressed partially by recording `dist_sha256` and `source_commit` in the manifest. A pinned `package-lock.json` pull or vendored tarball is left for the build-discipline follow-up.
21. Re-judge with second model for κ — recommended in journal, not enforced in code. Could become a Phase 4 sub-step; held back to avoid scope creep.

**Declined (3):**

22. "OV server delta is the single biggest reproducibility miss; should be first-class, not follow-up." — partially accepted (O5 is now a stretch task in Phase 4 step 8.3); not promoted further because installing OV 0.1.18 may be infeasible on this host (binary availability uncertain). Stretch is the right shape.
23. "Restore-on-exit is overclaimed — restart failures can cascade." — codex is right in principle, but the file lock plus PID-readiness check covers the realistic failure window. Further hardening (e.g. atomic config writes, gateway pinning) is over-engineering for the current bar.
24. "Smoke run summary appended findings are referenced but absent here." — codex saw the original draft; this revision adds both the smoke and codex-findings sections that codex correctly noted were missing. (Closed.)

The full raw codex transcript is preserved at `/tmp/codex-ov-plan-ZkT7ID.err` (this host, ephemeral). For the journal entry, the relevant verbatim findings have been quoted inline above.
