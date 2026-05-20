"""Per-row OpenClaw profile config orchestration.

The OV plugin reproduction needs to mutate the eval profile between backends:

  - oc-ov-plugin-bare:       memory-core disabled, contextEngine=openviking
  - oc-ov-plugin-augmented:  memory-core enabled,  contextEngine=openviking
  - (existing oo-* rows):    memory-core enabled,  contextEngine=legacy (or unset)

This module exposes the smallest set of primitives needed:

  read_profile_config(profile, key) -> JSON-decoded value or None
  set_profile_config(profile, key, value) -> CompletedProcess
  restart_gateway(profile) -> CompletedProcess
  wait_gateway_ready(profile, timeout_s) -> dict (pid + base_url + ready)
  snapshot_profile_keys(profile, keys) -> contextmanager{dict}

Codex flagged that snapshot-restore alone can race a previous gateway process.
`wait_gateway_ready` captures PID + base_url evidence after every restart so
the caller can assert in the manifest that the mutations apply to a known
live process.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any


def _openclaw_bin() -> str:
    path = shutil.which("openclaw")
    if not path:
        raise RuntimeError("openclaw binary not found on PATH")
    return path


def read_profile_config(profile: str, key: str) -> Any:
    """Return the JSON-decoded value at `key` under `profile`, or None when absent."""
    result = subprocess.run(
        [_openclaw_bin(), "--profile", profile, "config", "get", key, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        text = (result.stdout or "") + (result.stderr or "")
        if "Config path not found" in text:
            return None
        raise RuntimeError(
            f"openclaw --profile {profile} config get {key} failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    body = (result.stdout or "").strip()
    # CLI may prefix with "Config warnings" block; find the JSON body at end.
    if not body:
        return None
    # Find the last JSON value: either {...}, [...], "..." or scalar.
    # Prefer last line; fall back to whole body.
    last_line = body.splitlines()[-1].strip()
    candidates = [last_line, body]
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"cannot decode JSON from config get {key}: {body!r}")


def set_profile_config(profile: str, key: str, value: Any) -> subprocess.CompletedProcess:
    """Set `key=value` under `profile`. `value` must be JSON-serialisable."""
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        value_str = json.dumps(value)
    elif isinstance(value, str):
        # OpenClaw `config set` expects JSON for strings — wrap with quotes.
        value_str = json.dumps(value)
    else:
        value_str = json.dumps(value)
    result = subprocess.run(
        [_openclaw_bin(), "--profile", profile, "config", "set", key, value_str],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"openclaw --profile {profile} config set {key} failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result


def restart_gateway(profile: str) -> subprocess.CompletedProcess:
    """Restart the gateway under `profile`. Does not wait for readiness."""
    return subprocess.run(
        [_openclaw_bin(), "--profile", profile, "gateway", "restart"],
        capture_output=True,
        text=True,
        check=False,
    )


def _read_status_text(profile: str) -> str:
    result = subprocess.run(
        [_openclaw_bin(), "--profile", profile, "gateway", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (result.stdout or "") + "\n" + (result.stderr or "")


def _extract_pid_from_status(text: str) -> int | None:
    for line in text.splitlines():
        if "running (pid" in line:
            try:
                tail = line.split("running (pid", 1)[1]
                pid_str = tail.split(",", 1)[0].strip().rstrip(")")
                return int(pid_str)
            except (ValueError, IndexError):
                continue
        if line.strip().startswith("PID:"):
            try:
                return int(line.split("PID:", 1)[1].strip())
            except ValueError:
                continue
    return None


def wait_gateway_ready(profile: str, base_url: str, timeout_s: float = 30.0) -> dict:
    """Block until the gateway under `profile` responds at `base_url` health.

    Returns {"ready": bool, "pid": int | None, "base_url": str, "elapsed_s": float}.
    Does not raise on timeout; the caller decides how to treat `ready=False`.
    """
    deadline = time.monotonic() + timeout_s
    health_url = base_url.rstrip("/") + "/health"
    ready = False
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2.0) as resp:
                if 200 <= resp.status < 300:
                    ready = True
                    break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    pid = _extract_pid_from_status(_read_status_text(profile))
    return {
        "ready": ready,
        "pid": pid,
        "base_url": base_url,
        "elapsed_s": round(timeout_s - max(0.0, deadline - time.monotonic()), 3),
    }


@contextlib.contextmanager
def snapshot_profile_keys(profile: str, keys: list[str]):
    """Context manager: capture current values for `keys`, restore on exit.

    Restoration runs even when the body raises. Codex flagged restore as
    overclaimed under partial-restart conditions; callers should pair this
    with `wait_gateway_ready` to confirm restoration landed on a healthy
    gateway PID.
    """
    snapshot: dict[str, Any] = {}
    sentinel: dict[str, bool] = {}
    for key in keys:
        try:
            snapshot[key] = read_profile_config(profile, key)
            sentinel[key] = True
        except Exception:
            snapshot[key] = None
            sentinel[key] = False
    try:
        yield snapshot
    finally:
        restore_failures: list[str] = []
        for key in keys:
            if not sentinel.get(key):
                continue
            try:
                if snapshot[key] is None:
                    # Best effort: cannot easily unset, leave as last value.
                    continue
                set_profile_config(profile, key, snapshot[key])
            except Exception as exc:  # pragma: no cover — restore failures rare
                restore_failures.append(f"{key}: {exc}")
        if restore_failures:
            import sys
            print(
                f"WARNING: profile {profile} restore had failures: "
                + "; ".join(restore_failures),
                file=sys.stderr,
            )
