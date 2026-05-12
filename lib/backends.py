"""Backend registry and comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lib.openclaw import send_message
from lib.openviking import add_memory, search


class MemoryBackend(Protocol):
    backend_id: str
    backend_kind: str

    def ingest(self, user: str, message: str) -> tuple[str, dict]: ...

    def answer(self, user: str, question: str) -> tuple[str, dict]: ...

    def manifest_config(self) -> dict: ...


@dataclass
class OpenClawBackend:
    backend_id: str
    base_url: str
    token: str
    agent: str
    expected_memory_backend: str
    backend_kind: str = "openclaw"

    def ingest(self, user: str, message: str) -> tuple[str, dict]:
        return send_message(self.base_url, self.token, user, message, agent=self.agent)

    def answer(self, user: str, question: str) -> tuple[str, dict]:
        return send_message(self.base_url, self.token, user, question, agent=self.agent)

    def manifest_config(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "agent": self.agent,
            "expected_memory_backend": self.expected_memory_backend,
        }


@dataclass
class OpenVikingBackend:
    backend_id: str
    account: str | None
    agent_id: str
    answer_mode: str = "openviking-search-rag"
    backend_kind: str = "openviking"

    def ingest(self, user: str, message: str) -> tuple[str, dict]:
        result = add_memory(message, self.account, user, self.agent_id)
        if result["returncode"] != 0:
            raise RuntimeError(result["stderr"].strip() or "ov add-memory failed")
        return "[openviking] saved", result

    def answer(self, user: str, question: str) -> tuple[str, dict]:
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


def build_backend(backend_id: str, args) -> MemoryBackend:
    if backend_id == "oo-builtin":
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "builtin_agent", "eval-locomo-builtin"),
            expected_memory_backend="builtin",
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
