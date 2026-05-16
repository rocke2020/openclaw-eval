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

Do not delete existing eval memory or session files to prepare a run. Use a fresh agent and workspace for each primary backend run, for example:

```text
agent:     eval-locomo-builtin-full
workspace: ~/.openclaw-eval/workspace-locomo-builtin-full
```

This avoids contamination from smoke runs and preserves prior artifacts for audit.

The fresh agent must be configured in `~/.openclaw-eval/openclaw.json` before the run. After changing agent config, restart the eval gateway and verify the run uses the intended route. For builtin comparison runs, pass the same agent and workspace explicitly:

```bash
openclaw --profile eval agents add eval-locomo-builtin-full \
  --workspace ~/.openclaw-eval/workspace-locomo-builtin-full \
  --model deepseek/deepseek-v4-flash \
  --non-interactive

openclaw --profile eval gateway restart

openclaw --profile eval agents list --json
openclaw --profile eval skills check --agent eval-locomo-builtin-full --json
```

If `agents add` reports that the agent already exists, do not assume it is fresh. Verify the listed workspace path and inspect it for existing `MEMORY.md` or `memory/*.md`; choose a new agent/workspace name if prior memory exists.

Use the same agent and workspace in the eval command:

```bash
--builtin-agent eval-locomo-builtin-full
--agent-workspace ~/.openclaw-eval/workspace-locomo-builtin-full
```

After ingest starts, confirm `manifest.json` records the same `openclaw_agent`, and `backend_config.agent` matches the intended builtin agent.

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
openclaw --profile eval config get tools.allow --json
openclaw --profile eval config get tools.deny --json
```

`modelVisible` and `commandVisible` must both be empty. `eligible` may still list installed skills whose requirements are present; that is acceptable only when those skills appear under `agentFiltered` and are not model-visible or command-visible.

The eval profile must expose the minimal durable-memory tool surface:
`memory_search`, `memory_get`, `write`, and `edit`. OpenClaw 2026.5.7 writes builtin memory through the normal file write/edit tools under the isolated agent workspace; if `write` and `edit` are denied, ingest can only read/search memory and `memory_write_verification` will fail for every sample. Keep broad read/exec/process/session/browser/network tools denied.

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

If the local environment has SOCKS proxy variables and `judge.py` fails with a missing `socksio` error, clear proxy variables for the judge process:

```bash
env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
  PYTHONPATH=. uv run python judge.py ...
```

## Run Order

1. Verify clean git state.
2. Create or select a fresh agent/workspace for the backend.
3. Verify skills are not visible to the eval agent.
4. Restart the eval gateway after config changes.
5. Run ingest and QA into a new `output/runs/<run-group>/<backend-id>/` directory.
6. For multi-sample final runs, either enable contamination canaries with `--canary` or record that canaries were intentionally skipped.
7. Run the judge against `answers.json`.
8. Report only metrics traceable to artifacts.

Builtin full-run command shape:

```bash
RUN_GROUP="output/runs/builtin-memory-full-$(date +%Y%m%d-%H%M%S)"

OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" PYTHONPATH=. uv run eval.py compare locomo10.json \
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
  PYTHONPATH=. uv run python judge.py "$RUN_GROUP/oo-builtin/answers.json" \
  --output "$RUN_GROUP/oo-builtin/judge_grades.json" \
  --base-url https://api.deepseek.com/v1 \
  --token "$DEEPSEEK_API_KEY" \
  --model deepseek-v4-flash \
  --parallel 4
```

Use a sampled scope first when validating pipeline changes; use all of `locomo10.json` only for final rows.

Easy-to-confuse flags:

- `--openclaw-home` must point at `~/.openclaw-eval`; otherwise session reset looks in the default OpenClaw profile.
- `--agent-workspace` must be the same workspace configured for `--builtin-agent`; otherwise memory-write verification checks the wrong files.
- `--judge-model` and the later `judge.py --model` must match; the manifest records the former, while `judge_grades.json` is produced by the latter.
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
- `openclaw_agent` and `backend_config.agent` match the intended fresh agent
- `memory_write_verification` is `configured`
- every selected sample has `write_detected=true`
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
