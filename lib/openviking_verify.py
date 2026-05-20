"""OpenViking-side write + runtime evidence + isolation probes.

The OV plugin reproduction needs three OV-shaped checks distinct from the
OC-shaped checks already in `lib/memory_verify.py` and `main.py`:

  1. probe_session_exists(account, ov_agent_id, user)
     Post-ingest: did the agent commit at least one OV session?
     Read-only `ov session list`.

  2. probe_positive_recall(account, ov_agent_id, user, canary_text)
     Post-ingest: is a known LoCoMo fact actually retrievable?
     Read-only `ov find`.

  3. verify_runtime_ov_evidence(openclaw_home, oc_agent_ids)
     Post-QA: scan the OC agent transcripts for *either* OV plugin tool
     calls (`memory_recall`/`memory_search`/`memory_store`) *or* context-engine
     lifecycle hook traces (`assemble` / `afterTurn` / `commit`). Either
     evidence kind satisfies the gate; counts go into the manifest separately.

All probes are read-only. No `ov session delete`, no `ov rm`, no destructive
verbs. Codex flagged that "session count >= 1" alone is weak; we pair it
with positive recall.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterator


def _ov_bin() -> str:
    path = shutil.which("ov")
    if not path:
        raise RuntimeError("ov CLI not found on PATH")
    return path


def _run_ov(*args: str, api_key: str | None = None, timeout_s: float = 30.0) -> dict:
    cmd = [_ov_bin(), *args]
    env = None
    if api_key:
        import os
        env = os.environ.copy()
        env["OPENVIKING_API_KEY"] = api_key
    started = time.monotonic()
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, env=env, timeout=timeout_s,
    )
    return {
        "argv": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_s": round(time.monotonic() - started, 3),
    }


def _parse_ov_json(stdout: str) -> object | None:
    body = (stdout or "").strip()
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def probe_session_exists(
    account: str | None,
    ov_agent_id: str,
    user: str,
    api_key: str | None = None,
) -> dict:
    """Return {write_detected, sessions_count, raw}.

    Read-only. Calls `ov session list --agent-id <id> --user <u> [--account <a>]
    --output json`.
    """
    args = [
        "session", "list",
        "--agent-id", ov_agent_id,
        "--user", user,
        "--output", "json",
    ]
    if account:
        args.extend(["--account", account])
    result = _run_ov(*args, api_key=api_key)
    parsed = _parse_ov_json(result["stdout"])
    sessions_count = 0
    if isinstance(parsed, list):
        sessions_count = len(parsed)
    elif isinstance(parsed, dict):
        items = parsed.get("sessions") or parsed.get("results") or []
        if isinstance(items, list):
            sessions_count = len(items)
    return {
        "write_detected": sessions_count > 0,
        "sessions_count": sessions_count,
        "ov_agent_id": ov_agent_id,
        "user": user,
        "account": account,
        "returncode": result["returncode"],
        "stderr_snippet": (result["stderr"] or "").strip()[:240],
    }


def probe_positive_recall(
    account: str | None,
    ov_agent_id: str,
    user: str,
    canary_text: str,
    api_key: str | None = None,
    node_limit: int = 5,
) -> dict:
    """Return {recall_hit, hit_count, top_score, raw}.

    Read-only. Calls `ov find "<canary>" --agent-id <id> --user <u>
    -n <node_limit> --output json`.
    """
    args = [
        "find", canary_text,
        "--agent-id", ov_agent_id,
        "--user", user,
        "-n", str(node_limit),
        "--output", "json",
    ]
    if account:
        args.extend(["--account", account])
    result = _run_ov(*args, api_key=api_key)
    parsed = _parse_ov_json(result["stdout"])
    items: list = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        items = parsed.get("results") or parsed.get("memories") or []
    top_score = None
    for item in items:
        if isinstance(item, dict) and "score" in item:
            try:
                score = float(item["score"])
            except (TypeError, ValueError):
                continue
            top_score = score if top_score is None else max(top_score, score)
    return {
        "recall_hit": bool(items),
        "hit_count": len(items),
        "top_score": top_score,
        "ov_agent_id": ov_agent_id,
        "user": user,
        "account": account,
        "canary_text": canary_text,
        "returncode": result["returncode"],
        "stderr_snippet": (result["stderr"] or "").strip()[:240],
    }


# --- runtime evidence (OC transcript scanning) -------------------------------

_OV_PLUGIN_TOOL_NAMES = {
    "memory_recall",
    "memory_store",
    "memory_forget",
    "memory_search",
    "ov_archive_expand",
}

_OV_CONTEXT_ENGINE_HOOKS = {
    "assemble",
    "afterTurn",
    "commit",
    "session_start",
    "session_end",
    "before_reset",
}


def _iter_session_records(openclaw_home: Path, agent_id: str) -> Iterator[tuple[Path, int, dict]]:
    sessions_dir = openclaw_home / "agents" / agent_id / "sessions"
    if not sessions_dir.exists():
        return
    for path in sorted(sessions_dir.glob("*.jsonl*")):
        if path.name == "sessions.json":
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for ln, line in enumerate(f, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    yield path, ln, record
        except OSError:
            continue


def _extract_tool_name_and_provider(record: dict) -> tuple[str | None, str | None]:
    message = record.get("message")
    if not isinstance(message, dict):
        return None, None
    tool_name = message.get("toolName") or message.get("tool")
    if not tool_name:
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"tool_use", "tool_result"}:
                    tool_name = item.get("name") or item.get("toolName")
                    if tool_name:
                        break
    if not tool_name:
        return None, None
    details = message.get("details")
    provider = None
    if isinstance(details, dict):
        provider = details.get("providerId") or details.get("registeringPluginId") or details.get("plugin")
    return tool_name, provider


def _is_context_engine_event(record: dict) -> bool:
    if not isinstance(record, dict):
        return False
    event = record.get("event") or record.get("type")
    if isinstance(event, str) and event in _OV_CONTEXT_ENGINE_HOOKS:
        return True
    msg = record.get("message")
    if isinstance(msg, dict):
        kind = msg.get("kind") or msg.get("event")
        if isinstance(kind, str) and kind in _OV_CONTEXT_ENGINE_HOOKS:
            return True
        # Some implementations log "contextEngine" with a hook field.
        details = msg.get("details") if isinstance(msg.get("details"), dict) else {}
        if details.get("plugin") == "openviking" and details.get("hook") in _OV_CONTEXT_ENGINE_HOOKS:
            return True
    return False


def verify_runtime_ov_evidence(openclaw_home: Path, oc_agent_ids: list[str]) -> dict:
    """Return per-agent evidence counts + overall failures.

    A row passes when every agent has >= 1 *either* tool-call evidence *or*
    lifecycle-hook evidence. We do not require both — codex flagged that
    context-engine plugins may not surface model-visible tool calls at all.
    """
    by_agent: dict[str, dict] = {}
    failures: list[str] = []
    for agent_id in oc_agent_ids:
        tool_calls = 0
        hook_events = 0
        provenance: dict[str, int] = {}
        for _path, _ln, record in _iter_session_records(openclaw_home, agent_id):
            tool_name, provider = _extract_tool_name_and_provider(record)
            if tool_name in _OV_PLUGIN_TOOL_NAMES:
                tool_calls += 1
                key = provider or "unknown"
                provenance[key] = provenance.get(key, 0) + 1
            if _is_context_engine_event(record):
                hook_events += 1
        by_agent[agent_id] = {
            "tool_calls_total": tool_calls,
            "lifecycle_hooks_total": hook_events,
            "provenance": provenance,
        }
        if tool_calls == 0 and hook_events == 0:
            failures.append(
                f"agent {agent_id}: no OV plugin tool calls and no context-engine hook events"
            )
    return {
        "ok": not failures,
        "by_agent": by_agent,
        "failures": failures,
        "tool_calls_total": sum(a["tool_calls_total"] for a in by_agent.values()),
        "lifecycle_hooks_total": sum(a["lifecycle_hooks_total"] for a in by_agent.values()),
    }


# --- cross-scope isolation --------------------------------------------------


def verify_strict_openviking_scope_isolation(
    account: str | None,
    ov_agent_ids: list[str],
    sample_users: list[str],
    canary_text: str = "the_sample_specific_marker_phrase_that_should_not_cross",
    api_key: str | None = None,
) -> dict:
    """For each adjacent (i, j), `ov find` from agent_i with user_j must be empty.

    Cheap canary: even if the underlying samples don't share content, OV scope
    isolation should mean a user from one sample cannot query another sample's
    agent at all (or gets no results). We probe with a string that should not
    appear in ANY sample to keep the test cheap; a non-zero result implies the
    scope split isn't doing what the plugin manifest claims.
    """
    failures: list[str] = []
    probes: list[dict] = []
    n = min(len(ov_agent_ids), len(sample_users))
    for i in range(n):
        j = (i + 1) % n
        if i == j:
            continue
        ov_agent_id = ov_agent_ids[i]
        user = sample_users[j]
        probe = probe_positive_recall(
            account=account,
            ov_agent_id=ov_agent_id,
            user=user,
            canary_text=canary_text,
            api_key=api_key,
            node_limit=1,
        )
        probes.append(probe)
        if probe["recall_hit"]:
            failures.append(
                f"cross-scope leak: agent={ov_agent_id} user={user} returned "
                f"{probe['hit_count']} hit(s) for unrelated canary"
            )
    return {"ok": not failures, "failures": failures, "probes": probes}
