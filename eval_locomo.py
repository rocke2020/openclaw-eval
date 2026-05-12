"""LoCoMo dataset loading, formatting, and selection helpers."""

import json
import sys


def format_locomo_message(msg: dict) -> str:
    """Format a single LoCoMo message into a natural chat-style string."""
    speaker = msg.get("speaker", "unknown")
    text = msg.get("text", "")
    line = f"{speaker}: {text}"

    blip = msg.get("blip_caption", "")
    if blip:
        line += f"\n[shared image: {blip}]"

    return line


def load_locomo_data(path: str, sample_index: int | None = None) -> list[dict]:
    """Load LoCoMo JSON and optionally filter to one sample."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if sample_index is not None:
        if sample_index < 0 or sample_index >= len(data):
            print(
                f"Error: sample index {sample_index} out of range (0-{len(data) - 1})",
                file=sys.stderr,
            )
            sys.exit(1)
        return [data[sample_index]]
    return data


def default_sample_user(sample_id: str) -> str:
    """Return the default isolated OpenClaw user key for one LoCoMo sample."""
    return f"eval-{sample_id}"


def build_session_messages(
    item: dict,
    session_range: tuple[int, int] | None = None,
    tail: str = "[]",
) -> list[dict]:
    """Build bundled session messages for one LoCoMo sample."""
    conv = item["conversation"]
    speakers = f"{conv['speaker_a']} & {conv['speaker_b']}"

    session_keys = sorted(
        [k for k in conv if k.startswith("session_") and not k.endswith("_date_time")],
        key=lambda k: int(k.split("_")[1]),
    )

    sessions = []
    for sk in session_keys:
        sess_num = int(sk.split("_")[1])
        if session_range:
            lo, hi = session_range
            if sess_num < lo or sess_num > hi:
                continue

        dt_key = f"{sk}_date_time"
        date_time = conv.get(dt_key, "")

        parts = [f"[group chat conversation: {date_time}]"]
        for msg in conv[sk]:
            parts.append(format_locomo_message(msg))
        if tail:
            parts.append(tail)
        combined = "\n\n".join(parts)

        sessions.append(
            {
                "message": combined,
                "meta": {
                    "sample_id": item["sample_id"],
                    "session_key": sk,
                    "date_time": date_time,
                    "speakers": speakers,
                },
            }
        )

    return sessions


def parse_session_range(s: str) -> tuple[int, int]:
    """Parse '1-4' or '3' into (lo, hi) inclusive tuple."""
    if "-" in s:
        lo, hi = s.split("-", 1)
        return int(lo), int(hi)
    n = int(s)
    return n, n


def parse_category_set(value: str | None) -> set[str] | None:
    """Parse a comma-delimited category list."""
    if value is None or value == "":
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def select_qas(
    item: dict,
    include_categories: set[str] | None = None,
    exclude_categories: set[str] | None = None,
    count: int | None = None,
) -> list[dict]:
    """Select QA records with explicit include/exclude category policy."""
    qas = list(item.get("qa", []))
    if include_categories is not None:
        qas = [q for q in qas if str(q.get("category", "")) in include_categories]
    if exclude_categories is not None:
        qas = [q for q in qas if str(q.get("category", "")) not in exclude_categories]
    if count is not None:
        qas = qas[:count]
    return qas


def dataset_stats(samples: list[dict], selected_samples: list[dict] | None = None) -> dict:
    """Return basic dataset counts for manifests."""
    selected = selected_samples if selected_samples is not None else samples
    return {
        "dataset_sample_count": len(samples),
        "dataset_session_count": sum(_session_count(item) for item in samples),
        "dataset_qa_count_total": sum(len(item.get("qa", [])) for item in samples),
        "selected_sample_count": len(selected),
        "selected_session_count": sum(_session_count(item) for item in selected),
        "selected_qa_count_total": sum(len(item.get("qa", [])) for item in selected),
    }


def _session_count(item: dict) -> int:
    conv = item.get("conversation", {})
    return len(
        [k for k in conv if k.startswith("session_") and not k.endswith("_date_time")]
    )
