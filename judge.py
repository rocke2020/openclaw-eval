"""
Grade OpenClaw QA responses using LLM judge.

Usage:
    uv run python judge.py output/answers.txt.json
    uv run python judge.py output/answers.txt.json --output output/grades.json
    uv run python judge.py output/answers.txt.json \
        --base-url https://ark.cn-beijing.volces.com/api/v3 \
        --token $ARK_API_KEY \
        --model doubao-seed-2-0-pro-260215
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from eval_artifacts import render_report_html, summarize_judged
from judge_util import grade_answers, load_answers


async def run(
    input_path: str,
    output_path: str | None,
    base_url: str | None,
    token: str | None,
    model: str,
    parallel: int,
) -> None:
    answers = load_answers(input_path)
    print(f"Loaded {len(answers)} answers from {input_path}", file=sys.stderr)

    graded = await grade_answers(
        answers,
        base_url=base_url,
        api_key=token,
        model=model,
        parallel=parallel,
    )
    summary = summarize_judged(graded)

    print(f"\nResults: {summary['correct']}/{summary['total']} correct ({summary['score']:.2%})")

    if len(summary["per_category"]) > 1:
        print("\nPer-category scores:")
        for cat in sorted(summary["per_category"]):
            c = summary["per_category"][cat]
            print(f"  Category {cat}: {c['correct']}/{c['total']} ({c['score']:.2%})")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\nGrades written to {output_path}", file=sys.stderr)
        _maybe_write_report(output_path, summary)


def _maybe_write_report(output_path: str, judge_summary: dict) -> None:
    run_dir = Path(output_path).parent
    manifest_path = run_dir / "manifest.json"
    qa_summary_path = run_dir / "qa_summary.json"
    if not manifest_path.exists() or not qa_summary_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    qa_summary = json.loads(qa_summary_path.read_text(encoding="utf-8"))
    (run_dir / "report.html").write_text(
        render_report_html(manifest, qa_summary, judge_summary),
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description="Grade QA responses with LLM judge")
    parser.add_argument("input", help="Path to answers JSON file")
    parser.add_argument("--output", default=None, help="Path to write grades JSON")
    parser.add_argument(
        "--base-url",
        default=None,
        help="LLM API base URL (or set OPENAI_BASE_URL env var)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="LLM API key (or set OPENAI_API_KEY env var)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="Model name for grading (default: gpt-4o-mini)",
    )
    parser.add_argument("--parallel", type=int, default=8, help="Judge requests in flight")
    args = parser.parse_args()

    asyncio.run(run(args.input, args.output, args.base_url, args.token, args.model, args.parallel))


if __name__ == "__main__":
    main()
