"""Backend registry and comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import shutil
import subprocess
from typing import Protocol

from lib.openclaw import send_message_with_retry
from lib.openviking import add_memory, search

EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH = {
    "provider": "ollama",
    "base_url": "http://127.0.0.1:11434",
    "model": "qwen3-embedding:0.6b",
    "store.vector.enabled": True,
    "query.hybrid.enabled": True,
    "query.hybrid.vectorWeight": 0.8,
    "query.hybrid.textWeight": 0.2,
    "query.hybrid.candidateMultiplier": 6,
}

EXPECTED_OPENCLAW_MEMORY_BACKENDS = {
    "builtin": "builtin",
    "builtin-vector": "builtin-vector",
    "qmd": "qmd",
}


class MemoryBackend(Protocol):
    backend_id: str
    backend_kind: str

    def ingest(self, user: str, message: str, agent: str | None = None) -> tuple[str, dict]: ...

    def answer(self, user: str, question: str, agent: str | None = None) -> tuple[str, dict]: ...

    def manifest_config(self) -> dict: ...

    def publishability_failures(self) -> list[str]: ...


@dataclass
class OpenClawBackend:
    backend_id: str
    base_url: str
    token: str
    agent: str
    expected_memory_backend: str
    actual_memory_backend: str | None = None
    expected_memory_search: dict | None = None
    actual_memory_search: dict | None = None
    memory_search_failures: list[str] | None = None
    backend_kind: str = "openclaw"

    def ingest(self, user: str, message: str, agent: str | None = None) -> tuple[str, dict]:
        return send_message_with_retry(
            self.base_url, self.token, user, message, agent=agent or self.agent,
        )

    def answer(self, user: str, question: str, agent: str | None = None) -> tuple[str, dict]:
        return send_message_with_retry(
            self.base_url, self.token, user, question, agent=agent or self.agent,
        )

    def manifest_config(self) -> dict:
        config = {
            "backend_id": self.backend_id,
            "agent": self.agent,
            "expected_memory_backend": self.expected_memory_backend,
            "actual_memory_backend": self.actual_memory_backend,
        }
        if self.expected_memory_search is not None:
            config["expected_memory_search"] = self.expected_memory_search
            config["actual_memory_search"] = self.actual_memory_search
            config["memory_search_verified"] = not self.memory_search_failures
            config["memory_search_failures"] = self.memory_search_failures or []
        return config

    def publishability_failures(self) -> list[str]:
        return [
            f"builtin-vector memorySearch verification failed: {failure}"
            for failure in (self.memory_search_failures or [])
        ]


@dataclass
class OpenVikingBackend:
    backend_id: str
    account: str | None
    agent_id: str
    answer_mode: str = "openviking-search-rag"
    backend_kind: str = "openviking"

    def ingest(self, user: str, message: str, agent: str | None = None) -> tuple[str, dict]:
        result = add_memory(message, self.account, user, self.agent_id)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"].strip() or "ov add-memory failed")
        return "[openviking] saved", result

    def answer(self, user: str, question: str, agent: str | None = None) -> tuple[str, dict]:
        result = search(question, self.account, user, self.agent_id)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"].strip() or "ov search failed")
        context = "\n".join(item["text"] for item in result["retrieved"])
        answer = context or "[openviking] no retrieved memory"
        return answer, {"retrieval": result, "answer_mode": self.answer_mode}

    def manifest_config(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "answer_mode": self.answer_mode,
            "agent_id": self.agent_id,
            "account": self.account,
        }

    def publishability_failures(self) -> list[str]:
        return []


def read_openclaw_memory_search(profile: str) -> dict:
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        raise RuntimeError("openclaw binary not found")
    result = subprocess.run(
        [
            openclaw_bin,
            "--profile",
            profile,
            "config",
            "get",
            "agents.defaults.memorySearch",
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(stderr or stdout or "openclaw config get agents.defaults.memorySearch failed")
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise RuntimeError("agents.defaults.memorySearch must be a JSON object")
    return parsed


def read_openclaw_memory_backend(profile: str) -> str | None:
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        raise RuntimeError("openclaw binary not found")
    result = subprocess.run(
        [
            openclaw_bin,
            "--profile",
            profile,
            "config",
            "get",
            "memory.backend",
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        raise RuntimeError(stderr or stdout or "openclaw config get memory.backend failed")
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, str) else None


def _nested_get(config: dict, *path: str):
    value = config
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def normalize_memory_search_config(config: dict) -> dict:
    remote = _nested_get(config, "remote") or {}
    store_vector = _nested_get(config, "store", "vector") or {}
    query_hybrid = _nested_get(config, "query", "hybrid") or {}
    return {
        "provider": config.get("provider"),
        "base_url": (
            remote.get("baseUrl")
            or remote.get("base_url")
            or config.get("baseUrl")
            or config.get("base_url")
        ),
        "model": config.get("model") or remote.get("model"),
        "store.vector.enabled": store_vector.get("enabled"),
        "query.hybrid.enabled": query_hybrid.get("enabled"),
        "query.hybrid.vectorWeight": query_hybrid.get("vectorWeight"),
        "query.hybrid.textWeight": query_hybrid.get("textWeight"),
        "query.hybrid.candidateMultiplier": query_hybrid.get("candidateMultiplier"),
    }


def verify_builtin_vector_memory_search(actual: dict, expected: dict | None = None) -> tuple[dict, list[str]]:
    expected = expected or EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH
    normalized = normalize_memory_search_config(actual)
    failures = []
    for key, expected_value in expected.items():
        actual_value = normalized.get(key)
        if actual_value != expected_value:
            failures.append(f"{key} expected {expected_value!r}, got {actual_value!r}")
    return normalized, failures


def verify_openclaw_memory_backend(actual: str | None, expected: str) -> list[str]:
    expected_backend = EXPECTED_OPENCLAW_MEMORY_BACKENDS.get(expected, expected)
    if actual != expected_backend:
        return [f"memory.backend expected {expected_backend!r}, got {actual!r}"]
    return []


def build_backend(backend_id: str, args) -> MemoryBackend:
    if backend_id == "oo-builtin":
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "builtin_agent", "eval-locomo-builtin"),
            expected_memory_backend="builtin",
        )
    if backend_id == "oo-builtin-vector":
        expected = dict(EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH)
        try:
            actual_backend = read_openclaw_memory_backend(
                getattr(args, "openclaw_profile", "eval")
            )
            raw_memory_search = read_openclaw_memory_search(
                getattr(args, "openclaw_profile", "eval")
            )
            actual, failures = verify_builtin_vector_memory_search(raw_memory_search, expected)
            failures.extend(
                verify_openclaw_memory_backend(actual_backend, "builtin-vector")
            )
        except Exception as exc:
            actual_backend = None
            actual = None
            failures = [str(exc)]
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "builtin_vector_agent", "eval-locomo-builtin-vector"),
            expected_memory_backend="builtin-vector",
            actual_memory_backend=actual_backend,
            expected_memory_search=expected,
            actual_memory_search=actual,
            memory_search_failures=failures,
        )
    if backend_id == "oo-qmd":
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "qmd_agent", "eval-locomo-qmd"),
            expected_memory_backend="qmd",
        )
    if backend_id == "openviking":
        return OpenVikingBackend(
            backend_id=backend_id,
            account=getattr(args, "openviking_account", None),
            agent_id=getattr(args, "openviking_agent_id", "eval-locomo-openviking"),
        )
    raise ValueError(f"unknown backend: {backend_id}")


def backend_run_dir(run_group: str, backend_id: str) -> Path:
    return Path(run_group) / backend_id
