"""Backend registry and comparison helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
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

OPENCLAW_MEMORY_BACKEND_SCHEMA_VALUES = {"builtin", "qmd"}

# Maps harness backend ids to the value memory.backend must hold at runtime.
# Vector retrieval is an option *inside* the "builtin" engine (activated via
# agents.defaults.memorySearch.store.vector.enabled), not a distinct backend.
# Every value here must appear in OPENCLAW_MEMORY_BACKEND_SCHEMA_VALUES — see
# tests/test_eval_backends.py for the contract test that enforces this.
EXPECTED_OPENCLAW_MEMORY_BACKENDS = {
    "builtin": "builtin",
    "builtin-vector": "builtin",
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
    memory_backend_failures: list[str] | None = None
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
            "memory_backend_verified": not self.memory_backend_failures,
            "memory_backend_failures": self.memory_backend_failures or [],
        }
        if self.expected_memory_search is not None:
            config["expected_memory_search"] = self.expected_memory_search
            config["actual_memory_search"] = self.actual_memory_search
            config["memory_search_verified"] = not self.memory_search_failures
            config["memory_search_failures"] = self.memory_search_failures or []
        return config

    def publishability_failures(self) -> list[str]:
        failures = [
            f"OpenClaw memory backend verification failed: {failure}"
            for failure in (self.memory_backend_failures or [])
        ]
        failures.extend(
            [
                f"builtin-vector memorySearch verification failed: {failure}"
                for failure in (self.memory_search_failures or [])
            ]
        )
        return failures


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


def read_and_verify_openclaw_memory_backend(profile: str, expected: str) -> tuple[str | None, list[str]]:
    try:
        actual = read_openclaw_memory_backend(profile)
    except Exception as exc:
        return None, [str(exc)]
    return actual, verify_openclaw_memory_backend(actual, expected)


# ---------------------------------------------------------------------------
# OpenClaw + OpenViking plugin rows (reproduction of volcengine/OpenViking
# published LoCoMo comparison). The OV plugin sits in OC's contextEngine slot;
# the agent loop is unchanged from `oo-*` rows. What differs per row is
# `plugins.slots.contextEngine` + `plugins.entries.memory-core.enabled` +
# `tools.allow` widening for OV plugin tools.
# ---------------------------------------------------------------------------

# Tool names the OV plugin registers (manifest: openclaw.plugin.json).
OPENVIKING_PLUGIN_TOOLS = (
    "memory_recall",
    "memory_store",
    "memory_forget",
    "ov_archive_expand",
    "memory_search",
)

# Tools the OV plugin ALSO exposes but that we deny for strict memory-only eval
# (they let the model widen scope mid-eval).
OPENVIKING_PLUGIN_DENIED_TOOLS = ("add_resource", "add_skill")

# OC builtin memory tools (carried over to augmented row; codex flagged that
# the augmented row may be a hybrid surface — held behind a flag for now).
OPENCLAW_BUILTIN_MEMORY_TOOLS = ("memory_search", "memory_get", "write", "edit")


# Per-row config matrix — single source of truth, asserted by the strict gate
# from live profile state and recorded in the manifest.
OPENCLAW_OV_PLUGIN_ROW_MATRIX: dict[str, dict] = {
    "oc-ov-plugin-bare": {
        "memory_core_enabled": False,
        "context_engine_slot": "openviking",
        "tools_allow": tuple(sorted(set(OPENVIKING_PLUGIN_TOOLS))),
        "tools_deny_required": tuple(sorted(set(OPENVIKING_PLUGIN_DENIED_TOOLS))),
        "requires_hybrid_flag": False,
    },
    "oc-ov-plugin-augmented": {
        "memory_core_enabled": True,
        "context_engine_slot": "openviking",
        "tools_allow": tuple(sorted(set(OPENVIKING_PLUGIN_TOOLS) | set(OPENCLAW_BUILTIN_MEMORY_TOOLS))),
        "tools_deny_required": tuple(sorted(set(OPENVIKING_PLUGIN_DENIED_TOOLS))),
        "requires_hybrid_flag": True,  # codex: hybrid surface unverified
    },
}


@dataclass
class OpenClawOVPluginBackend:
    """OpenClaw agent loop with OV plugin in the contextEngine slot.

    The OC backend logic (ingest/answer) is identical to the existing
    OpenClawBackend; this class wraps it with row-specific config + extra
    publishability evidence collected by the pipeline.
    """

    backend_id: str
    base_url: str
    token: str
    agent: str
    memory_core_enabled: bool
    context_engine_slot: str
    openviking_server_base_url: str
    openviking_agent_prefix: str
    answer_model: str
    backend_kind: str = "openclaw"
    answer_mode: str = "openclaw-ov-plugin"

    # Live-config-observed values (populated by the pipeline pre-run).
    observed_context_engine_slot: str | None = None
    observed_memory_core_enabled: bool | None = None
    observed_plugin_version: str | None = None
    observed_plugin_source: str | None = None
    observed_server_version: str | None = None
    observed_server_auth_mode: str | None = None

    # Publishability evidence (populated by the pipeline as gates run).
    pre_flight_failures: list[str] = field(default_factory=list)
    isolation_gate_failures: list[str] = field(default_factory=list)
    pre_run_empty_scope_failures: list[str] = field(default_factory=list)
    write_verification_failures: list[str] = field(default_factory=list)
    runtime_evidence_failures: list[str] = field(default_factory=list)
    cross_scope_isolation_failures: list[str] = field(default_factory=list)
    config_drift_failures: list[str] = field(default_factory=list)

    def ingest(self, user: str, message: str, agent: str | None = None) -> tuple[str, dict]:
        return send_message_with_retry(
            self.base_url, self.token, user, message, agent=agent or self.agent,
        )

    def answer(self, user: str, question: str, agent: str | None = None) -> tuple[str, dict]:
        return send_message_with_retry(
            self.base_url, self.token, user, question, agent=agent or self.agent,
        )

    def manifest_config(self) -> dict:
        return {
            "backend_id": self.backend_id,
            "backend_kind": self.backend_kind,
            "answer_mode": self.answer_mode,
            "agent": self.agent,
            "answer_model": self.answer_model,
            "memory_core_enabled_expected": self.memory_core_enabled,
            "memory_core_enabled_observed": self.observed_memory_core_enabled,
            "context_engine_slot_expected": self.context_engine_slot,
            "context_engine_slot_observed": self.observed_context_engine_slot,
            "openclaw_ov_plugin_version": self.observed_plugin_version,
            "openclaw_ov_plugin_source": self.observed_plugin_source,
            "openviking_server_base_url": self.openviking_server_base_url,
            "openviking_server_version": self.observed_server_version,
            "openviking_server_auth_mode": self.observed_server_auth_mode,
            "openviking_agent_prefix": self.openviking_agent_prefix,
            "ov_scope_pattern": f"{self.openviking_agent_prefix}_<openclaw_agent_id>",
            "pre_flight_verified": not self.pre_flight_failures,
            "pre_flight_failures": self.pre_flight_failures,
            "isolation_gate_verified": not self.isolation_gate_failures,
            "isolation_gate_failures": self.isolation_gate_failures,
            "pre_run_empty_scope_verified": not self.pre_run_empty_scope_failures,
            "pre_run_empty_scope_failures": self.pre_run_empty_scope_failures,
            "write_verification_verified": not self.write_verification_failures,
            "write_verification_failures": self.write_verification_failures,
            "runtime_evidence_verified": not self.runtime_evidence_failures,
            "runtime_evidence_failures": self.runtime_evidence_failures,
            "cross_scope_isolation_verified": not self.cross_scope_isolation_failures,
            "cross_scope_isolation_failures": self.cross_scope_isolation_failures,
            "config_drift_verified": not self.config_drift_failures,
            "config_drift_failures": self.config_drift_failures,
            "comparison_class": self.comparison_class(),
        }

    def comparison_class(self) -> str:
        """Compute the comparison class from observed values, not flags."""
        # Exact reproduction requires OV server 0.1.18 AND answer model
        # seed-2.0-code AND matched judge. We don't have any of those locally.
        if self.observed_server_version == "0.1.18" and self.answer_model == "byteplus/seed-2.0-code":
            return "exact_reproduction_pending_judge"
        if self.answer_model not in {"byteplus/seed-2.0-code", "seed-2.0-code"}:
            return "approximation"
        return "directional_rerun"

    def publishability_failures(self) -> list[str]:
        failures: list[str] = []
        failures.extend([f"pre-flight: {x}" for x in self.pre_flight_failures])
        failures.extend([f"isolation gate: {x}" for x in self.isolation_gate_failures])
        failures.extend([f"empty-scope: {x}" for x in self.pre_run_empty_scope_failures])
        failures.extend([f"write verification: {x}" for x in self.write_verification_failures])
        failures.extend([f"runtime evidence: {x}" for x in self.runtime_evidence_failures])
        failures.extend([f"cross-scope isolation: {x}" for x in self.cross_scope_isolation_failures])
        failures.extend([f"config drift: {x}" for x in self.config_drift_failures])
        return failures


def build_backend(backend_id: str, args) -> MemoryBackend:
    if backend_id == "oc-builtin":
        actual_backend, backend_failures = read_and_verify_openclaw_memory_backend(
            getattr(args, "openclaw_profile", "eval"),
            "builtin",
        )
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "builtin_agent", "eval-locomo-builtin"),
            expected_memory_backend="builtin",
            actual_memory_backend=actual_backend,
            memory_backend_failures=backend_failures,
        )
    if backend_id == "oc-builtin-vector":
        expected = dict(EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH)
        actual_backend, backend_failures = read_and_verify_openclaw_memory_backend(
            getattr(args, "openclaw_profile", "eval"),
            "builtin-vector",
        )
        try:
            raw_memory_search = read_openclaw_memory_search(
                getattr(args, "openclaw_profile", "eval")
            )
            actual, search_failures = verify_builtin_vector_memory_search(raw_memory_search, expected)
        except Exception as exc:
            actual = None
            search_failures = [str(exc)]
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "builtin_vector_agent", "eval-locomo-builtin-vector"),
            expected_memory_backend="builtin-vector",
            actual_memory_backend=actual_backend,
            memory_backend_failures=backend_failures,
            expected_memory_search=expected,
            actual_memory_search=actual,
            memory_search_failures=search_failures,
        )
    if backend_id == "oo-qmd":
        actual_backend, backend_failures = read_and_verify_openclaw_memory_backend(
            getattr(args, "openclaw_profile", "eval"),
            "qmd",
        )
        return OpenClawBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=getattr(args, "qmd_agent", "eval-locomo-qmd"),
            expected_memory_backend="qmd",
            actual_memory_backend=actual_backend,
            memory_backend_failures=backend_failures,
        )
    if backend_id == "openviking":
        return OpenVikingBackend(
            backend_id=backend_id,
            account=getattr(args, "openviking_account", None),
            agent_id=getattr(args, "openviking_agent_id", "eval-locomo-openviking"),
        )
    if backend_id in OPENCLAW_OV_PLUGIN_ROW_MATRIX:
        row = OPENCLAW_OV_PLUGIN_ROW_MATRIX[backend_id]
        if row["requires_hybrid_flag"] and not getattr(args, "allow_unverified_hybrid_row", False):
            raise SystemExit(
                f"Backend {backend_id} requires --allow-unverified-hybrid-row "
                "until O4 in docs/design/openviking-memory-eval-plan.md resolves "
                "(published +memory-core tool surface unknown)."
            )
        return OpenClawOVPluginBackend(
            backend_id=backend_id,
            base_url=args.base_url,
            token=args.token,
            agent=_resolve_row_agent(args, backend_id),
            memory_core_enabled=row["memory_core_enabled"],
            context_engine_slot=row["context_engine_slot"],
            openviking_server_base_url=getattr(
                args, "openviking_server_base_url", "http://127.0.0.1:1933",
            ),
            openviking_agent_prefix=getattr(
                args, "openviking_agent_prefix", "eval-locomo-ov",
            ),
            answer_model=getattr(args, "answer_model", "deepseek/deepseek-v4-flash"),
        )
    raise ValueError(f"unknown backend: {backend_id}")


def _resolve_row_agent(args, backend_id: str) -> str:
    """Pick the per-row base agent name from --row-agent mapping or fallback."""
    row_map: dict = getattr(args, "row_agent_map", None) or {}
    if backend_id in row_map:
        return row_map[backend_id]
    # Fallback default — explicit, manifest-checkable.
    return f"eval-locomo-ov-{backend_id.removeprefix('oc-ov-plugin-')}"


def backend_run_dir(run_group: str, backend_id: str) -> Path:
    return Path(run_group) / backend_id
