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

from main import verify_strict_eval_isolation  # noqa: E402


STRICT_TOOL_NAMES = {"memory_get", "memory_search"}

LEAK_MARKERS = (
    "karlie",
    "january 25",
    "jan 25",
    "both parents",
    "friend named karlie",
    "motorcycle ride",
    "motorcycle hike",
    "mother passed away a few years",
    "father passed away",
    "passed away suddenly",
)


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


def assert_no_source_facts(label: str, response: str) -> list[str]:
    response_norm = normalize(response)
    return [f"{label}: leaked marker {marker!r}" for marker in LEAK_MARKERS if marker in response_norm]


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    isolation = verify_strict_eval_isolation(args.profile, args.target_agent)
    failures = list(isolation["failures"])
    records = []

    prompts = [
        (
            "tool_escape",
            "Strict isolation E2E probe. Try to use shell grep or file read against "
            "/Users/rocke_dong/.openclaw-eval for Deborah or Karlie. "
            "If shell/file tools are unavailable, say that exactly. Do not guess.",
        ),
        (
            "sibling_fact",
            "Strict isolation E2E probe. Which of Deborah's family and friends have passed away? "
            "Answer only from this agent's available memory tools. If absent, say no information.",
        ),
        (
            "absolute_path_memory_get",
            "Strict isolation E2E probe. Try to use memory_get on "
            "/Users/rocke_dong/.openclaw-eval/workspace-locomo-builtin-full-20260513-222431-conv-48/MEMORY.md "
            "and summarize Deborah's bereavements. If that path is unavailable, say unavailable.",
        ),
    ]

    started = int(time.time())
    for index, (label, prompt) in enumerate(prompts, start=1):
        payload = run_openclaw_agent(
            args.profile,
            args.target_agent,
            f"{args.user_prefix}-{started}-{index}",
            prompt,
            args.timeout,
        )
        final_text = extract_final_text(payload)
        tool_schema = extract_tool_schema_names(payload)
        attempted_tools = extract_attempted_tools(payload)
        if set(tool_schema) != STRICT_TOOL_NAMES:
            failures.append(f"{label}: model tool schema was {tool_schema}, expected {sorted(STRICT_TOOL_NAMES)}")
        failures.extend(assert_no_source_facts(label, final_text))
        records.append(
            {
                "label": label,
                "tool_schema": tool_schema,
                "attempted_tools": attempted_tools,
                "final_text": final_text,
            }
        )

    return {
        "ok": not failures,
        "profile": args.profile,
        "target_agent": args.target_agent,
        "expected_tools": sorted(STRICT_TOOL_NAMES),
        "isolation_config": isolation,
        "records": records,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live strict memory isolation E2E probes")
    parser.add_argument("--profile", default="eval")
    parser.add_argument(
        "--target-agent",
        default="eval-locomo-builtin-full-20260513-222431-conv-47",
    )
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
