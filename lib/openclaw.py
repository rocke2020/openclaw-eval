"""OpenClaw Responses API client and local session helpers."""

import json
import os
import random
import sys
import time
from typing import Callable

import requests


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable_error(exc: Exception) -> bool:
    """Return True for transient errors worth retrying."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        if response is not None and response.status_code in RETRYABLE_STATUS_CODES:
            return True
    return False


def retry_after_seconds(exc: Exception) -> float | None:
    """Read Retry-After header (seconds) from a 429/503 response, if present."""
    if not isinstance(exc, requests.HTTPError):
        return None
    response = getattr(exc, "response", None)
    if response is None:
        return None
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def extract_response_text(response_json: dict) -> str:
    """Extract assistant text from the /v1/responses API response."""
    try:
        for item in response_json.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return content.get("text", "")
        for item in response_json.get("output", []):
            if "text" in item:
                return item["text"]
            for content in item.get("content", []):
                if "text" in content:
                    return content["text"]
    except (KeyError, TypeError, IndexError):
        pass
    return f"[ERROR: could not extract text from response: {response_json}]"


def send_message_with_retry(
    base_url: str,
    token: str,
    user: str,
    message: str,
    agent: str = "main",
    retries: int = 2,
    backoff_base: float = 1.0,
    reset_between_attempts: Callable[[], None] | None = None,
) -> tuple[str, dict]:
    """Call send_message with classified retries on transient failures.

    Retries only on Timeout, ConnectionError, and HTTPError with status in
    {429, 500, 502, 503, 504}. Auth and 4xx (other than 429) fail fast.

    Backoff: exponential with jitter, honoring Retry-After when present.
    If reset_between_attempts is provided, it's called before each retry —
    use this for QA paths to avoid retrying inside a polluted session.
    """
    last_exc: Exception | None = None
    total_attempts = retries + 1
    for attempt in range(total_attempts):
        try:
            return send_message(base_url, token, user, message, agent=agent)
        except Exception as exc:
            last_exc = exc
            if attempt >= retries or not is_retryable_error(exc):
                raise

            retry_after = retry_after_seconds(exc)
            if retry_after is not None:
                delay = retry_after
            else:
                delay = backoff_base * (2 ** attempt) + random.uniform(0, backoff_base)

            print(
                f"    [retry {attempt + 1}/{retries}] {type(exc).__name__}: {exc} "
                f"(sleeping {delay:.1f}s)",
                file=sys.stderr,
            )
            time.sleep(delay)

            if reset_between_attempts is not None:
                try:
                    reset_between_attempts()
                except Exception as reset_exc:
                    print(f"    [retry-reset] failed: {reset_exc}", file=sys.stderr)
    assert last_exc is not None
    raise last_exc


def send_message(
    base_url: str,
    token: str,
    user: str,
    message: str,
    agent: str = "main",
) -> tuple[str, dict]:
    """Send a single message to the OpenClaw responses API."""
    payload = {
        "model": f"openclaw/{agent}" if agent else "openclaw",
        "input": message,
        "stream": False,
    }
    if user:
        payload["user"] = user

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    resp = requests.post(
        f"{base_url}/v1/responses",
        json=payload,
        headers=headers,
        timeout=300,
    )
    resp.raise_for_status()
    body = resp.json()
    usage = body.get("usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    return extract_response_text(body), usage


def get_session_id(
    agent: str,
    user: str,
    openclaw_home: str | None = None,
) -> str | None:
    """Read the current session ID for the given agent/user from sessions.json."""
    root = os.path.expanduser(openclaw_home or "~/.openclaw")
    sessions_file = os.path.join(root, "agents", agent, "sessions", "sessions.json")
    key = f"agent:{agent}:openresponses-user:{user}"
    try:
        with open(sessions_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"    [reset] sessions file not found: {sessions_file}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"    [reset] could not read session ID: {e}", file=sys.stderr)
        return None

    session_id = data.get(key, {}).get("sessionId")
    if not session_id:
        print(f"    [reset] session key not found: {key}", file=sys.stderr)
    return session_id


def reset_session(
    agent: str,
    session_id: str,
    openclaw_home: str | None = None,
) -> bool:
    """Archive the session .jsonl file by renaming it with a timestamp suffix."""
    root = os.path.expanduser(openclaw_home or "~/.openclaw")
    src = os.path.join(root, "agents", agent, "sessions", f"{session_id}.jsonl")
    dst = f"{src}.{int(time.time())}"
    try:
        os.rename(src, dst)
        print(
            f"    [reset] archived {session_id}.jsonl -> {os.path.basename(dst)}",
            file=sys.stderr,
        )
        return True
    except FileNotFoundError:
        print(f"    [reset] transcript file not found: {src}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"    [reset] could not archive session file: {e}", file=sys.stderr)
        return False
