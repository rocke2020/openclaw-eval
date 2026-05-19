#!/usr/bin/env python3
"""Retrieval-only ablation orchestrator.

Implements the experiment in
`docs/eval-journal/2026-05-19-retrieval-only-ablation-plan.md`:

    clone   Provision fresh per-sample agents and overlay condition A's
            written-memory snapshot so condition B starts from the exact
            same MEMORY.md + memory/*.md state.

    verify  Re-check the source vs destination memory hash gate. Safe to
            call repeatedly before QA starts.

    smoke   Inspect a destination run's per-sample agent transcripts and
            assert no QMD and no vector retrieval evidence appear. The
            plan requires this gate before the full QA-only run.

    compare Bucket two judge_grades.json files paired by (sample_id, qi)
            into both-correct / a-only / b-only / both-wrong, with
            category deltas.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.ablation import (  # noqa: E402
    clone_memory_snapshot,
    collect_runtime_search_details,
    collect_sample_ids,
    derive_source_base_workspace,
    inspect_search_evidence,
    load_judge_grades,
    load_source_manifest,
    load_source_verification,
    paired_buckets,
    render_paired_summary_markdown,
    source_workspace_for_sample,
    verify_memory_hashes,
)
from lib.agent_provision import (  # noqa: E402
    provision_sample_agents,
    sample_agent_id,
    sample_workspace,
)
from lib.artifacts import write_json  # noqa: E402


DEFAULT_DEST_BASE_AGENT_PREFIX = "eval-locomo-retrieval-ablation-builtin-from-vector"
DEFAULT_DEST_WORKSPACE_PARENT = Path.home() / ".openclaw-eval"
DEFAULT_DEST_WORKSPACE_PREFIX = "workspace-retrieval-ablation-builtin-from-vector"


def _git_clean(repo_root: Path) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, f"git status failed: {result.stderr.strip() or result.stdout.strip()}"
    return not result.stdout.strip(), result.stdout.strip()


def _resolve_source_run_dir(path: str) -> Path:
    run_dir = Path(path).expanduser().resolve()
    if not run_dir.is_dir():
        raise SystemExit(f"source run dir not found: {run_dir}")
    if not (run_dir / "manifest.json").is_file():
        raise SystemExit(f"manifest.json missing under {run_dir}")
    if not (run_dir / "memory_write_verification.json").is_file():
        raise SystemExit(f"memory_write_verification.json missing under {run_dir}")
    return run_dir


def _default_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def cmd_clone(args: argparse.Namespace) -> int:
    repo_root = ROOT
    if args.require_clean_git:
        clean, status = _git_clean(repo_root)
        if not clean:
            raise SystemExit(
                "git working tree must be clean before clone:\n" + status
            )

    source_run_dir = _resolve_source_run_dir(args.source_run_dir)
    manifest = load_source_manifest(source_run_dir)
    verification = load_source_verification(source_run_dir)
    sample_ids = collect_sample_ids(verification)
    if not sample_ids:
        raise SystemExit("source verification has no samples")
    if args.sample_ids:
        wanted = [s.strip() for s in args.sample_ids.split(",") if s.strip()]
        missing = [s for s in wanted if s not in sample_ids]
        if missing:
            raise SystemExit(f"sample(s) not in source verification: {missing}")
        sample_ids = wanted

    source_base_workspace = derive_source_base_workspace(verification)
    source_base_agent = manifest.get("openclaw_agent")
    if not source_base_agent:
        raise SystemExit("source manifest is missing openclaw_agent")

    timestamp = args.timestamp or _default_timestamp()
    dest_base_agent = args.dest_base_agent or f"{DEFAULT_DEST_BASE_AGENT_PREFIX}-{timestamp}"
    dest_base_workspace = args.dest_base_workspace or str(
        DEFAULT_DEST_WORKSPACE_PARENT / f"{DEFAULT_DEST_WORKSPACE_PREFIX}-{timestamp}"
    )

    dest_existing_with_memory = []
    for sample_id in sample_ids:
        dest_ws = Path(sample_workspace(dest_base_workspace, sample_id))
        if (dest_ws / "MEMORY.md").exists():
            dest_existing_with_memory.append(str(dest_ws))
    if dest_existing_with_memory and not args.allow_existing_memory:
        raise SystemExit(
            "destination workspaces already have MEMORY.md "
            "(pass --allow-existing-memory to overwrite):\n  "
            + "\n  ".join(dest_existing_with_memory)
        )

    if not args.skip_provision:
        provision_sample_agents(
            profile=args.profile,
            base_agent=dest_base_agent,
            base_workspace=dest_base_workspace,
            sample_ids=sample_ids,
        )

    clone_records: list[dict] = []
    for sample_id in sample_ids:
        source_ws = source_workspace_for_sample(verification, sample_id)
        dest_ws = Path(sample_workspace(dest_base_workspace, sample_id))
        clone_record = clone_memory_snapshot(source_ws, dest_ws)
        verification_record = verify_memory_hashes(source_ws, dest_ws)
        clone_records.append(
            {
                "sample_id": sample_id,
                "source_agent": sample_agent_id(source_base_agent, sample_id),
                "dest_agent": sample_agent_id(dest_base_agent, sample_id),
                "source_workspace": str(source_ws),
                "dest_workspace": str(dest_ws),
                "files": clone_record["files"],
                "hash_verification": verification_record,
            }
        )

    failures = [
        rec["sample_id"]
        for rec in clone_records
        if not rec["hash_verification"]["ok"]
    ]
    if failures:
        raise SystemExit(
            f"hash verification failed for samples: {', '.join(failures)}"
        )

    clone_manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "timestamp": timestamp,
        "source_run_dir": str(source_run_dir),
        "source_base_agent": source_base_agent,
        "source_base_workspace": source_base_workspace,
        "source_openclaw_version": manifest.get("openclaw_version"),
        "source_backend_id": manifest.get("backend_id"),
        "dest_base_agent": dest_base_agent,
        "dest_base_workspace": dest_base_workspace,
        "profile": args.profile,
        "sample_ids": sample_ids,
        "clones": clone_records,
    }

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(out_path, clone_manifest)
        print(f"clone manifest written to {out_path}", file=sys.stderr)

    print(json.dumps(clone_manifest, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    manifest_path = Path(args.clone_manifest).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    records = []
    failures = []
    for clone in manifest.get("clones", []):
        source_ws = Path(clone["source_workspace"])
        dest_ws = Path(clone["dest_workspace"])
        verification = verify_memory_hashes(source_ws, dest_ws)
        records.append({"sample_id": clone["sample_id"], "verification": verification})
        if not verification["ok"]:
            failures.append(clone["sample_id"])

    payload = {
        "ok": not failures,
        "clone_manifest": str(manifest_path),
        "results": records,
        "failed_samples": failures,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    manifest_path = Path(args.clone_manifest).expanduser().resolve()
    clone_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    openclaw_home = Path(args.openclaw_home).expanduser().resolve()

    sample_ids = args.sample_ids.split(",") if args.sample_ids else clone_manifest.get("sample_ids", [])
    sample_ids = [s.strip() for s in sample_ids if s.strip()]
    if not sample_ids:
        raise SystemExit("no samples to inspect")

    dest_base_agent = clone_manifest.get("dest_base_agent")
    if not dest_base_agent:
        raise SystemExit("clone manifest missing dest_base_agent")

    agent_ids = [sample_agent_id(dest_base_agent, sample_id) for sample_id in sample_ids]
    details = collect_runtime_search_details(openclaw_home, agent_ids)
    report = inspect_search_evidence(
        details,
        forbid_vector=not args.allow_vector,
        forbid_qmd=True,
    )
    payload = {
        "openclaw_home": str(openclaw_home),
        "agent_ids": agent_ids,
        "forbid_vector": not args.allow_vector,
        "report": report,
    }
    print(json.dumps(payload, indent=2))
    return 0 if report["ok"] else 1


def cmd_compare(args: argparse.Namespace) -> int:
    grades_a = load_judge_grades(Path(args.run_a).expanduser().resolve())
    grades_b = load_judge_grades(Path(args.run_b).expanduser().resolve())
    if not grades_a or not grades_b:
        raise SystemExit("could not load grades from one of the inputs")

    result = paired_buckets(grades_a, grades_b)
    payload = {
        "run_a": args.run_a,
        "run_b": args.run_b,
        "label_a": args.label_a,
        "label_b": args.label_b,
        **result,
    }

    if args.output:
        write_json(Path(args.output).expanduser().resolve(), payload)
    print(json.dumps(payload, indent=2))

    if args.markdown:
        md_path = Path(args.markdown).expanduser().resolve()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            render_paired_summary_markdown(result, label_a=args.label_a, label_b=args.label_b)
            + "\n",
            encoding="utf-8",
        )
        print(f"markdown summary written to {md_path}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    clone = sub.add_parser("clone", help="Provision dest agents and overlay condition A memory")
    clone.add_argument("source_run_dir", help="Path to source backend run dir (e.g. .../oo-builtin-vector/)")
    clone.add_argument("--profile", default="eval", help="OpenClaw profile name")
    clone.add_argument("--timestamp", default=None, help="Override timestamp used in dest base names")
    clone.add_argument("--dest-base-agent", default=None, help="Override destination base agent id")
    clone.add_argument("--dest-base-workspace", default=None, help="Override destination base workspace path")
    clone.add_argument("--sample-ids", default=None, help="Comma-delimited subset of source sample IDs")
    clone.add_argument("--output", default=None, help="Write clone manifest JSON to this path")
    clone.add_argument(
        "--skip-provision", action="store_true", default=False,
        help="Do not call openclaw agents add; assume dest agents already exist",
    )
    clone.add_argument(
        "--allow-existing-memory", action="store_true", default=False,
        help="Overwrite MEMORY.md in destinations that already have one (use for resumes)",
    )
    clone.add_argument(
        "--no-git-clean-check", dest="require_clean_git", action="store_false", default=True,
        help="Skip the git working-tree-clean gate",
    )
    clone.set_defaults(func=cmd_clone)

    verify = sub.add_parser("verify", help="Re-verify source vs destination memory hashes")
    verify.add_argument("clone_manifest", help="Path to clone manifest JSON")
    verify.set_defaults(func=cmd_verify)

    smoke = sub.add_parser("smoke", help="Assert runtime memory_search evidence is no-vector")
    smoke.add_argument("clone_manifest", help="Path to clone manifest JSON")
    smoke.add_argument(
        "--openclaw-home",
        default=str(Path.home() / ".openclaw"),
        help="OpenClaw home directory (default: ~/.openclaw)",
    )
    smoke.add_argument("--sample-ids", default=None, help="Comma-delimited subset to inspect")
    smoke.add_argument(
        "--allow-vector", action="store_true", default=False,
        help="Do not treat ollama / qwen3-embedding evidence as failures",
    )
    smoke.set_defaults(func=cmd_smoke)

    compare = sub.add_parser("compare", help="Paired comparison of two judge_grades.json files")
    compare.add_argument("run_a", help="judge_grades.json for condition A (vector)")
    compare.add_argument("run_b", help="judge_grades.json for condition B (no-vector)")
    compare.add_argument("--label-a", default="vector", help="Label for condition A in summary")
    compare.add_argument("--label-b", default="no-vector", help="Label for condition B in summary")
    compare.add_argument("--output", default=None, help="Write paired-comparison JSON to this path")
    compare.add_argument("--markdown", default=None, help="Write a Markdown table summary to this path")
    compare.set_defaults(func=cmd_compare)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
