# OpenClaw Serious Memory Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn this repo into a publishable, stricter, reproducible memory benchmark harness for LoCoMo-style "memory write + retrieval + answer" evaluation, with OpenClaw built-in memory as the baseline and comparable QMD/OpenViking runs.

**Architecture:** Keep the existing LoCoMo ingest and QA shape, but make every hidden assumption explicit: target backend, target agent, user key, dataset fingerprint, category filter, memory write verification, run manifest, and scoring output. The harness should support a dedicated eval agent in a normal gateway for daily runs, a dedicated OpenClaw profile/gateway for publishable OpenClaw runs, and an OpenViking adapter that can be scored under the same artifact contract.

**Tech Stack:** Python 3.13, `unittest`, OpenClaw `/v1/responses`, OpenViking CLI, LoCoMo JSON, JSONL/JSON artifacts, optional HTML report.

---

## Current Diagnosis

This repo already evaluates the intended end-to-end chain:

```text
LoCoMo session text
  -> OpenClaw normal agent run
  -> agent decides what to write into memory
  -> later QA question
  -> OpenClaw retrieves memory and answers
  -> judge scores answer
```

The current implementation is not yet strict enough for publishable numbers:

- `eval.py:407` silently excludes category `5`, so `locomo10.json` uses `1,540` QA pairs instead of all `1,986`.
- `eval.py:182-198` hardcodes session reset to `agent:main`, which breaks once we use a dedicated eval agent.
- `eval.py:505-511` writes only total usage to the main QA output path, while `judge.py` expects an aggregate answers JSON.
- Ingest asks OpenClaw to remember, but this repo does not verify that any memory file was written.
- The run has no manifest with dataset hash, OpenClaw version, eval commit, agent id, model, category policy, and config.
- The current default model payload is always `model: "openclaw"`, so agent routing can accidentally hit the default `main` agent.

## Evaluation Definition

The benchmark measures the full memory loop:

```text
memory write + retrieval + answer
```

It does not pre-load ground truth into memory. Ingest must send conversation sessions through the backend's normal write path, and QA must ask normal questions later through the backend's declared answer path. A run is publishable only if the harness records evidence that memory state changed during ingest and that QA used the intended isolated backend/agent/user route.

For the cross-backend benchmark, keep the same semantic definition:

```text
memory write + retrieval + answer
```

OpenClaw built-in and OpenClaw QMD should use the normal OpenClaw agent path for both ingest and QA. OpenViking must not be compared using ingest-only `ov add-memory`; it needs an answering path too. If OpenViking does not expose a stable chat/answer API, the reproducible adapter should use `ov search` for retrieval and a fixed answer model/prompt for final answers, and the manifest must mark that mode as `openviking-search-rag`.

## Backend Matrix

The primary comparison should run all three backends under one run group:

```text
output/runs/<group_id>/
  oo-builtin/
  oo-qmd/
  openviking/
  comparison_report.html
  comparison_summary.json
```

| Backend id | Purpose | Ingest path | QA path | Isolation |
|------------|---------|-------------|---------|-----------|
| `oo-builtin` | Baseline | OpenClaw `/v1/responses` with built-in memory backend | OpenClaw `/v1/responses` | dedicated `eval-locomo-builtin` agent/profile |
| `oo-qmd` | OpenClaw QMD memory comparison | OpenClaw `/v1/responses` with `memory.backend: "qmd"` | OpenClaw `/v1/responses` | dedicated `eval-locomo-qmd` agent/profile |
| `openviking` | External memory comparison | `ov add-memory` through an adapter | `ov search` plus fixed answer prompt, or stable OpenViking chat if available | dedicated OpenViking account/user/agent id |

Fairness rules:

- Use the same dataset file, sample set, session range, message formatter, category policy, and judge for every backend.
- Use the same final answer model where the backend design allows it. If one backend controls its answer model internally, record that explicitly in `manifest.json`.
- Keep OpenClaw built-in memory as the baseline row in every comparison report.
- Keep QMD baseline mode conservative: disable QMD session transcript indexing and extra paths unless the run is explicitly an ablation. Otherwise QMD may receive extra context that built-in memory does not receive.
- Do not mix backend runs in the same OpenClaw agent, OpenViking user, workspace, or memory directory.
- Report backend setup separately from score, because a higher score with a non-equivalent setup is not a clean memory-backend comparison.

## Isolation Model

### Tier 1: serious local eval

Use one dedicated agent in the existing gateway.

```text
gateway default profile
  agent main
    normal daily workspace and memory
  agent eval-locomo
    isolated workspace
    isolated MEMORY.md and memory/
    isolated sessions
    eval-only model/tool config
```

This is enough for daily development if the agent has no `memorySearch.extraPaths` pointing at normal memory and background memory jobs are disabled or scoped away from eval.

### Tier 2: publishable eval

Use a dedicated OpenClaw profile and gateway process.

```bash
OPENCLAW_PROFILE=locomo-eval openclaw gateway --port 18790
```

Then run this harness against:

```bash
--base-url http://127.0.0.1:18790
--agent eval-locomo
```

This is the recommended mode for numbers that will be compared publicly.

## Artifact Contract

Every benchmark run writes one directory:

```text
output/runs/<run_id>/
  manifest.json
  ingest.jsonl
  ingest_summary.json
  memory_write_verification.json
  qa.jsonl
  qa_summary.json
  answers.json
  judge_grades.json
  report.html
```

For comparison runs, each backend writes the same directory shape under `output/runs/<group_id>/<backend_id>/`. The group directory also writes:

```text
output/runs/<group_id>/
  comparison_summary.json
  comparison_report.html
```

`manifest.json` must include:

- `run_id`
- `run_group_id`
- `backend_id`
- `backend_kind`
- `backend_config`
- `created_at`
- `dataset_path`
- `dataset_sha256`
- `dataset_sample_count`
- `dataset_session_count`
- `dataset_qa_count_total`
- `dataset_qa_count_selected`
- `eval_repo_commit`
- `eval_repo_dirty`
- `openclaw_base_url`
- `openclaw_agent`
- `openclaw_model`
- `openclaw_profile`
- `openviking_account`
- `openviking_user`
- `openviking_agent_id`
- `user_policy`
- `category_policy`
- `tail`
- `session_range`
- `parallel`
- `memory_write_verification`
- `judge_model`
- `judge_base_url`

`answers.json` must be the stable input for `judge.py`.

`comparison_summary.json` must include per-backend:

- `backend_id`
- `publishable`
- `non_publishable_reasons`
- `qa_total`
- `judge_score`
- `per_category`
- `memory_write_verified`
- `canary_leakage_count`
- `total_ingest_tokens` when available
- `total_qa_tokens` when available

## Target CLI

Keep the two primary commands, but make strict mode explicit.

```bash
uv run python eval.py ingest ./locomo10.json \
  --agent eval-locomo \
  --run-dir output/runs/locomo-eval-001 \
  --agent-workspace ~/.openclaw/workspace-locomo-eval \
  --tail "[remember what's said, keep existing memory]"

uv run python eval.py qa ./locomo10.json \
  --agent eval-locomo \
  --run-dir output/runs/locomo-eval-001 \
  --include-categories 1,2,3,4,5

uv run python judge.py output/runs/locomo-eval-001/answers.json \
  --output output/runs/locomo-eval-001/judge_grades.json \
  --model gpt-4o-mini
```

For publishable runs:

```bash
OPENCLAW_PROFILE=locomo-eval openclaw gateway --port 18790

uv run python eval.py ingest ./locomo10.json \
  --base-url http://127.0.0.1:18790 \
  --agent eval-locomo \
  --run-dir output/runs/locomo-eval-001 \
  --agent-workspace ~/.openclaw/workspace-locomo-eval
```

For the three-backend comparison:

```bash
uv run python eval.py compare ./locomo10.json \
  --run-group output/runs/locomo-memory-comparison-001 \
  --backends oo-builtin,oo-qmd,openviking \
  --include-categories 1,2,3,4,5 \
  --judge-model gpt-4o-mini
```

The compare command should expand into three normal strict runs and then render the group-level comparison artifacts. It should fail fast if a requested backend cannot be configured, unless `--allow-non-publishable` is set.

## File Structure

The implementation should keep `eval.py` as the CLI entry point but split reusable logic into focused modules.

- Modify: `eval.py`
  - CLI parsing and high-level orchestration only.
- Create: `eval_openclaw.py`
  - `/v1/responses` client, agent routing, session lookup, session reset.
- Create: `eval_backends.py`
  - common backend interface, backend registry, comparison orchestration helpers.
- Create: `eval_openviking.py`
  - OpenViking ingest/search adapter and optional answer adapter.
- Create: `eval_locomo.py`
  - LoCoMo loading, message formatting, session building, QA filtering, dataset stats.
- Create: `eval_artifacts.py`
  - run directory creation, manifest, JSONL writers, aggregate answer output, HTML report.
- Create: `eval_memory_verify.py`
  - memory file snapshot and post-ingest verification.
- Modify: `judge.py`
  - stable input/output contract and summary JSON.
- Modify: `judge_util.py`
  - strict JSON judge response, bounded concurrency, retries, persisted reasoning.
- Modify: `README.md`
  - documented strict workflow, isolation modes, category policy, output files.
- Create or extend tests:
  - `tests/test_eval_openclaw.py`
  - `tests/test_eval_locomo.py`
  - `tests/test_eval_artifacts.py`
  - `tests/test_eval_memory_verify.py`
  - `tests/test_judge_util.py`

## Data Flow

```text
              +------------------+
              |  locomo10.json   |
              +---------+--------+
                        |
                        v
              +------------------+
              | eval_locomo.py   |
              | format sessions  |
              | select QA cats   |
              +---------+--------+
                        |
           ingest       |        qa
              v         |        v
   +----------------+   |   +----------------+
   | eval_openclaw  |   |   | eval_openclaw  |
   | /v1/responses  |   |   | /v1/responses  |
   +-------+--------+   |   +-------+--------+
           |            |           |
           v            |           v
   +----------------+   |   +----------------+
   | OpenClaw agent |   |   | OpenClaw agent |
   | writes memory  |   |   | recalls answer |
   +-------+--------+   |   +-------+--------+
           |            |           |
           v            |           v
   +----------------+   |   +----------------+
   | memory verify  |   |   | answers.json   |
   +----------------+   |   +-------+--------+
                                      |
                                      v
                              +---------------+
                              | judge.py      |
                              | grades/report |
                              +---------------+
```

Comparison data flow:

```text
                 +------------------+
                 |  locomo10.json   |
                 +---------+--------+
                           |
                           v
                 +------------------+
                 | shared LoCoMo    |
                 | formatter/QA set |
                 +---------+--------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   +-------------+  +-------------+  +-------------+
   | oo-builtin  |  |   oo-qmd    |  | openviking  |
   | strict run  |  | strict run  |  | strict run  |
   +------+------+  +------+------+  +------+------+
          |                |                |
          +----------------+----------------+
                           |
                           v
                 +------------------+
                 | same judge       |
                 | same reporting   |
                 +---------+--------+
                           |
                           v
                 +------------------+
                 | comparison HTML  |
                 +------------------+
```

## Task 1: Split LoCoMo Formatting And QA Selection

**Files:**
- Create: `eval_locomo.py`
- Modify: `eval.py`
- Test: `tests/test_eval_locomo.py`

- [ ] **Step 1: Move LoCoMo helpers into `eval_locomo.py`**

Move these functions without behavior changes first:

```python
def format_locomo_message(msg: dict) -> str: ...
def load_locomo_data(path: str, sample_index: int | None = None) -> list[dict]: ...
def default_sample_user(sample_id: str) -> str: ...
def build_session_messages(item: dict, session_range: tuple[int, int] | None = None, tail: str = "[]") -> list[dict]: ...
def parse_session_range(s: str) -> tuple[int, int]: ...
```

- [ ] **Step 2: Add explicit category selection**

Add this function:

```python
def select_qas(
    item: dict,
    include_categories: set[str] | None = None,
    exclude_categories: set[str] | None = None,
    count: int | None = None,
) -> list[dict]:
    qas = list(item.get("qa", []))
    if include_categories is not None:
        qas = [q for q in qas if str(q.get("category", "")) in include_categories]
    if exclude_categories is not None:
        qas = [q for q in qas if str(q.get("category", "")) not in exclude_categories]
    if count is not None:
        qas = qas[:count]
    return qas
```

- [ ] **Step 3: Write tests for category behavior**

Test cases:

```python
def test_select_qas_defaults_to_all_categories():
    sample = {"qa": [{"category": 1}, {"category": 5}]}
    assert len(select_qas(sample)) == 2

def test_select_qas_can_exclude_category_5_explicitly():
    sample = {"qa": [{"category": 1}, {"category": 5}]}
    assert select_qas(sample, exclude_categories={"5"}) == [{"category": 1}]

def test_select_qas_include_categories_wins_before_count():
    sample = {"qa": [{"category": 1}, {"category": 5}, {"category": 5}]}
    assert select_qas(sample, include_categories={"5"}, count=1) == [{"category": 5}]
```

- [ ] **Step 4: Update `run_sample_qa()`**

Replace the hardcoded category-5 exclusion with `select_qas(...)`.

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_locomo.py tests/test_eval_user_keys.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add eval.py eval_locomo.py tests/test_eval_locomo.py tests/test_eval_user_keys.py
git commit -m "refactor: isolate locomo dataset handling"
```

## Task 2: Add Agent-Aware OpenClaw Client

**Files:**
- Create: `eval_openclaw.py`
- Modify: `eval.py`
- Test: `tests/test_eval_openclaw.py`

- [ ] **Step 1: Move HTTP client code**

Move `extract_response_text()`, `send_message_with_retry()`, and `send_message()` into `eval_openclaw.py`.

- [ ] **Step 2: Add agent routing**

Change the client signature:

```python
def send_message(
    base_url: str,
    token: str,
    user: str,
    message: str,
    agent: str = "main",
) -> tuple[str, dict]:
    payload = {
        "model": f"openclaw/{agent}" if agent else "openclaw",
        "input": message,
        "stream": False,
    }
    if user:
        payload["user"] = user
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    resp = requests.post(f"{base_url}/v1/responses", json=payload, headers=headers, timeout=300)
    resp.raise_for_status()
    body = resp.json()
    usage = body.get("usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    return extract_response_text(body), usage
```

- [ ] **Step 3: Make session lookup agent-aware**

Add:

```python
def get_session_id(agent: str, user: str, openclaw_home: str | None = None) -> str | None:
    root = os.path.expanduser(openclaw_home or "~/.openclaw")
    sessions_file = os.path.join(root, "agents", agent, "sessions", "sessions.json")
    with open(sessions_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    key = f"agent:{agent}:openresponses-user:{user}"
    return data.get(key, {}).get("sessionId")
```

If the file does not exist or the key is absent, return `None` and print a warning.

- [ ] **Step 4: Make session reset agent-aware**

Add:

```python
def reset_session(agent: str, session_id: str, openclaw_home: str | None = None) -> bool:
    root = os.path.expanduser(openclaw_home or "~/.openclaw")
    src = os.path.join(root, "agents", agent, "sessions", f"{session_id}.jsonl")
    dst = f"{src}.{int(time.time())}"
    os.rename(src, dst)
    return True
```

Catch `FileNotFoundError` and return `False` with a warning. Do not delete files.

- [ ] **Step 5: Add CLI args**

Add:

```python
parser.add_argument("--agent", default="main", help="OpenClaw agent id to evaluate")
parser.add_argument("--openclaw-home", default=None, help="OpenClaw home directory for session lookup")
```

- [ ] **Step 6: Tests**

Test cases:

```python
def test_send_message_targets_named_agent():
    # patch requests.post and assert payload["model"] == "openclaw/eval-locomo"

def test_get_session_id_reads_named_agent_store(tmp_path):
    # create tmp/.openclaw/agents/eval-locomo/sessions/sessions.json
    # assert key agent:eval-locomo:openresponses-user:eval-conv-26 works

def test_reset_session_archives_named_agent_transcript(tmp_path):
    # create transcript and assert original path gone, archived path exists
```

- [ ] **Step 7: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_openclaw.py tests/test_eval_user_keys.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add eval.py eval_openclaw.py tests/test_eval_openclaw.py tests/test_eval_user_keys.py
git commit -m "feat: add agent-aware openclaw eval client"
```

## Task 2.5: Add Backend Abstraction And Comparison Matrix

**Files:**
- Create: `eval_backends.py`
- Modify: `eval.py`
- Test: `tests/test_eval_backends.py`

- [ ] **Step 1: Define backend interface**

Create a small protocol-style interface:

```python
class MemoryBackend(Protocol):
    backend_id: str
    backend_kind: str

    def ingest(self, user: str, message: str) -> tuple[str, dict]: ...
    def answer(self, user: str, question: str) -> tuple[str, dict]: ...
    def manifest_config(self) -> dict: ...
```

Keep it deliberately thin. The benchmark should own LoCoMo formatting, category selection, artifacts, and judging.

- [ ] **Step 2: Implement OpenClaw backend variants**

Add two configured OpenClaw variants:

```python
oo-builtin -> OpenClawBackend(agent="eval-locomo-builtin", expected_memory_backend="builtin")
oo-qmd     -> OpenClawBackend(agent="eval-locomo-qmd", expected_memory_backend="qmd")
```

The harness cannot fully prove OpenClaw's in-process backend from the Responses API alone, so it must record the declared backend config and fail publishability if the expected agent/profile config cannot be verified from local config files.

- [ ] **Step 3: Add compare command**

Add:

```bash
uv run python eval.py compare ./locomo10.json --run-group output/runs/<group> --backends oo-builtin,oo-qmd,openviking
```

The command should create one strict run directory per backend and then render group-level summary/report artifacts.

- [ ] **Step 4: Tests**

Test cases:

```python
def test_backend_registry_requires_known_backend():
    # unknown backend raises a clear ValueError

def test_compare_run_paths_are_backend_scoped():
    # group/foo and group/bar are separate directories

def test_openclaw_backend_manifest_records_expected_backend():
    # manifest_config includes backend_id and expected_memory_backend
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_backends.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add eval.py eval_backends.py tests/test_eval_backends.py
git commit -m "feat: add memory backend comparison harness"
```

## Task 3: Add Run Directory And Manifest

**Files:**
- Create: `eval_artifacts.py`
- Modify: `eval.py`
- Test: `tests/test_eval_artifacts.py`

- [ ] **Step 1: Add run directory helper**

Create:

```python
def ensure_run_dir(path: str) -> Path:
    run_dir = Path(path)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
```

- [ ] **Step 2: Add dataset hash**

Create:

```python
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 3: Add manifest writer**

Create:

```python
def write_manifest(path: Path, manifest: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=True)
```

- [ ] **Step 4: Add CLI arg**

Add:

```python
parser.add_argument("--run-dir", default=None, help="Directory for reproducible eval artifacts")
```

If `--run-dir` is present, write all strict artifacts there. Keep `--output` for backward compatibility.

- [ ] **Step 5: Manifest fields**

Populate at minimum:

```python
{
    "run_id": run_dir.name,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "dataset_path": args.input,
    "dataset_sha256": sha256_file(args.input),
    "openclaw_base_url": args.base_url,
    "openclaw_agent": args.agent,
    "tail": args.tail,
    "sample": args.sample,
    "sessions": args.sessions,
    "include_categories": args.include_categories,
    "exclude_categories": args.exclude_categories,
}
```

- [ ] **Step 6: Tests**

Test cases:

```python
def test_sha256_file_is_stable(tmp_path):
    path = tmp_path / "data.txt"
    path.write_text("abc", encoding="utf-8")
    assert sha256_file(str(path)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

def test_write_manifest_sorts_keys(tmp_path):
    write_manifest(tmp_path / "manifest.json", {"b": 2, "a": 1})
    assert '"a": 1' in (tmp_path / "manifest.json").read_text()
```

- [ ] **Step 7: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_artifacts.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add eval.py eval_artifacts.py tests/test_eval_artifacts.py
git commit -m "feat: write reproducible eval manifests"
```

## Task 4: Fix QA Output Contract

**Files:**
- Modify: `eval.py`
- Modify: `eval_artifacts.py`
- Test: `tests/test_eval_artifacts.py`

- [ ] **Step 1: Add JSONL append helper**

Create:

```python
def append_jsonl(path: Path, item: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
```

- [ ] **Step 2: Add aggregate answers writer**

Create:

```python
def write_answers(path: Path, records: list[dict], summary: dict) -> None:
    payload = {"results": records, "summary": summary}
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
```

- [ ] **Step 3: Update `run_qa()`**

After `results_list = asyncio.run(_run())`, flatten all records:

```python
all_records = []
for records, sample_usage in results_list:
    all_records.extend(records)
```

Write:

```text
<run-dir>/qa.jsonl
<run-dir>/qa_summary.json
<run-dir>/answers.json
```

- [ ] **Step 4: Preserve legacy output**

If `--output` is provided without `--run-dir`, keep current summary text output, but also write `<output>.json` with `{"results": all_records, "summary": summary}` so `judge.py output/answers.txt.json` works.

- [ ] **Step 5: Tests**

Test cases:

```python
def test_write_answers_uses_results_key(tmp_path):
    write_answers(tmp_path / "answers.json", [{"question": "q"}], {"total": 1})
    data = json.loads((tmp_path / "answers.json").read_text())
    assert data["results"] == [{"question": "q"}]
    assert data["summary"] == {"total": 1}
```

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_artifacts.py tests/test_eval_user_keys.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add eval.py eval_artifacts.py tests/test_eval_artifacts.py tests/test_eval_user_keys.py
git commit -m "fix: write aggregate qa answers for judging"
```

## Task 5: Add Memory Write Verification

**Files:**
- Create: `eval_memory_verify.py`
- Modify: `eval.py`
- Test: `tests/test_eval_memory_verify.py`

- [ ] **Step 1: Add file snapshot**

Create:

```python
def snapshot_memory_files(workspace: str) -> dict[str, dict]:
    root = Path(workspace).expanduser()
    candidates = [root / "MEMORY.md"]
    memory_dir = root / "memory"
    if memory_dir.exists():
        candidates.extend(p for p in memory_dir.rglob("*.md") if p.is_file())
    snapshot = {}
    for path in candidates:
        if path.exists() and path.is_file():
            stat = path.stat()
            snapshot[str(path)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(str(path)),
            }
    return snapshot
```

- [ ] **Step 2: Add diff helper**

Create:

```python
def diff_memory_snapshots(before: dict, after: dict) -> dict:
    created = sorted(path for path in after if path not in before)
    modified = sorted(
        path for path in after
        if path in before and after[path]["sha256"] != before[path]["sha256"]
    )
    unchanged = sorted(path for path in after if path in before and path not in modified)
    return {
        "created": created,
        "modified": modified,
        "unchanged": unchanged,
        "write_detected": bool(created or modified),
    }
```

- [ ] **Step 3: Add CLI arg**

Add:

```python
parser.add_argument("--agent-workspace", default=None, help="Eval agent workspace path used to verify memory writes")
```

If `--agent-workspace` is missing, strict publishable mode should mark memory verification as `"status": "not_configured"`.

- [ ] **Step 4: Integrate ingest verification**

Before ingest for each sample, snapshot memory files. After ingest for each sample, snapshot again and write:

```text
<run-dir>/memory_write_verification.json
```

The output should include per-sample `created`, `modified`, and `write_detected`.

- [ ] **Step 5: Tests**

Test cases:

```python
def test_snapshot_memory_files_reads_memory_and_daily_files(tmp_path):
    (tmp_path / "MEMORY.md").write_text("durable", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-12.md").write_text("daily", encoding="utf-8")
    snapshot = snapshot_memory_files(str(tmp_path))
    assert len(snapshot) == 2

def test_diff_memory_snapshots_detects_modified_file(tmp_path):
    before = {"MEMORY.md": {"sha256": "old"}}
    after = {"MEMORY.md": {"sha256": "new"}}
    assert diff_memory_snapshots(before, after)["write_detected"] is True
```

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_memory_verify.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add eval.py eval_memory_verify.py tests/test_eval_memory_verify.py
git commit -m "feat: verify memory writes during ingest"
```

## Task 6: Add Contamination Canary Runs

**Files:**
- Modify: `eval.py`
- Modify: `eval_artifacts.py`
- Test: `tests/test_eval_artifacts.py`

- [ ] **Step 1: Define canary record**

A canary record is a normal QA request with:

```python
{
    "type": "contamination_canary",
    "source_sample_id": "conv-30",
    "target_user": "eval-conv-26",
    "question": "...",
    "expected": "...",
    "response": "...",
}
```

- [ ] **Step 2: Add CLI args**

Add:

```python
parser.add_argument("--canary", action="store_true", default=False, help="Run cross-sample contamination canaries")
parser.add_argument("--canary-count", type=int, default=3, help="Canary questions per sample pair")
```

- [ ] **Step 3: Implement simple canary selection**

For each selected sample, pick questions from the next selected sample and send them to the current sample user. Save records to:

```text
<run-dir>/canary.jsonl
```

The harness should not auto-grade canaries as benchmark score. It should report them as leakage checks.

- [ ] **Step 4: Tests**

Test the canary selector without network calls:

```python
def test_canary_pairs_next_sample_questions_to_current_user():
    # conv-26 user receives conv-30 questions
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add eval.py eval_artifacts.py tests/test_eval_artifacts.py
git commit -m "feat: add cross-sample contamination canaries"
```

## Task 7: Harden Judge Output

**Files:**
- Modify: `judge.py`
- Modify: `judge_util.py`
- Test: `tests/test_judge_util.py`

- [ ] **Step 1: Return full judge payload**

Change `locomo_grader()` to return:

```python
{
    "grade": True,
    "label": "CORRECT",
    "reasoning": "...",
    "judge_model": model,
}
```

Do not return only a boolean.

- [ ] **Step 2: Enforce JSON mode where supported**

Use:

```python
response_format={"type": "json_object"}
```

Keep a fallback parser that extracts the first JSON object if the provider rejects `response_format`.

- [ ] **Step 3: Add bounded concurrency**

Add CLI arg:

```python
parser.add_argument("--parallel", type=int, default=8, help="Judge requests in flight")
```

Use `asyncio.Semaphore`.

- [ ] **Step 4: Add retry for transient judge failures**

Retry 429, 500, 502, 503, 504 up to 3 attempts with short backoff.

- [ ] **Step 5: Preserve per-category summary**

`judge_grades.json` should include:

```python
{
    "score": 0.0,
    "correct": 0,
    "total": 0,
    "per_category": {"1": {"correct": 0, "total": 0, "score": 0.0}},
    "grades": [...]
}
```

- [ ] **Step 6: Tests**

Test cases:

```python
def test_load_answers_accepts_results_key(tmp_path):
    # current behavior should remain supported

def test_per_category_summary_counts_each_category():
    # pure function test, no network

def test_grader_parses_json_label():
    # mock AsyncOpenAI response content
```

- [ ] **Step 7: Verify**

Run:

```bash
uv run python -m unittest tests/test_judge_util.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add judge.py judge_util.py tests/test_judge_util.py
git commit -m "feat: harden locomo judge outputs"
```

## Task 8: Generate Final HTML Report

**Files:**
- Modify: `eval_artifacts.py`
- Modify: `judge.py`
- Test: `tests/test_eval_artifacts.py`

- [ ] **Step 1: Add report renderer**

Create:

```python
def render_report_html(manifest: dict, qa_summary: dict, judge_summary: dict | None = None) -> str:
    ...
```

Report sections:

- Run identity
- Isolation mode
- Dataset counts
- Category policy
- Ingest sessions and token usage
- Memory write verification
- QA score and per-category score
- Canary results
- Links to JSONL artifacts

- [ ] **Step 2: Write report after judge**

When `judge.py --output output/runs/<run_id>/judge_grades.json` is used and the sibling `manifest.json` exists, write:

```text
output/runs/<run_id>/report.html
```

- [ ] **Step 3: Tests**

Test:

```python
def test_render_report_html_includes_score_and_manifest():
    html = render_report_html({"run_id": "r1"}, {"total": 2}, {"score": 0.5})
    assert "r1" in html
    assert "50.00%" in html
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_artifacts.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add eval_artifacts.py judge.py tests/test_eval_artifacts.py
git commit -m "feat: render benchmark run reports"
```

## Task 8.5: Add OpenViking Adapter And Comparison Report

**Files:**
- Create: `eval_openviking.py`
- Modify: `eval_backends.py`
- Modify: `eval_artifacts.py`
- Test: `tests/test_eval_openviking.py`
- Test: `tests/test_eval_artifacts.py`

- [ ] **Step 1: Add OpenViking ingest adapter**

Wrap the current experimental CLI path instead of scattering subprocess calls:

```python
def add_memory(content: str, account: str | None, user: str, agent_id: str) -> dict:
    cmd = ["ov", "add-memory", content, "--user", user, "--agent-id", agent_id]
    if account:
        cmd.extend(["--account", account])
    ...
```

The adapter should capture stdout, stderr, return code, and timing in `ingest.jsonl`.

- [ ] **Step 2: Add OpenViking retrieval adapter**

Use:

```python
ov search <question> --user <user> --agent-id <agent_id> --output json
```

The adapter should normalize retrieved memories into:

```python
{
    "query": "...",
    "retrieved": [
        {"text": "...", "score": 0.0, "source": "..."}
    ]
}
```

- [ ] **Step 3: Add final answer path**

Preferred publishable mode:

```text
OpenViking writes memory
  -> OpenViking retrieves memory
  -> fixed answer model answers from retrieved context
```

This should be recorded as:

```json
{
  "backend_id": "openviking",
  "answer_mode": "openviking-search-rag"
}
```

If OpenViking exposes a stable chat/answer API later, add it as a separate `answer_mode`; do not silently replace the search-RAG mode.

- [ ] **Step 4: Render comparison report**

Add:

```python
def render_comparison_report_html(group_manifest: dict, backend_summaries: list[dict]) -> str:
    ...
```

Report columns:

- Backend id
- Memory implementation
- Isolation mode
- Publishable status
- QA total
- Overall judge score
- Per-category score
- Memory write verification
- Canary leakage count
- Notes/non-publishable reasons

- [ ] **Step 5: Tests**

Test cases:

```python
def test_openviking_add_memory_command_includes_user_and_agent():
    # patch subprocess.run and assert argv

def test_openviking_search_normalizes_json_output():
    # parse mocked ov search JSON

def test_comparison_report_orders_builtin_first():
    # oo-builtin remains baseline row
```

- [ ] **Step 6: Verify**

Run:

```bash
uv run python -m unittest tests/test_eval_openviking.py tests/test_eval_artifacts.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add eval_openviking.py eval_backends.py eval_artifacts.py tests/test_eval_openviking.py tests/test_eval_artifacts.py
git commit -m "feat: compare openclaw and openviking memory backends"
```

## Task 9: Update Docs And Reproducible Runbook

**Files:**
- Modify: `README.md`
- Create: `docs/reproducible-locomo-eval.md`

- [ ] **Step 1: Document strict local run**

Add a section showing:

```bash
uv sync
uv run python eval.py ingest ./locomo10.json --agent eval-locomo --run-dir output/runs/dev-smoke --sample 0 --sessions 1-4 --agent-workspace ~/.openclaw/workspace-locomo-eval
uv run python eval.py qa ./locomo10.json --agent eval-locomo --run-dir output/runs/dev-smoke --sample 0 --include-categories 1,2,3,4,5
uv run python judge.py output/runs/dev-smoke/answers.json --output output/runs/dev-smoke/judge_grades.json
```

- [ ] **Step 2: Document publishable profile run**

Add:

```bash
OPENCLAW_PROFILE=locomo-eval openclaw gateway --port 18790
```

and the matching `--base-url`.

- [ ] **Step 3: Document backend comparison run**

Add:

```bash
uv run python eval.py compare ./locomo10.json \
  --run-group output/runs/locomo-memory-comparison-001 \
  --backends oo-builtin,oo-qmd,openviking \
  --include-categories 1,2,3,4,5
```

Document that `oo-builtin` is the baseline, `oo-qmd` is an OpenClaw memory backend variant, and `openviking` is a separate memory system adapter. State that QMD extra paths/session transcript indexing are off for the primary comparison unless the run is explicitly marked as an ablation.

- [ ] **Step 4: Document category policy**

State that strict mode includes categories `1,2,3,4,5` by default. Category exclusions must be explicit in the manifest.

- [ ] **Step 5: Document non-publishable conditions**

A run is not publishable if:

- `memory_write_verification.status` is `not_configured`
- the eval agent is `main`
- requested backend config cannot be verified
- QMD extra paths or transcript indexing are enabled in a primary comparison run
- category exclusions are not declared
- manifest is missing dataset hash or eval commit
- QA artifacts are incomplete

- [ ] **Step 6: Verify docs**

Run:

```bash
rg -n "eval-locomo|memory_write_verification|include-categories|OPENCLAW_PROFILE|oo-builtin|oo-qmd|openviking" README.md docs/reproducible-locomo-eval.md
```

Expected: all key terms are present.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/reproducible-locomo-eval.md
git commit -m "docs: add reproducible locomo eval runbook"
```

## Task 10: End-To-End Smoke Test

**Files:**
- No new files required unless failures reveal missing tests.

- [ ] **Step 1: Run unit tests**

```bash
uv run python -m unittest discover -s tests
```

Expected: all tests pass.

- [ ] **Step 2: Run dry artifact smoke**

Use mocks in unit tests for network calls. Do not hit OpenClaw in CI.

Expected files from mocked strict run:

```text
manifest.json
ingest.jsonl
qa.jsonl
qa_summary.json
answers.json
```

- [ ] **Step 3: Manual local OpenClaw smoke**

Run against `locomo10_small.json`:

```bash
uv run python eval.py ingest ./locomo10_small.json \
  --agent eval-locomo \
  --run-dir output/runs/manual-small \
  --agent-workspace ~/.openclaw/workspace-locomo-eval

uv run python eval.py qa ./locomo10_small.json \
  --agent eval-locomo \
  --run-dir output/runs/manual-small \
  --count 3 \
  --include-categories 1,2,3,4,5
```

Expected:

- `output/runs/manual-small/manifest.json` exists.
- `output/runs/manual-small/answers.json` has `results`.
- `memory_write_verification.json` has `write_detected: true` for the sample, or the run is marked non-publishable.

- [ ] **Step 4: Commit final docs or fixes**

```bash
git status --short
git add <intentional files>
git commit -m "test: verify strict locomo eval workflow"
```

Only commit if this step produced intentional changes.

## Acceptance Criteria

The repo is ready for strict memory eval when all of these are true:

- The harness can run `oo-builtin`, `oo-qmd`, and `openviking` under one comparison group.
- `oo-builtin` is always reported as the baseline row.
- The harness can target `openclaw/eval-locomo` without touching `main`.
- Built-in and QMD OpenClaw runs use separate agents/profiles/workspaces.
- OpenViking runs use separate account/user/agent identifiers and include both memory write and answer behavior.
- Session lookup and reset are agent-aware.
- LoCoMo category `5` is included unless explicitly excluded.
- Every strict run writes a complete `manifest.json`.
- Every strict QA run writes `answers.json` compatible with `judge.py`.
- Ingest records memory write verification.
- Judge output includes per-category scores and saved reasoning.
- Group reports include per-backend scores, per-category scores, publishability status, and non-publishable reasons.
- The docs explain local eval and publishable profile/gateway eval.
- Unit tests cover dataset selection, agent routing, artifact writing, memory verification, and judge parsing.

## Not In Scope

- Rewriting OpenClaw memory internals.
- Pre-loading gold memories directly into files.
- Fetching LoCoMo image URLs or sending `input_image` parts.
- Changing LoCoMo dataset content.
- Optimizing memory search ranking before the harness can measure it.
- Requiring a separate gateway for every local dev run.
- Claiming OpenViking and OpenClaw internals are identical. The comparison measures benchmark behavior under a declared adapter contract.

## Worktree Parallelization Strategy

This implementation can split into four lanes after Task 1 lands.

| Lane | Modules touched | Depends on |
|------|-----------------|------------|
| A | `eval_openclaw.py`, `eval.py`, `tests/test_eval_openclaw.py` | Task 1 |
| B | `eval_artifacts.py`, `eval.py`, `tests/test_eval_artifacts.py` | Task 1 |
| C | `eval_memory_verify.py`, `eval.py`, `tests/test_eval_memory_verify.py` | Task 1 |
| D | `judge.py`, `judge_util.py`, `tests/test_judge_util.py` | none |
| E | `eval_backends.py`, `eval_openviking.py`, comparison report tests | Tasks 2, 3, 4 |

Execution order:

```text
Task 1 sequential
  -> launch Lane A + Lane B + Lane D in parallel
  -> merge
  -> run Lane C + Lane E
  -> docs and end-to-end smoke
```

Conflict flags:

- Lanes A, B, and C all touch `eval.py`. Keep the `eval.py` edits small and merge after each lane.
- Lane E touches `eval.py`, `eval_backends.py`, `eval_artifacts.py`; start it after the strict single-backend run path is stable.
- Lane D is independent and can run in parallel.

## Failure Modes To Test

```text
agent routing
  failure: model stays "openclaw" and hits main
  test: payload model equals "openclaw/eval-locomo"

session reset
  failure: reset looks under agents/main for eval-locomo
  test: temp openclaw home with named agent sessions

category selection
  failure: category 5 silently excluded
  test: default selection returns category 5

artifact output
  failure: judge input file missing or empty
  test: answers.json contains results list

memory verification
  failure: ingest completes but writes nothing
  test: modified memory file produces write_detected true

judge parsing
  failure: non-JSON judge response crashes whole run
  test: malformed response becomes grade error record

backend comparison
  failure: QMD gets extra paths/transcripts and is not comparable to built-in
  test: manifest publishability flags forbidden primary-comparison config

openviking answer path
  failure: OpenViking ingest runs but QA answers bypass retrieval
  test: answer records include normalized retrieval evidence
```

## Completion Summary Template

Use this after implementation:

```text
Strict LoCoMo memory eval status:
- Unit tests: <pass/fail command>
- Smoke run: <run dir>
- Dataset hash: <sha256>
- Agent: <agent id>
- Categories: <included categories>
- Memory writes verified: <yes/no>
- QA records: <count>
- Judge score: <score or not run>
- Publishable: <yes/no and reason>
```

Comparison completion template:

```text
Memory backend comparison status:
- Run group: <path>
- Dataset hash: <sha256>
- Categories: <included categories>
- Baseline: oo-builtin score <score>
- QMD: score <score>, delta vs baseline <delta>
- OpenViking: score <score>, delta vs baseline <delta>
- Non-publishable backends: <list and reasons>
- Comparison report: <path>
```
