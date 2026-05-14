# Full Eval Run Principles

Use this checklist before running any result intended for the final comparison table.

## Scope

A full eval run must declare its dataset scope before execution. Examples:

- `locomo10_small.json`
- `locomo10.json --sample 0 --sessions 1-4`
- all of `locomo10.json`

Do not imply that a sampled run represents all LoCoMo10.

## Clean Code State

Start from a clean git worktree. Commit or stash documentation and code changes before running, so `manifest.json` records `eval_repo_dirty: false`.

Verify:

```bash
git status --short
```

The command must print nothing for a final benchmark row.

## Isolated Runtime State

Do not delete existing eval memory or session files to prepare a run. The only publishable OpenClaw isolation mode is per-sample: pass a base agent and base workspace, and let the harness provision one effective agent/workspace per selected LoCoMo sample.

```text
base agent:     eval-locomo-builtin-full
base workspace: ~/.openclaw-eval/workspace-locomo-builtin-full
sample agent:   eval-locomo-builtin-full-conv-26
sample workspace: ~/.openclaw-eval/workspace-locomo-builtin-full-conv-26
```

This avoids cross-sample contamination and preserves prior artifacts for audit.

The base agent can be configured in `~/.openclaw-eval/openclaw.json` before the run, but final publishability depends on the derived per-sample agents. When `--agent-workspace` is present, the harness creates missing sample agents as `<base-agent>-<sample_id>` with workspaces derived as `<base-workspace>-<sample_id>`, then restarts the gateway after batch provisioning. For builtin comparison runs, pass the base agent and base workspace explicitly:

```bash
openclaw --profile eval agents add eval-locomo-builtin-full \
  --workspace ~/.openclaw-eval/workspace-locomo-builtin-full \
  --model deepseek/deepseek-v4-flash \
  --non-interactive

openclaw --profile eval gateway restart

openclaw --profile eval agents list --json
openclaw --profile eval skills check --agent eval-locomo-builtin-full --json
```

If `agents add` reports that the base agent or any derived sample agent already exists, do not assume it is fresh. Verify the listed workspace path and inspect the derived sample workspaces for existing `MEMORY.md` or `memory/*.md`; choose a new base agent/workspace name if prior memory exists.

Use the base agent and base workspace in the eval command:

```bash
--builtin-agent eval-locomo-builtin-full
--agent-workspace ~/.openclaw-eval/workspace-locomo-builtin-full
```

After ingest starts, confirm `manifest.json` records the base `openclaw_agent`, `backend_config.agent` matches the intended backend base agent, and `memory_write_verification.json.samples[*]` contains one entry per selected sample.

Do not pass `--user` for primary multi-sample runs. The harness defaults to one user key per LoCoMo sample; overriding `--user` collapses samples into one memory namespace and invalidates isolation.

## Skill Isolation

Benchmark agents must expose no optional skills during ingest or QA.

Disable skills at the eval-profile default level before final runs:

```bash
openclaw --profile eval config set agents.defaults.skills '[]' --strict-json
openclaw --profile eval gateway restart
```

If an eval agent has an explicit per-agent skill allowlist, set that allowlist to `[]` too. The effective check is what matters: no skills can be visible to the model or command menu.

Verify:

```bash
openclaw --profile eval skills check --agent <agent-id> --json
```

`modelVisible` and `commandVisible` must both be empty. `eligible` may still list installed skills whose requirements are present; that is acceptable only when those skills appear under `agentFiltered` and are not model-visible or command-visible.

## Gateway And Backend

Use the eval profile, not the default OpenClaw profile:

```text
base URL: http://127.0.0.1:19002
profile:  eval
```

For builtin memory, verify `memory-core` is enabled and selected as the memory slot before running.

```bash
openclaw --profile eval config get gateway.port
openclaw --profile eval config get plugins
openclaw --profile eval config get agents.defaults.memorySearch
openclaw --profile eval config get agents.defaults.startupContext
openclaw --profile eval config get agents.defaults.model
```

Also verify builtin-memory invariants:

- `gateway.port=19002`
- `plugins.slots.memory="memory-core"`
- `plugins.entries.memory-core.enabled=true`
- `agents.defaults.startupContext.enabled=false`
- `agents.defaults.memorySearch.sources=["memory"]`
- `agents.defaults.memorySearch.extraPaths=[]`
- `agents.defaults.memorySearch.experimental.sessionMemory=false`
- `agents.defaults.memorySearch.sync.onSessionStart=false`
- `agents.defaults.memorySearch.sync.watch=false`

The current eval profile uses `deepseek/deepseek-v4-flash` as the primary and fallback model. Treat this as the default thinking model for OpenClaw eval turns unless the run manifest explicitly records a different model.

## Auth And Tokens

Export the eval gateway token from the eval profile before running the harness:

```bash
export OPENCLAW_GATEWAY_TOKEN="$(jq -r '.gateway.auth.token' ~/.openclaw-eval/openclaw.json)"
```

For DeepSeek judge runs, verify the judge key is present:

```bash
test -n "$DEEPSEEK_API_KEY" && echo "DEEPSEEK_API_KEY=set"
```

If the local environment has SOCKS proxy variables and the judge subcommand fails with a missing `socksio` error, clear proxy variables for the judge process:

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
  PYTHONPATH=. uv run python main.py judge ...
```

## Run Order

1. Verify clean git state.
2. Create or select a fresh base agent/workspace for the backend; per-sample agents/workspaces are derived from that base.
3. Verify skills are not visible to the base eval agent and any effective per-sample agents used by the run.
4. Restart the eval gateway after config changes.
5. Run ingest and QA into a new `output/runs/<run-group>/<backend-id>/` directory.
6. For multi-sample final runs, either enable contamination canaries with `--canary` or record that canaries were intentionally skipped.
7. Run the judge against `answers.json`.
8. Report only metrics traceable to artifacts.

Builtin full-run command shape:

```bash
RUN_GROUP="output/runs/builtin-memory-full-$(date +%Y%m%d-%H%M%S)"

OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" PYTHONPATH=. uv run python main.py eval locomo10.json \
  --run-group "$RUN_GROUP" \
  --backends oo-builtin \
  --builtin-agent eval-locomo-builtin-full \
  --base-url http://127.0.0.1:19002 \
  --openclaw-home ~/.openclaw-eval \
  --openclaw-profile eval \
  --agent-workspace ~/.openclaw-eval/workspace-locomo-builtin-full \
  --include-categories 1,2,3,4,5 \
  --judge-model deepseek-v4-flash \
  --judge-base-url https://api.deepseek.com/v1 \
  --canary

env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
  PYTHONPATH=. uv run python main.py judge "$RUN_GROUP/oo-builtin/answers.json" \
  --output "$RUN_GROUP/oo-builtin/judge_grades.json" \
  --base-url https://api.deepseek.com/v1 \
  --token "$DEEPSEEK_API_KEY" \
  --model deepseek-v4-flash \
  --parallel 4
```

Use a sampled scope first when validating pipeline changes; use all of `locomo10.json` only for final rows.

Easy-to-confuse flags:

- `--openclaw-home` must point at `~/.openclaw-eval`; otherwise session reset looks in the default OpenClaw profile.
- `--agent-workspace` is the required base workspace for per-sample OpenClaw isolation. The harness derives sample workspaces from it; without this flag memory-write verification is `not_configured` and the run is non-publishable.
- `--judge-model` and any later `main.py judge --model` rerun must match; the manifest records the former, while `judge_grades.json` is produced by the latter.
- Do not use `--allow-non-publishable` for final rows. It is acceptable only while debugging setup failures.

## Post-Run Checks

Run these checks before accepting a result:

```bash
jq '{backend_id, openclaw_agent, openclaw_profile, openclaw_model, judge_model, dataset_sample_count, dataset_session_count, dataset_qa_count_selected, eval_repo_dirty, category_policy, memory_write_verification}' "$RUN_GROUP/oo-builtin/manifest.json"
jq '{agent:.backend_config.agent, expected_memory_backend:.backend_config.expected_memory_backend}' "$RUN_GROUP/oo-builtin/manifest.json"
jq '{samples:.samples}' "$RUN_GROUP/oo-builtin/memory_write_verification.json"
jq '{total:.total, usage:.usage}' "$RUN_GROUP/oo-builtin/ingest_summary.json"
jq '{total:.total, usage:.usage}' "$RUN_GROUP/oo-builtin/qa_summary.json"
jq '{correct, total, score, per_category}' "$RUN_GROUP/oo-builtin/judge_grades.json"
jq '.results | length' "$RUN_GROUP/oo-builtin/answers.json"
```

Accept the run only if:

- `eval_repo_dirty=false`
- `openclaw_agent` and `backend_config.agent` match the intended backend base agent
- `memory_write_verification` is `configured`
- every selected sample has a per-sample verification entry with `write_detected=true`
- `dataset_qa_count_selected` matches the declared scope
- `judge_grades.json.total` matches `answers.json.summary.total`
- `judge_grades.json.grades | length` matches `answers.json.results | length`

## Reporting Rules

The final table must use artifact-backed values only:

- task completion rate from `judge_grades.json`
- input-token cost from `ingest_summary.json.usage.input_tokens + qa_summary.json.usage.input_tokens`
- dataset/backend scope from `manifest.json`
- answer LM from `manifest.json.openclaw_model` and the eval profile model config
- judge LM from `manifest.json.judge_model` and `judge_grades.json`
- memory-write evidence from `memory_write_verification.json`

Every final table or report must name the answer model and judge model alongside the score. The current eval answer model is `deepseek/deepseek-v4-flash` in thinking mode unless the run manifest proves otherwise.

Do not use `comparison_summary.json` or `comparison_report.html` for final scores unless they were regenerated after judging. The current compare flow writes placeholder `judge_score: 0.0` before the separate judge step.

Smoke runs may validate the pipeline, but they are not final benchmark rows.
