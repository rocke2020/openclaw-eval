"""OpenClaw Responses API client and local session helpers."""

import json
import os
import sys
import time

import requests


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
) -> tuple[str, dict]:
    """Call send_message with retries on failure."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return send_message(base_url, token, user, message, agent=agent)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                print(f"    [retry {attempt + 1}/{retries}] {e}", file=sys.stderr)
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
