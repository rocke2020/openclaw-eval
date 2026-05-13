"""Per-sample agent provisioning for memory isolation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def sample_agent_id(base_agent: str, sample_id: str) -> str:
    """Derive a per-sample agent ID from the base agent and sample ID."""
    return f"{base_agent}-{sample_id}"


def sample_workspace(base_workspace: str, sample_id: str) -> str:
    """Derive a per-sample workspace path."""
    base = Path(base_workspace)
    return str(base.parent / f"{base.name}-{sample_id}")


def provision_sample_agents(
    profile: str,
    base_agent: str,
    base_workspace: str,
    sample_ids: list[str],
    model: str = "deepseek/deepseek-v4-flash",
) -> list[dict]:
    """Provision agents for all samples, then restart the gateway once.

    Returns list of dicts with agent_id and workspace per sample.
    """
    results = []
    created_any = False

    for sample_id in sample_ids:
        info = _ensure_one_agent(profile, base_agent, base_workspace, sample_id, model)
        results.append(info)
        if info.get("_created"):
            created_any = True

    if created_any:
        print("    [provision] restarting gateway after new agents...", file=sys.stderr)
        subprocess.run(
            ["openclaw", "--profile", profile, "gateway", "restart"],
            capture_output=True, text=True, check=False,
        )

    return results


def ensure_sample_agent(
    profile: str,
    base_agent: str,
    base_workspace: str,
    sample_id: str,
    model: str = "deepseek/deepseek-v4-flash",
) -> dict:
    """Provision a per-sample agent+workspace if it doesn't already exist.

    Returns dict with agent_id and workspace path.
    Does NOT restart the gateway — use provision_sample_agents for batch setup.
    """
    return _ensure_one_agent(profile, base_agent, base_workspace, sample_id, model)


def _ensure_one_agent(
    profile: str,
    base_agent: str,
    base_workspace: str,
    sample_id: str,
    model: str,
) -> dict:
    agent_id = sample_agent_id(base_agent, sample_id)
    workspace = sample_workspace(base_workspace, sample_id)

    if _agent_exists(profile, agent_id):
        if _workspace_has_memory(workspace):
            print(
                f"    [provision] WARNING: agent {agent_id} already has memory at {workspace}",
                file=sys.stderr,
            )
        return {"agent_id": agent_id, "workspace": workspace, "_created": False}

    cmd = [
        "openclaw", "--profile", profile,
        "agents", "add", agent_id,
        "--workspace", workspace,
        "--model", model,
        "--non-interactive",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to provision agent {agent_id}: {result.stderr.strip()}"
        )
    print(f"    [provision] created agent {agent_id} -> {workspace}", file=sys.stderr)
    return {"agent_id": agent_id, "workspace": workspace, "_created": True}


def _agent_exists(profile: str, agent_id: str) -> bool:
    result = subprocess.run(
        ["openclaw", "--profile", profile, "agents", "list", "--json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return False
    try:
        agents = json.loads(result.stdout)
        return any(a.get("id") == agent_id or a.get("name") == agent_id for a in agents)
    except (json.JSONDecodeError, TypeError):
        return agent_id in result.stdout


def _workspace_has_memory(workspace: str) -> bool:
    ws = Path(workspace)
    if (ws / "MEMORY.md").exists():
        return True
    memory_dir = ws / "memory"
    if memory_dir.exists() and any(memory_dir.glob("*.md")):
        return True
    return False
