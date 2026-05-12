"""
OpenClaw response evaluator.

Modes:
  ingest   Load conversations into a memory backend.
  qa       Run QA questions and write judge-compatible answers.
  compare  Run the same strict artifact contract for multiple backends.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

from eval_artifacts import (
    build_manifest,
    ensure_run_dir,
    render_comparison_report_html,
    summarize_usage,
    write_answers,
    write_json,
    write_jsonl,
    write_manifest,
)
from eval_backends import backend_run_dir, build_backend
from eval_locomo import (
    build_session_messages,
    dataset_stats,
    default_sample_user,
    format_locomo_message,
    load_locomo_data,
    parse_category_set,
    parse_session_range,
    select_qas,
)
from eval_memory_verify import diff_memory_snapshots, snapshot_memory_files
from eval_openclaw import (
    extract_response_text,
    get_session_id,
    reset_session,
    send_message,
    send_message_with_retry,
)


def parse_test_file(path: str) -> list[dict]:
    """Parse txt test file into sessions."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    raw_sessions = content.split("---\n")
    sessions = []
    for raw in raw_sessions:
        lines = [line for line in raw.strip().splitlines() if line.strip()]
        if not lines:
            continue
        messages = []
        evals = []
        for line in lines:
            if line.startswith("eval:"):
                evals.append(line[len("eval:") :].strip())
            else:
                messages.append(line)
        if messages or evals:
            sessions.append({"messages": messages, "evals": evals})
    return sessions


def _call_ingest(args, user_key: str, message: str) -> tuple[str, dict]:
    backend = getattr(args, "backend", None)
    if backend is not None:
        return backend.ingest(user_key, message)
    if getattr(args, "viking", False):
        from eval_openviking import add_memory

        result = add_memory(
            message,
            getattr(args, "openviking_account", None),
            user_key,
            getattr(args, "openviking_agent_id", "eval-locomo-openviking"),
        )
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"].strip() or "ov add-memory failed")
        return "[viking] saved", result
    return send_message(args.base_url, args.token, user_key, message, agent=args.agent)


def _call_answer(args, user_key: str, question: str) -> tuple[str, dict]:
    backend = getattr(args, "backend", None)
    if backend is not None:
        return backend.answer(user_key, question)
    return send_message_with_retry(
        args.base_url,
        args.token,
        user_key,
        question,
        agent=args.agent,
    )


def _maybe_reset_session(args, user_key: str) -> None:
    if getattr(args, "backend", None) is not None and getattr(args.backend, "backend_kind", "") != "openclaw":
        return
    if getattr(args, "viking", False):
        return
    session_id = get_session_id(args.agent, user_key, args.openclaw_home)
    if session_id:
        reset_session(args.agent, session_id, args.openclaw_home)


def _write_run_manifest(args, samples: list[dict], backend_config: dict | None = None) -> dict | None:
    if not getattr(args, "run_dir", None):
        return None
    all_samples = load_locomo_data(args.input, None)
    manifest = build_manifest(args, samples, dataset_stats(all_samples, samples), backend_config)
    manifest_path = ensure_run_dir(args.run_dir) / "manifest.json"
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if (
            manifest["memory_write_verification"] == "not_configured"
            and existing.get("memory_write_verification") == "configured"
        ):
            manifest["memory_write_verification"] = "configured"
    write_manifest(manifest_path, manifest)
    return manifest


def run_ingest(args: argparse.Namespace) -> list[dict]:
    """Load conversations into OpenClaw/OpenViking."""
    session_range = parse_session_range(args.sessions) if args.sessions else None
    run_dir = ensure_run_dir(args.run_dir) if args.run_dir else None

    if args.input.endswith(".json"):
        samples = load_locomo_data(args.input, args.sample)
        results = []
        verification = []

        backend_config = args.backend.manifest_config() if getattr(args, "backend", None) else None
        _write_run_manifest(args, samples, backend_config)

        for item in samples:
            sample_id = item["sample_id"]
            user_key = args.user or default_sample_user(sample_id)
            sessions = build_session_messages(item, session_range, tail=args.tail)

            print(f"\n=== Sample {sample_id} ===", file=sys.stderr)
            print(f"    user: {user_key}", file=sys.stderr)
            print(f"    {len(sessions)} session(s) to ingest", file=sys.stderr)

            before = (
                snapshot_memory_files(args.agent_workspace)
                if args.agent_workspace
                else None
            )

            for sess in sessions:
                meta = sess["meta"]
                msg = sess["message"]
                label = f"{meta['session_key']} ({meta['date_time']})"
                preview = msg.replace("\n", " | ")[:80]
                print(f"  [{label}] {preview}...", file=sys.stderr)

                try:
                    reply, usage = _call_ingest(args, user_key, msg)
                    print(
                        f"    -> {reply[:80]}{'...' if len(reply) > 80 else ''}",
                        file=sys.stderr,
                    )
                except Exception as e:
                    reply = f"[ERROR] {e}"
                    usage = {}
                    print(f"    -> {reply}", file=sys.stderr)

                record = {
                    "sample_id": sample_id,
                    "session": meta["session_key"],
                    "user": user_key,
                    "agent": args.agent,
                    "reply": reply,
                    "usage": usage,
                }
                results.append(record)
                _maybe_reset_session(args, user_key)

            if args.agent_workspace:
                after = snapshot_memory_files(args.agent_workspace)
                diff = diff_memory_snapshots(before or {}, after)
                verification.append({"sample_id": sample_id, "user": user_key, **diff})

        summary = {
            "total": len(results),
            "usage": summarize_usage(results),
        }

        if run_dir:
            write_jsonl(run_dir / "ingest.jsonl", results)
            write_json(run_dir / "ingest_summary.json", summary)
            memory_payload = (
                {"status": "ok", "samples": verification}
                if args.agent_workspace
                else {"status": "not_configured", "samples": []}
            )
            write_json(run_dir / "memory_write_verification.json", memory_payload)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                for r in results:
                    f.write(f"[{r['sample_id']}/{r['session']}] user={r['user']}\n")
                    f.write(f"  {r['reply']}\n\n")
            with open(args.output + ".json", "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            print(f"Results written to {args.output}", file=sys.stderr)

        return results

    sessions = parse_test_file(args.input)
    print(f"Running {len(sessions)} session(s)", file=sys.stderr)

    results = []
    for idx, session in enumerate(sessions, start=1):
        session_key = args.user or "eval-1"
        print(f"--- Session {idx} (user={session_key}) ---", file=sys.stderr)
        turns = []
        for msg in session["messages"]:
            print(f"  [user] {msg}", file=sys.stderr)
            try:
                reply, _usage = _call_ingest(args, session_key, msg)
                print(
                    f"  [assistant] {reply[:80]}{'...' if len(reply) > 80 else ''}",
                    file=sys.stderr,
                )
                turns.append(("user", msg))
                turns.append(("assistant", reply))
            except Exception as e:
                print(f"  [ERROR] {e}", file=sys.stderr)
                turns.append(("user", msg))
                turns.append(("error", str(e)))
                break
        _maybe_reset_session(args, session_key)
        results.append({"index": idx, "turns": turns, "evals": session["evals"]})

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            for r in results:
                f.write(f"=== Session {r['index']} ===\n")
                for role, text in r["turns"]:
                    f.write(f"[{role}] {text}\n")
                for ev in r["evals"]:
                    f.write(f"[eval] {ev}\n")
                f.write("\n")
    return results


async def run_sample_qa(
    item: dict,
    sample_idx: int,
    args: argparse.Namespace,
    semaphore: asyncio.Semaphore,
) -> tuple[list[dict], dict]:
    """Process QA for a single sample. Returns (records, sample_usage)."""
    sample_id = item["sample_id"]
    user_key = args.user or default_sample_user(sample_id)
    include_categories = parse_category_set(args.include_categories)
    exclude_categories = parse_category_set(args.exclude_categories)
    qas = select_qas(item, include_categories, exclude_categories, args.count)

    sample_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    records = []

    async with semaphore:
        print(f"\n=== Sample {sample_id} [{sample_idx}] (user={user_key}) ===", file=sys.stderr)
        print(f"    Running {len(qas)} QA question(s)...", file=sys.stderr)

        for qi, qa in enumerate(qas, start=1):
            question = qa["question"]
            expected = str(qa["answer"])
            category = qa.get("category", "")
            evidence = qa.get("evidence", [])

            print(
                f"  [{sample_idx}] Q{qi}/{len(qas)}: {question[:60]}{'...' if len(question) > 60 else ''}",
                file=sys.stderr,
            )

            try:
                response, usage = await asyncio.to_thread(_call_answer, args, user_key, question)
                print(
                    f"  [{sample_idx}]   A: {response[:60]}{'...' if len(response) > 60 else ''}",
                    file=sys.stderr,
                )
                for k in sample_usage:
                    sample_usage[k] += usage.get(k, 0)
            except Exception as e:
                response = f"[ERROR] {e}"
                usage = {}
                print(f"  [{sample_idx}]   A: {response}", file=sys.stderr)

            _maybe_reset_session(args, user_key)

            records.append(
                {
                    "sample_id": sample_id,
                    "sample_idx": sample_idx,
                    "qi": qi,
                    "question": question,
                    "expected": expected,
                    "response": response,
                    "category": category,
                    "evidence": evidence,
                    "user": user_key,
                    "agent": args.agent,
                    "usage": usage,
                }
            )

    return records, sample_usage


def run_qa(args: argparse.Namespace) -> list[dict]:
    """QA only: send questions and get responses."""
    if not args.input.endswith(".json"):
        print("Error: QA mode only works with LoCoMo JSON files", file=sys.stderr)
        sys.exit(1)

    samples = load_locomo_data(args.input, args.sample)
    backend_config = args.backend.manifest_config() if getattr(args, "backend", None) else None
    _write_run_manifest(args, samples, backend_config)

    parallel = min(args.parallel, 10)
    print(f"    user: {args.user or 'per-sample default'}", file=sys.stderr)
    print(f"    agent: {args.agent}", file=sys.stderr)
    print(f"    parallel: {parallel}", file=sys.stderr)

    async def _run():
        semaphore = asyncio.Semaphore(parallel)
        tasks = [
            run_sample_qa(item, idx + 1, args, semaphore)
            for idx, item in enumerate(samples)
        ]
        return await asyncio.gather(*tasks)

    results_list = asyncio.run(_run())

    all_records = []
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for records, sample_usage in results_list:
        all_records.extend(records)
        for key in total_usage:
            total_usage[key] += sample_usage[key]

    summary = {
        "total": len(all_records),
        "usage": total_usage,
        "include_categories": args.include_categories,
        "exclude_categories": args.exclude_categories,
    }
    print(
        f"\n    total tokens: in={total_usage['input_tokens']} out={total_usage['output_tokens']} total={total_usage['total_tokens']}",
        file=sys.stderr,
    )

    if args.run_dir:
        run_dir = ensure_run_dir(args.run_dir)
        write_jsonl(run_dir / "qa.jsonl", all_records)
        write_json(run_dir / "qa_summary.json", summary)
        write_answers(run_dir / "answers.json", all_records, summary)
        if args.canary:
            canary_records = run_canaries(samples, args)
            write_jsonl(run_dir / "canary.jsonl", canary_records)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write("=== TOTAL USAGE ===\n")
            f.write(f"input_tokens: {total_usage['input_tokens']}\n")
            f.write(f"output_tokens: {total_usage['output_tokens']}\n")
            f.write(f"total_tokens: {total_usage['total_tokens']}\n")
        with open(args.output + ".json", "w", encoding="utf-8") as f:
            json.dump({"results": all_records, "summary": summary}, f, indent=2, ensure_ascii=False)
        print(f"Summary written to {args.output}", file=sys.stderr)
    elif not args.run_dir:
        print("\nDone (no output file requested).", file=sys.stderr)

    return all_records


def select_canary_pairs(samples: list[dict], canary_count: int) -> list[dict]:
    """Pair each sample's user with questions from the next selected sample."""
    if len(samples) < 2:
        return []
    pairs = []
    for idx, target in enumerate(samples):
        source = samples[(idx + 1) % len(samples)]
        for qa in source.get("qa", [])[:canary_count]:
            pairs.append(
                {
                    "type": "contamination_canary",
                    "source_sample_id": source["sample_id"],
                    "target_sample_id": target["sample_id"],
                    "target_user": default_sample_user(target["sample_id"]),
                    "question": qa["question"],
                    "expected": str(qa["answer"]),
                    "category": qa.get("category", ""),
                }
            )
    return pairs


def run_canaries(samples: list[dict], args: argparse.Namespace) -> list[dict]:
    records = []
    for pair in select_canary_pairs(samples, args.canary_count):
        target_user = args.user or pair["target_user"]
        try:
            response, usage = _call_answer(args, target_user, pair["question"])
        except Exception as e:
            response = f"[ERROR] {e}"
            usage = {}
        records.append({**pair, "target_user": target_user, "response": response, "usage": usage})
        _maybe_reset_session(args, target_user)
    return records


def run_compare(args: argparse.Namespace) -> None:
    backends = [item.strip() for item in args.backends.split(",") if item.strip()]
    group_dir = ensure_run_dir(args.run_group)
    summaries = []

    for backend_id in backends:
        backend = build_backend(backend_id, args)
        run_args = copy.copy(args)
        run_args.backend = backend
        run_args.backend_id = backend.backend_id
        run_args.backend_kind = backend.backend_kind
        run_args.agent = getattr(backend, "agent", args.agent)
        run_args.run_dir = str(backend_run_dir(args.run_group, backend_id))
        run_args.run_group_id = group_dir.name
        ensure_run_dir(run_args.run_dir)

        if backend.backend_kind == "openviking":
            run_args.viking = True

        print(f"\n=== Backend {backend_id}: ingest ===", file=sys.stderr)
        run_ingest(run_args)
        print(f"\n=== Backend {backend_id}: qa ===", file=sys.stderr)
        records = run_qa(run_args)

        verification_path = Path(run_args.run_dir) / "memory_write_verification.json"
        memory_verified = False
        if verification_path.exists():
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            memory_verified = any(
                item.get("write_detected") for item in verification.get("samples", [])
            )
        reasons = []
        if run_args.agent == "main":
            reasons.append("eval agent is main")
        if not memory_verified:
            reasons.append("memory write verification failed or is not configured")
        summary = {
            "backend_id": backend_id,
            "backend_kind": backend.backend_kind,
            "publishable": not reasons,
            "non_publishable_reasons": reasons,
            "qa_total": len(records),
            "judge_score": 0.0,
            "per_category": {},
            "memory_write_verified": memory_verified,
            "canary_leakage_count": 0,
            "total_ingest_tokens": None,
            "total_qa_tokens": summarize_usage(records).get("total_tokens"),
        }
        summaries.append(summary)

        if reasons and not args.allow_non_publishable:
            raise SystemExit(
                f"Backend {backend_id} is non-publishable: {'; '.join(reasons)}"
            )

    group_manifest = {
        "run_group_id": group_dir.name,
        "backends": backends,
        "baseline_backend": "oo-builtin",
    }
    write_json(group_dir / "comparison_summary.json", {"backends": summaries})
    (group_dir / "comparison_report.html").write_text(
        render_comparison_report_html(group_manifest, summaries),
        encoding="utf-8",
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", help="Path to test file (.txt or .json)")
    parser.add_argument("--output", default=None, help="Path to legacy output file")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:19002",
        help="OpenClaw gateway base URL (default: http://127.0.0.1:19002)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("OPENCLAW_GATEWAY_TOKEN", "xxx"),
        help="Auth token (or set OPENCLAW_GATEWAY_TOKEN env var)",
    )
    parser.add_argument("--agent", default="eval-locomo", help="OpenClaw agent id to evaluate")
    parser.add_argument("--openclaw-home", default=None, help="OpenClaw home directory for session lookup")
    parser.add_argument("--openclaw-profile", default="eval", help="OpenClaw profile name for manifests")
    parser.add_argument("--sample", type=int, default=None, help="LoCoMo sample index")
    parser.add_argument("--sessions", default=None, help="LoCoMo session range, e.g. '1-4'")
    parser.add_argument(
        "--tail",
        default="[remember what's said, keep existing memory]",
        help="Tail message appended after conversation messages per session",
    )
    parser.add_argument("--count", type=int, default=None, help="QA question limit")
    parser.add_argument("--user", default=None, help="Override OpenClaw user key")
    parser.add_argument("-p", "--parallel", type=int, default=1, metavar="N", help="QA samples in flight")
    parser.add_argument("--run-dir", default=None, help="Directory for reproducible eval artifacts")
    parser.add_argument("--agent-workspace", default=None, help="Eval agent workspace path for memory write checks")
    parser.add_argument("--include-categories", default=None, help="Comma-delimited QA categories to include")
    parser.add_argument("--exclude-categories", default=None, help="Comma-delimited QA categories to exclude")
    parser.add_argument("--viking", action="store_true", default=False, help="Use OpenViking add-memory for ingest")
    parser.add_argument("--openviking-account", default=None, help="OpenViking account")
    parser.add_argument("--openviking-user", default=None, help="OpenViking user for manifests")
    parser.add_argument("--openviking-agent-id", default="eval-locomo-openviking", help="OpenViking agent id")
    parser.add_argument("--judge-model", default=None, help="Judge model recorded in manifest")
    parser.add_argument("--judge-base-url", default=None, help="Judge base URL recorded in manifest")
    parser.add_argument("--canary", action="store_true", default=False, help="Run cross-sample contamination canaries")
    parser.add_argument("--canary-count", type=int, default=3, help="Canary questions per sample pair")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate memory-backed responses")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Load conversations")
    add_common_args(ingest_parser)

    qa_parser = subparsers.add_parser("qa", help="Run QA")
    add_common_args(qa_parser)

    compare_parser = subparsers.add_parser("compare", help="Run backend comparison")
    add_common_args(compare_parser)
    compare_parser.add_argument("--run-group", required=True, help="Comparison run group directory")
    compare_parser.add_argument(
        "--backends",
        default="oo-builtin,oo-qmd,openviking",
        help="Comma-delimited backend ids",
    )
    compare_parser.add_argument("--builtin-agent", default="eval-locomo-builtin")
    compare_parser.add_argument("--qmd-agent", default="eval-locomo-qmd")
    compare_parser.add_argument("--allow-non-publishable", action="store_true", default=False)

    args = parser.parse_args()

    if not args.token and not getattr(args, "viking", False):
        print("Error: --token or OPENCLAW_GATEWAY_TOKEN env var is required", file=sys.stderr)
        sys.exit(1)

    if args.mode == "ingest":
        run_ingest(args)
    elif args.mode == "qa":
        run_qa(args)
    elif args.mode == "compare":
        run_compare(args)


if __name__ == "__main__":
    main()
