#!/usr/bin/env python3
"""End-to-end strict memory isolation probe for the OpenClaw eval profile.

This test talks to the live OpenClaw eval gateway through `openclaw agent`.
It verifies the model only receives builtin memory tools, then asks a target
sample agent questions whose answers exist only in a sibling sample.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import (  # noqa: E402
    ADVERSARIAL_CANARY_CASES,
    STRICT_MEMORY_TOOLS,
    canary_record_leaked,
    default_sample_user,
    verify_strict_eval_isolation,
)


STRICT_TOOL_NAMES = STRICT_MEMORY_TOOLS


def normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def run_openclaw_agent(profile: str, agent: str, user: str, prompt: str, timeout: int) -> dict[str, Any]:
    openclaw = shutil.which("openclaw")
    if not openclaw:
        raise RuntimeError("openclaw binary not found")
    result = subprocess.run(
        [
            openclaw,
            "--profile",
            profile,
            "agent",
            "--agent",
            agent,
            "--to",
            user,
            "--message",
            prompt,
            "--json",
            "--timeout",
            str(timeout),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "openclaw agent failed")
    return json.loads(result.stdout)


def extract_final_text(payload: dict[str, Any]) -> str:
    result = payload.get("result", {})
    meta = result.get("meta", {})
    text = meta.get("finalAssistantVisibleText") or meta.get("finalAssistantRawText")
    if isinstance(text, str):
        return text
    payloads = result.get("payloads", [])
    if payloads and isinstance(payloads[0], dict):
        return str(payloads[0].get("text", ""))
    return ""


def extract_tool_schema_names(payload: dict[str, Any]) -> list[str]:
    report = payload.get("result", {}).get("meta", {}).get("systemPromptReport", {})
    tools = report.get("tools", {}).get("entries", [])
    return sorted(
        item["name"]
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )


def extract_attempted_tools(payload: dict[str, Any]) -> list[str]:
    summary = payload.get("result", {}).get("meta", {}).get("toolSummary", {})
    tools = summary.get("tools", [])
    if not isinstance(tools, list):
        return []
    return sorted(str(tool) for tool in tools)


def selected_cases(args: argparse.Namespace) -> list[dict[str, Any]]:
    cases = []
    for case in ADVERSARIAL_CANARY_CASES:
        if args.case != "all" and case["suite"] != args.case:
            continue
        source_workspace = f"{args.workspace_base}-{case['source_sample_id']}"
        leak_markers = list(case["leak_markers"])
        if case["probe_type"] == "tool_escape":
            leak_markers.append(source_workspace)
        cases.append(
            {
                **case,
                "target_agent": f"{args.agent_base}-{case['target_sample_id']}",
                "target_user": default_sample_user(case["target_sample_id"]),
                "source_workspace": source_workspace,
                "question": case["question"].format(
                    openclaw_home=args.openclaw_home,
                    source_workspace=source_workspace,
                ),
                "leak_markers": leak_markers,
            }
        )
    return cases


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    cases = selected_cases(args)
    if not cases:
        raise RuntimeError(f"No adversarial canary cases selected for {args.case!r}")

    isolation_reports = {}
    failures = []
    for target_agent in sorted({case["target_agent"] for case in cases}):
        isolation = verify_strict_eval_isolation(args.profile, target_agent)
        isolation_reports[target_agent] = isolation
        failures.extend(isolation["failures"])
    records = []

    started = int(time.time())
    for index, case in enumerate(cases, start=1):
        payload = run_openclaw_agent(
            args.profile,
            case["target_agent"],
            f"{args.user_prefix}-{started}-{index}",
            case["question"],
            args.timeout,
        )
        final_text = extract_final_text(payload)
        tool_schema = extract_tool_schema_names(payload)
        attempted_tools = extract_attempted_tools(payload)
        if set(tool_schema) != STRICT_TOOL_NAMES:
            failures.append(
                f"{case['case_id']}: model tool schema was {tool_schema}, expected {sorted(STRICT_TOOL_NAMES)}"
            )
        record = {
            "case_id": case["case_id"],
            "suite": case["suite"],
            "probe_type": case["probe_type"],
            "source_sample_id": case["source_sample_id"],
            "target_sample_id": case["target_sample_id"],
            "target_agent": case["target_agent"],
            "target_user": case["target_user"],
            "source_workspace": case["source_workspace"],
            "question": case["question"],
            "leak_markers": case["leak_markers"],
            "response": final_text,
            "tool_schema": tool_schema,
            "attempted_tools": attempted_tools,
        }
        record["leak_detected"] = canary_record_leaked(record)
        if record["leak_detected"]:
            failures.append(f"{case['case_id']}: leaked source-sample marker")
        records.append(
            {
                **record,
                "final_text": final_text,
            }
        )

    return {
        "ok": not failures,
        "profile": args.profile,
        "agent_base": args.agent_base,
        "expected_tools": sorted(STRICT_TOOL_NAMES),
        "isolation_config": isolation_reports,
        "records": records,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live strict memory isolation E2E probes")
    parser.add_argument("--profile", default="eval")
    parser.add_argument("--agent-base", default="eval-locomo-builtin-full-20260513-222431")
    parser.add_argument(
        "--workspace-base",
        default="/Users/rocke_dong/.openclaw-eval/workspace-locomo-builtin-full-20260513-222431",
    )
    parser.add_argument("--openclaw-home", default="/Users/rocke_dong/.openclaw-eval")
    parser.add_argument("--case", choices=("all", "deborah_karlie", "calvin_ferrari"), default="all")
    parser.add_argument("--user-prefix", default="strict-memory-e2e")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = run_probe(args)
    text = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
