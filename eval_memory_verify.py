"""Memory write verification helpers."""

from pathlib import Path

from eval_artifacts import sha256_file


def snapshot_memory_files(workspace: str) -> dict[str, dict]:
    root = Path(workspace).expanduser()
    candidates = [root / "MEMORY.md"]
    memory_dir = root / "memory"
    if memory_dir.exists():
        candidates.extend(p for p in memory_dir.rglob("*.md") if p.is_file())

    snapshot = {}
    for path in candidates:
        if path.exists() and path.is_file():
            stat = path.stat()
            snapshot[str(path)] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(str(path)),
            }
    return snapshot


def diff_memory_snapshots(before: dict, after: dict) -> dict:
    created = sorted(path for path in after if path not in before)
    modified = sorted(
        path
        for path in after
        if path in before and after[path]["sha256"] != before[path]["sha256"]
    )
    unchanged = sorted(path for path in after if path in before and path not in modified)
    return {
        "created": created,
        "modified": modified,
        "unchanged": unchanged,
        "write_detected": bool(created or modified),
    }
