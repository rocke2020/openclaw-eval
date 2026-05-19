"""Retrieval-only ablation helpers.

Supports the experiment described in
`docs/eval-journal/2026-05-19-retrieval-only-ablation-plan.md`:
given a source `oo-builtin-vector` run, clone its written-memory snapshot
into fresh per-sample workspaces so a no-vector QA-only run can isolate
the retrieval method as the only varying factor.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from lib.artifacts import sha256_file


# Files that must be present in a memory-bearing OpenClaw workspace and
# whose contents define condition A's written memory.
MEMORY_ROOT_FILE = "MEMORY.md"
MEMORY_SUBDIR = "memory"


# Provider/model markers that prove the runtime is still using vector
# retrieval. The plan explicitly requires their absence under condition B.
VECTOR_EVIDENCE_PROVIDERS = {"ollama"}
VECTOR_EVIDENCE_MODELS = {"qwen3-embedding:0.6b"}
QMD_EVIDENCE_VALUES = {"qmd"}


def load_source_manifest(run_dir: Path) -> dict:
    """Read the source backend's manifest.json from a backend run directory."""
    manifest_path = run_dir / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_source_verification(run_dir: Path) -> dict:
    """Read the source backend's memory_write_verification.json."""
    verification_path = run_dir / "memory_write_verification.json"
    return json.loads(verification_path.read_text(encoding="utf-8"))


def source_workspace_for_sample(verification: dict, sample_id: str) -> Path:
    """Locate a sample's workspace by walking its created memory paths."""
    for entry in verification.get("samples", []):
        if entry.get("sample_id") != sample_id:
            continue
        for created in entry.get("created", []):
            candidate = Path(created)
            if candidate.name == MEMORY_ROOT_FILE:
                return candidate.parent
            if candidate.parent.name == MEMORY_SUBDIR:
                return candidate.parent.parent
    raise KeyError(f"sample {sample_id} not present in verification samples")


def derive_source_base_workspace(verification: dict) -> str:
    """Derive the source `<base>-<sample_id>` workspace stem.

    Every sample workspace name must end with `-<sample_id>`; the prefix
    that remains after stripping the sample suffix is the shared base.
    """
    base_candidates: set[str] = set()
    base_parent: Path | None = None
    for entry in verification.get("samples", []):
        sample_id = entry.get("sample_id")
        if not sample_id:
            continue
        sample_ws = source_workspace_for_sample(verification, sample_id)
        suffix = f"-{sample_id}"
        if not sample_ws.name.endswith(suffix):
            raise ValueError(
                f"workspace {sample_ws} does not end with sample suffix {suffix!r}"
            )
        base_candidates.add(sample_ws.name[: -len(suffix)])
        if base_parent is None:
            base_parent = sample_ws.parent
        elif base_parent != sample_ws.parent:
            raise ValueError(
                f"sample workspaces are split across parents: {base_parent} vs {sample_ws.parent}"
            )
    if not base_candidates or base_parent is None:
        raise ValueError("verification has no samples to derive base workspace from")
    if len(base_candidates) != 1:
        raise ValueError(f"sample workspaces share no single base: {sorted(base_candidates)}")
    return str(base_parent / next(iter(base_candidates)))


def list_memory_files(workspace: Path) -> list[Path]:
    """Return relative paths to MEMORY.md and memory/*.md files under `workspace`."""
    relatives: list[Path] = []
    root_file = workspace / MEMORY_ROOT_FILE
    if root_file.is_file():
        relatives.append(Path(MEMORY_ROOT_FILE))
    memory_dir = workspace / MEMORY_SUBDIR
    if memory_dir.is_dir():
        for path in sorted(memory_dir.rglob("*.md")):
            if path.is_file():
                relatives.append(path.relative_to(workspace))
    return relatives


def clone_memory_snapshot(source_ws: Path, dest_ws: Path) -> dict:
    """Copy MEMORY.md and memory/*.md from `source_ws` into `dest_ws`.

    Existing destination files are overwritten so a freshly provisioned
    OpenClaw workspace can be overlaid with condition A's written memory.
    Returns a per-file record with source/destination sha256 hashes.
    """
    if not source_ws.is_dir():
        raise FileNotFoundError(f"source workspace not found: {source_ws}")
    dest_ws.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for rel in list_memory_files(source_ws):
        src = source_ws / rel
        dst = dest_ws / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        records.append(
            {
                "path": str(rel),
                "source": str(src),
                "dest": str(dst),
                "sha256": sha256_file(str(dst)),
                "size": dst.stat().st_size,
            }
        )
    if not records:
        raise ValueError(f"no memory files found under {source_ws}")
    return {
        "source_workspace": str(source_ws),
        "dest_workspace": str(dest_ws),
        "files": records,
    }


def verify_memory_hashes(source_ws: Path, dest_ws: Path) -> dict:
    """Confirm MEMORY.md and memory/*.md hashes match between source and dest."""
    source_files = list_memory_files(source_ws)
    dest_files = list_memory_files(dest_ws)

    failures: list[str] = []
    only_in_source = sorted(set(source_files) - set(dest_files))
    only_in_dest = sorted(set(dest_files) - set(source_files))
    if only_in_source:
        failures.append(
            f"missing in dest: {', '.join(str(p) for p in only_in_source)}"
        )
    if only_in_dest:
        failures.append(
            f"unexpected in dest: {', '.join(str(p) for p in only_in_dest)}"
        )

    matched: list[dict] = []
    mismatched: list[dict] = []
    for rel in sorted(set(source_files) & set(dest_files)):
        src_hash = sha256_file(str(source_ws / rel))
        dst_hash = sha256_file(str(dest_ws / rel))
        record = {"path": str(rel), "source_sha256": src_hash, "dest_sha256": dst_hash}
        if src_hash == dst_hash:
            matched.append(record)
        else:
            mismatched.append(record)
            failures.append(f"hash mismatch for {rel}")

    return {
        "ok": not failures,
        "source_workspace": str(source_ws),
        "dest_workspace": str(dest_ws),
        "matched": matched,
        "mismatched": mismatched,
        "only_in_source": [str(p) for p in only_in_source],
        "only_in_dest": [str(p) for p in only_in_dest],
        "failures": failures,
    }


def iter_session_records(openclaw_home: Path, agent_id: str) -> Iterable[dict]:
    """Yield JSON-decoded session log records for one agent."""
    sessions_dir = openclaw_home / "agents" / agent_id / "sessions"
    if not sessions_dir.exists():
        return
    for path in sorted(sessions_dir.glob("*.jsonl*")):
        if path.name == "sessions.json":
            continue
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield {"path": str(path), "line": line_number, "record": record}


def extract_memory_search_details(record: dict) -> dict | None:
    """Pull a memory_search toolResult details object out of a session record."""
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    if message.get("role") != "toolResult" or message.get("toolName") != "memory_search":
        return None
    details = message.get("details")
    if isinstance(details, dict):
        return details
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            try:
                parsed = json.loads(item.get("text", ""))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def inspect_search_evidence(
    detail_iter: Iterable[dict],
    *,
    forbid_vector: bool,
    forbid_qmd: bool = True,
) -> dict:
    """Classify runtime memory_search details and report any forbidden evidence.

    Each item in `detail_iter` should look like
    `{"path": ..., "line": ..., "details": {...}}`.
    """
    providers: dict[str, int] = {}
    models: dict[str, int] = {}
    backends: dict[str, int] = {}
    failures: list[str] = []
    sample_size = 0
    sample_details: list[dict] = []

    for item in detail_iter:
        details = item.get("details")
        if not isinstance(details, dict):
            continue
        sample_size += 1
        provider = details.get("provider")
        model = details.get("model")
        debug_raw = details.get("debug")
        debug = debug_raw if isinstance(debug_raw, dict) else {}
        backend = debug.get("backend")

        if isinstance(provider, str):
            providers[provider] = providers.get(provider, 0) + 1
        if isinstance(model, str):
            models[model] = models.get(model, 0) + 1
        if isinstance(backend, str):
            backends[backend] = backends.get(backend, 0) + 1

        location = f"{item.get('path', '<unknown>')}:{item.get('line', '?')}"
        if forbid_qmd and (provider in QMD_EVIDENCE_VALUES or model in QMD_EVIDENCE_VALUES):
            failures.append(f"{location}: qmd evidence (provider={provider!r}, model={model!r})")
        if forbid_vector:
            if isinstance(provider, str) and provider in VECTOR_EVIDENCE_PROVIDERS:
                failures.append(f"{location}: vector provider {provider!r}")
            if isinstance(model, str) and model in VECTOR_EVIDENCE_MODELS:
                failures.append(f"{location}: vector model {model!r}")
            store_raw = details.get("store")
            store = store_raw if isinstance(store_raw, dict) else {}
            vector_raw = store.get("vector")
            vector_cfg = vector_raw if isinstance(vector_raw, dict) else {}
            if vector_cfg.get("enabled") is True:
                failures.append(f"{location}: vector store enabled in details")

        if len(sample_details) < 5:
            sample_details.append(
                {
                    "path": item.get("path"),
                    "line": item.get("line"),
                    "provider": provider,
                    "model": model,
                    "backend": backend,
                }
            )

    return {
        "ok": not failures and sample_size > 0,
        "evidence_count": sample_size,
        "providers": providers,
        "models": models,
        "backends": backends,
        "failures": failures,
        "sample_details": sample_details,
    }


def _grade_key(record: dict) -> tuple:
    return (record.get("sample_id"), record.get("qi"))


def paired_buckets(grades_a: Iterable[dict], grades_b: Iterable[dict]) -> dict:
    """Bucket two judge_grades sets by paired (sample_id, qi).

    Reports both-correct, A-only, B-only, both-wrong, A-only-rows (missing
    from B), B-only-rows (missing from A), and per-category deltas.
    """
    a_by_key = {_grade_key(g): g for g in grades_a}
    b_by_key = {_grade_key(g): g for g in grades_b}

    shared = sorted(set(a_by_key) & set(b_by_key), key=lambda k: (str(k[0]), int(k[1] or 0)))
    only_in_a = sorted(set(a_by_key) - set(b_by_key), key=lambda k: (str(k[0]), int(k[1] or 0)))
    only_in_b = sorted(set(b_by_key) - set(a_by_key), key=lambda k: (str(k[0]), int(k[1] or 0)))

    buckets = {
        "both_correct": 0,
        "a_only_correct": 0,
        "b_only_correct": 0,
        "both_wrong": 0,
    }
    per_category: dict[str, dict[str, int]] = {}
    for key in shared:
        a_grade = bool(a_by_key[key].get("grade"))
        b_grade = bool(b_by_key[key].get("grade"))
        if a_grade and b_grade:
            bucket = "both_correct"
        elif a_grade and not b_grade:
            bucket = "a_only_correct"
        elif not a_grade and b_grade:
            bucket = "b_only_correct"
        else:
            bucket = "both_wrong"
        buckets[bucket] += 1

        category = str(a_by_key[key].get("category", ""))
        slot = per_category.setdefault(
            category,
            {
                "both_correct": 0,
                "a_only_correct": 0,
                "b_only_correct": 0,
                "both_wrong": 0,
                "a_correct": 0,
                "b_correct": 0,
                "total": 0,
            },
        )
        slot[bucket] += 1
        slot["total"] += 1
        if a_grade:
            slot["a_correct"] += 1
        if b_grade:
            slot["b_correct"] += 1

    paired_total = sum(buckets.values())
    a_correct = buckets["both_correct"] + buckets["a_only_correct"]
    b_correct = buckets["both_correct"] + buckets["b_only_correct"]
    net_delta = b_correct - a_correct

    return {
        "paired_total": paired_total,
        "a_correct": a_correct,
        "b_correct": b_correct,
        "net_b_minus_a": net_delta,
        "buckets": buckets,
        "per_category": per_category,
        "only_in_a": [{"sample_id": k[0], "qi": k[1]} for k in only_in_a],
        "only_in_b": [{"sample_id": k[0], "qi": k[1]} for k in only_in_b],
    }


def collect_runtime_search_details(
    openclaw_home: Path,
    agent_ids: Iterable[str],
) -> list[dict]:
    """Walk session transcripts and surface memory_search details with locations."""
    collected: list[dict] = []
    for agent_id in agent_ids:
        for item in iter_session_records(openclaw_home, agent_id):
            details = extract_memory_search_details(item["record"])
            if details is None:
                continue
            collected.append(
                {
                    "agent_id": agent_id,
                    "path": item["path"],
                    "line": item["line"],
                    "details": details,
                }
            )
    return collected


def load_judge_grades(path: Path) -> list[dict]:
    """Load a judge_grades.json file as a flat list of grade records."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        grades = data.get("grades")
        if isinstance(grades, list):
            return grades
        return []
    if isinstance(data, list):
        return data
    return []


def render_paired_summary_markdown(
    result: dict,
    *,
    label_a: str = "vector",
    label_b: str = "no-vector",
) -> str:
    """Render a Markdown table summarizing paired_buckets output."""
    buckets = result.get("buckets", {})
    lines = [
        f"| Pair bucket | Count |",
        f"|---|---:|",
        f"| Both correct | {buckets.get('both_correct', 0)} |",
        f"| {label_a}-only correct | {buckets.get('a_only_correct', 0)} |",
        f"| {label_b}-only correct | {buckets.get('b_only_correct', 0)} |",
        f"| Both wrong | {buckets.get('both_wrong', 0)} |",
        f"| Net {label_b} delta | {result.get('net_b_minus_a', 0)} |",
    ]
    per_category = result.get("per_category", {})
    if per_category:
        lines.extend(["", "| Category | Both | A-only | B-only | Both wrong | A correct | B correct |",
                      "|---|---:|---:|---:|---:|---:|---:|"])
        for category in sorted(per_category):
            slot = per_category[category]
            lines.append(
                f"| {category} | {slot['both_correct']} | {slot['a_only_correct']} | "
                f"{slot['b_only_correct']} | {slot['both_wrong']} | {slot['a_correct']} | {slot['b_correct']} |"
            )
    return "\n".join(lines)


def collect_sample_ids(verification: dict) -> list[str]:
    """Return sample IDs present in a verification file, in file order."""
    return [entry["sample_id"] for entry in verification.get("samples", []) if entry.get("sample_id")]


__all__ = [
    "MEMORY_ROOT_FILE",
    "MEMORY_SUBDIR",
    "VECTOR_EVIDENCE_MODELS",
    "VECTOR_EVIDENCE_PROVIDERS",
    "QMD_EVIDENCE_VALUES",
    "clone_memory_snapshot",
    "collect_runtime_search_details",
    "collect_sample_ids",
    "derive_source_base_workspace",
    "extract_memory_search_details",
    "inspect_search_evidence",
    "iter_session_records",
    "list_memory_files",
    "load_judge_grades",
    "load_source_manifest",
    "load_source_verification",
    "paired_buckets",
    "render_paired_summary_markdown",
    "source_workspace_for_sample",
    "verify_memory_hashes",
]
