"""Artifact helpers for reproducible eval runs."""

from __future__ import annotations

import hashlib
import html
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def ensure_run_dir(path: str) -> Path:
    run_dir = Path(path)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(path: Path, manifest: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, item: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def write_answers(path: Path, records: list[dict], summary: dict) -> None:
    payload = {"results": records, "summary": summary}
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def created_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_dirty() -> bool | None:
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def summarize_usage(records: list[dict]) -> dict:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for record in records:
        item_usage = record.get("usage") or {}
        for key in usage:
            usage[key] += item_usage.get(key, 0)
    return usage


def build_manifest(args, samples: list[dict], stats: dict, backend_config: dict | None = None) -> dict:
    run_dir_name = Path(args.run_dir).name if getattr(args, "run_dir", None) else None
    selected_qa_count = sum(len(item.get("qa", [])) for item in samples)
    manifest = {
        "run_id": run_dir_name,
        "run_group_id": getattr(args, "run_group_id", None),
        "backend_id": getattr(args, "backend_id", "oo-builtin"),
        "backend_kind": getattr(args, "backend_kind", "openclaw"),
        "backend_config": backend_config or {},
        "created_at": created_at_utc(),
        "dataset_path": args.input,
        "dataset_sha256": sha256_file(args.input),
        "dataset_sample_count": stats.get("dataset_sample_count"),
        "dataset_session_count": stats.get("dataset_session_count"),
        "dataset_qa_count_total": stats.get("dataset_qa_count_total"),
        "dataset_qa_count_selected": selected_qa_count,
        "eval_repo_commit": git_commit(),
        "eval_repo_dirty": git_dirty(),
        "openclaw_base_url": getattr(args, "base_url", None),
        "openclaw_agent": getattr(args, "agent", None),
        "openclaw_model": f"openclaw/{getattr(args, 'agent', 'main')}",
        "openclaw_profile": getattr(args, "openclaw_profile", None),
        "openviking_account": getattr(args, "openviking_account", None),
        "openviking_user": getattr(args, "openviking_user", None),
        "openviking_agent_id": getattr(args, "openviking_agent_id", None),
        "user_policy": "per-sample default" if not getattr(args, "user", None) else "explicit",
        "category_policy": {
            "include_categories": getattr(args, "include_categories", None),
            "exclude_categories": getattr(args, "exclude_categories", None),
        },
        "tail": getattr(args, "tail", None),
        "sample": getattr(args, "sample", None),
        "session_range": getattr(args, "sessions", None),
        "parallel": getattr(args, "parallel", None),
        "memory_write_verification": "not_configured"
        if not getattr(args, "agent_workspace", None)
        else "configured",
        "judge_model": getattr(args, "judge_model", None),
        "judge_base_url": getattr(args, "judge_base_url", None),
    }
    return manifest


def summarize_judged(graded: list[dict]) -> dict:
    correct = sum(1 for g in graded if g.get("grade"))
    total = len(graded)
    per_category = per_category_summary(graded)
    return {
        "score": correct / total if total else 0.0,
        "correct": correct,
        "total": total,
        "per_category": per_category,
        "grades": graded,
    }


def per_category_summary(graded: list[dict]) -> dict:
    categories: dict[str, dict] = {}
    for item in graded:
        cat = str(item.get("category", "unknown"))
        categories.setdefault(cat, {"correct": 0, "total": 0, "score": 0.0})
        categories[cat]["total"] += 1
        if item.get("grade"):
            categories[cat]["correct"] += 1
    for item in categories.values():
        item["score"] = item["correct"] / item["total"] if item["total"] else 0.0
    return categories


CATEGORY_LABELS = {
    "1": "Single-hop factual",
    "2": "Temporal",
    "3": "Multi-hop reasoning",
    "4": "Yes/No verification",
    "5": "Open-ended / adversarial",
}

CATEGORY_LEGEND = """<details open><summary><strong>Category definitions</strong></summary>
<table>
<thead><tr><th>Category</th><th>What it tests</th><th>Example Q</th><th>Expected keywords</th><th>How to answer</th></tr></thead>
<tbody>
<tr><td>1 — Single-hop factual</td><td>Direct recall of one stated fact</td>
<td>What instrument does Melanie play?</td><td>Violin</td>
<td>Retrieve the single conversation where the fact was mentioned</td></tr>
<tr><td>2 — Temporal</td><td>Date/time recall or ordering</td>
<td>When did Caroline go to the support group?</td><td>7 May 2023</td>
<td>Locate the event and return its timestamp</td></tr>
<tr><td>3 — Multi-hop reasoning</td><td>Combine facts from multiple conversations</td>
<td>Who introduced the hobby that Dave later taught?</td><td>Calvin</td>
<td>Chain: find who introduced it → confirm Dave taught it → return the introducer</td></tr>
<tr><td>4 — Yes/No verification</td><td>Confirm or deny a claim against memory</td>
<td>Did Sam ever mention visiting Italy?</td><td>No</td>
<td>Search all conversations for the claim; absence = No</td></tr>
<tr><td>5 — Open-ended / adversarial</td><td>Questions with false premises, misattributions, or requiring unstated inference</td>
<td>What did Caroline realize after her charity race?</td><td>Self-care is important (trap: it was Melanie's race, not Caroline's)</td>
<td>Detect the misattribution, refuse the false premise, then recall the correct person's realization</td></tr>
</tbody></table></details>"""


def _render_category_table(per_category: dict) -> str:
    if not per_category:
        return ""
    rows = []
    for cat in sorted(per_category):
        c = per_category[cat]
        label = CATEGORY_LABELS.get(cat, f"Category {cat}")
        rows.append(
            f"<tr><td>{html.escape(cat)}</td>"
            f"<td>{html.escape(label)}</td>"
            f"<td>{c['correct']}/{c['total']}</td>"
            f"<td>{c['score']:.2%}</td></tr>"
        )
    return (
        "<h2>Per-category scores</h2>"
        "<table><thead><tr><th>Category</th><th>Type</th><th>Correct</th>"
        "<th>Score</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"{CATEGORY_LEGEND}"
    )


def render_report_html(
    manifest: dict,
    qa_summary: dict,
    judge_summary: dict | None = None,
) -> str:
    score = None
    category_html = ""
    if judge_summary:
        score = f"{judge_summary.get('score', 0.0):.2%}"
        category_html = _render_category_table(judge_summary.get("per_category", {}))
    rows = [
        ("Run", manifest.get("run_id")),
        ("Backend", manifest.get("backend_id")),
        ("Agent", manifest.get("openclaw_agent")),
        ("Dataset", manifest.get("dataset_path")),
        ("Selected QA", qa_summary.get("total")),
        ("Judge score", score or "not judged"),
        ("Memory verification", manifest.get("memory_write_verification")),
    ]
    body = "\n".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
        for k, v in rows
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>LoCoMo Eval Report</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;max-width:960px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
        "th{width:14rem;background:#f6f6f6}</style></head><body>"
        f"<h1>LoCoMo Eval Report: {html.escape(str(manifest.get('run_id')))}</h1>"
        f"<table>{body}</table>"
        f"{category_html}"
        "</body></html>"
    )


def render_comparison_report_html(group_manifest: dict, backend_summaries: list[dict]) -> str:
    ordered = sorted(
        backend_summaries,
        key=lambda item: (0 if item.get("backend_id") == "oo-builtin" else 1, item.get("backend_id", "")),
    )
    rows = []
    for summary in ordered:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(summary.get('backend_id')))}</td>"
            f"<td>{html.escape(str(summary.get('backend_kind', '')))}</td>"
            f"<td>{html.escape(str(summary.get('publishable', False)))}</td>"
            f"<td>{html.escape(str(summary.get('qa_total', 0)))}</td>"
            f"<td>{summary.get('judge_score', 0.0):.2%}</td>"
            f"<td>{html.escape(str(summary.get('memory_write_verified', False)))}</td>"
            f"<td>{html.escape(str(summary.get('canary_leakage_count', 0)))}</td>"
            f"<td>{html.escape('; '.join(summary.get('non_publishable_reasons', [])))}</td>"
            "</tr>"
        )

    category_sections = []
    for summary in ordered:
        per_category = summary.get("per_category", {})
        if per_category:
            backend_id = summary.get("backend_id", "")
            section = f"<h3>{html.escape(backend_id)}</h3>{_render_category_table(per_category)}"
            category_sections.append(section)

    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Memory Backend Comparison</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;max-width:960px}"
        "table{border-collapse:collapse;width:100%;margin-bottom:1.5rem}"
        "th,td{border:1px solid #ddd;padding:.5rem;text-align:left}"
        "th{background:#f6f6f6}</style></head><body>"
        f"<h1>{html.escape(str(group_manifest.get('run_group_id', 'comparison')))}</h1>"
        "<table><thead><tr><th>Backend</th><th>Kind</th><th>Publishable</th>"
        "<th>QA total</th><th>Score</th><th>Memory writes</th><th>Canary leaks</th><th>Notes</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"{''.join(category_sections)}"
        "</body></html>"
    )
