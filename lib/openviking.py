"""OpenViking CLI adapter for benchmark comparisons."""

from __future__ import annotations

import json
import subprocess
import time


def add_memory(content: str, account: str | None, user: str, agent_id: str) -> dict:
    cmd = ["ov", "add-memory", content, "--user", user, "--agent-id", agent_id]
    if account:
        cmd.extend(["--account", account])
    started = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "argv": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_s": time.monotonic() - started,
    }


def search(query: str, account: str | None, user: str, agent_id: str) -> dict:
    cmd = ["ov", "search", query, "--user", user, "--agent-id", agent_id, "--output", "json"]
    if account:
        cmd.extend(["--account", account])
    started = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    retrieved = normalize_search_output(result.stdout)
    return {
        "argv": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_s": time.monotonic() - started,
        "query": query,
        "retrieved": retrieved,
    }


def normalize_search_output(output: str) -> list[dict]:
    if not output.strip():
        return []
    data = json.loads(output)
    if isinstance(data, dict):
        items = data.get("results", data.get("memories", []))
    else:
        items = data

    normalized = []
    for item in items:
        if isinstance(item, str):
            normalized.append({"text": item, "score": 0.0, "source": ""})
            continue
        normalized.append(
            {
                "text": item.get("text") or item.get("content") or item.get("memory") or "",
                "score": float(item.get("score", 0.0) or 0.0),
                "source": item.get("source") or item.get("id") or "",
            }
        )
    return normalized
