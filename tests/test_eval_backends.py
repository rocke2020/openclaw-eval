import unittest
from unittest import mock

from lib.backends import (
    EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH,
    EXPECTED_OPENCLAW_MEMORY_BACKENDS,
    OPENCLAW_MEMORY_BACKEND_SCHEMA_VALUES,
    OpenClawBackend,
    backend_run_dir,
    build_backend,
    verify_builtin_vector_memory_search,
    verify_openclaw_memory_backend,
)


class Args:
    base_url = "http://127.0.0.1:19002"
    token = "token"
    builtin_agent = "eval-locomo-builtin"
    builtin_vector_agent = "eval-locomo-builtin-vector"
    qmd_agent = "eval-locomo-qmd"
    openclaw_profile = "eval"
    openviking_account = None
    openviking_agent_id = "eval-locomo-openviking"


class EvalBackendsTests(unittest.TestCase):
    def test_backend_registry_requires_known_backend(self):
        with self.assertRaisesRegex(ValueError, "unknown backend"):
            build_backend("missing", Args())

    def test_compare_run_paths_are_backend_scoped(self):
        self.assertEqual(
            str(backend_run_dir("group", "oc-builtin")), "group/oc-builtin"
        )

    def test_openclaw_backend_manifest_records_expected_backend(self):
        backend = OpenClawBackend(
            backend_id="oo-qmd",
            base_url="http://127.0.0.1:19002",
            token="token",
            agent="eval-locomo-qmd",
            expected_memory_backend="qmd",
        )
        self.assertEqual(backend.manifest_config()["expected_memory_backend"], "qmd")
        self.assertTrue(backend.manifest_config()["memory_backend_verified"])

    def test_build_backend_supports_builtin_vector(self):
        memory_search = {
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": True}},
            "query": {
                "hybrid": {
                    "enabled": True,
                    "vectorWeight": 0.8,
                    "textWeight": 0.2,
                    "candidateMultiplier": 6,
                }
            },
        }
        with (
            mock.patch("lib.backends.read_openclaw_memory_backend", return_value="builtin"),
            mock.patch("lib.backends.read_openclaw_memory_search", return_value=memory_search),
        ):
            backend = build_backend("oc-builtin-vector", Args())

        self.assertEqual(backend.backend_id, "oc-builtin-vector")
        self.assertEqual(backend.agent, "eval-locomo-builtin-vector")
        self.assertEqual(backend.manifest_config()["expected_memory_backend"], "builtin-vector")
        self.assertEqual(backend.manifest_config()["actual_memory_backend"], "builtin")
        self.assertTrue(backend.manifest_config()["memory_backend_verified"])
        self.assertEqual(backend.publishability_failures(), [])

    def test_builtin_vector_manifest_records_expected_and_actual_memory_search(self):
        memory_search = {
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": True}},
            "query": {
                "hybrid": {
                    "enabled": True,
                    "vectorWeight": 0.8,
                    "textWeight": 0.2,
                    "candidateMultiplier": 6,
                }
            },
        }
        with (
            mock.patch("lib.backends.read_openclaw_memory_backend", return_value="builtin"),
            mock.patch("lib.backends.read_openclaw_memory_search", return_value=memory_search),
        ):
            backend = build_backend("oc-builtin-vector", Args())

        config = backend.manifest_config()
        self.assertEqual(config["actual_memory_backend"], "builtin")
        self.assertEqual(config["expected_memory_search"], EXPECTED_BUILTIN_VECTOR_MEMORY_SEARCH)
        self.assertEqual(config["actual_memory_search"]["model"], "qwen3-embedding:0.6b")
        self.assertTrue(config["memory_search_verified"])

    def test_builtin_vector_rejects_memory_backend_mismatch(self):
        memory_search = {
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": True}},
            "query": {
                "hybrid": {
                    "enabled": True,
                    "vectorWeight": 0.8,
                    "textWeight": 0.2,
                    "candidateMultiplier": 6,
                }
            },
        }
        with (
            mock.patch("lib.backends.read_openclaw_memory_backend", return_value="qmd"),
            mock.patch("lib.backends.read_openclaw_memory_search", return_value=memory_search),
        ):
            backend = build_backend("oc-builtin-vector", Args())

        config = backend.manifest_config()
        self.assertEqual(config["actual_memory_backend"], "qmd")
        self.assertFalse(config["memory_backend_verified"])
        self.assertTrue(config["memory_search_verified"])
        self.assertTrue(
            any(
                "memory.backend expected 'builtin', got 'qmd'" in failure
                for failure in backend.publishability_failures()
            )
        )

    def test_builtin_rejects_memory_backend_mismatch(self):
        with mock.patch("lib.backends.read_openclaw_memory_backend", return_value="qmd"):
            backend = build_backend("oc-builtin", Args())

        config = backend.manifest_config()
        self.assertEqual(config["actual_memory_backend"], "qmd")
        self.assertFalse(config["memory_backend_verified"])
        self.assertTrue(
            any(
                "memory.backend expected 'builtin', got 'qmd'" in failure
                for failure in backend.publishability_failures()
            )
        )

    def test_qmd_rejects_memory_backend_mismatch(self):
        with mock.patch("lib.backends.read_openclaw_memory_backend", return_value="builtin"):
            backend = build_backend("oo-qmd", Args())

        config = backend.manifest_config()
        self.assertEqual(config["actual_memory_backend"], "builtin")
        self.assertFalse(config["memory_backend_verified"])
        self.assertTrue(
            any(
                "memory.backend expected 'qmd', got 'builtin'" in failure
                for failure in backend.publishability_failures()
            )
        )

    def test_builtin_records_matching_memory_backend(self):
        with mock.patch("lib.backends.read_openclaw_memory_backend", return_value="builtin"):
            backend = build_backend("oc-builtin", Args())

        config = backend.manifest_config()
        self.assertEqual(config["actual_memory_backend"], "builtin")
        self.assertTrue(config["memory_backend_verified"])
        self.assertEqual(backend.publishability_failures(), [])

    def test_memory_backend_verification_rejects_any_mismatch(self):
        # oc-builtin-vector requires memory.backend == "builtin" at runtime
        # (vector lives inside builtin via agents.defaults.memorySearch).
        self.assertEqual(verify_openclaw_memory_backend("builtin", "builtin-vector"), [])
        self.assertEqual(
            verify_openclaw_memory_backend("qmd", "builtin-vector"),
            ["memory.backend expected 'builtin', got 'qmd'"],
        )
        # Even the literal string "builtin-vector" must be rejected — it's not a
        # schema-valid runtime value (probed: schema enum = {"builtin","qmd"}).
        self.assertEqual(
            verify_openclaw_memory_backend("builtin-vector", "builtin-vector"),
            ["memory.backend expected 'builtin', got 'builtin-vector'"],
        )
        self.assertEqual(
            verify_openclaw_memory_backend(None, "builtin-vector"),
            ["memory.backend expected 'builtin', got None"],
        )

    def test_expected_backend_map_values_are_schema_valid(self):
        # Regression guard for the gate-mapping bug shipped earlier: the
        # original mapping had {"builtin-vector": "builtin-vector"}, which
        # OpenClaw's schema actively refuses (enum: "builtin" | "qmd"). The
        # gate then could not pass for any possible runtime state. Every
        # expected value in the map must be a value OpenClaw can actually
        # hold — otherwise the check is unreachable.
        for backend_id, expected in EXPECTED_OPENCLAW_MEMORY_BACKENDS.items():
            with self.subTest(backend_id=backend_id):
                self.assertIn(
                    expected,
                    OPENCLAW_MEMORY_BACKEND_SCHEMA_VALUES,
                    f"{backend_id!r} maps to {expected!r}, which is not a valid "
                    f"OpenClaw memory.backend value "
                    f"(allowed: {sorted(OPENCLAW_MEMORY_BACKEND_SCHEMA_VALUES)}).",
                )

    def test_builtin_vector_config_verification_rejects_wrong_provider(self):
        actual, failures = verify_builtin_vector_memory_search({
            "provider": "openai",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": True}},
            "query": {"hybrid": {"enabled": True, "vectorWeight": 0.8, "textWeight": 0.2, "candidateMultiplier": 6}},
        })
        self.assertEqual(actual["provider"], "openai")
        self.assertIn("provider expected 'ollama'", failures[0])

    def test_builtin_vector_config_verification_rejects_wrong_model(self):
        _, failures = verify_builtin_vector_memory_search({
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "nomic-embed-text",
            "store": {"vector": {"enabled": True}},
            "query": {"hybrid": {"enabled": True, "vectorWeight": 0.8, "textWeight": 0.2, "candidateMultiplier": 6}},
        })
        self.assertTrue(any("model expected 'qwen3-embedding:0.6b'" in failure for failure in failures))

    def test_builtin_vector_config_verification_rejects_disabled_vector_store(self):
        _, failures = verify_builtin_vector_memory_search({
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": False}},
            "query": {"hybrid": {"enabled": True, "vectorWeight": 0.8, "textWeight": 0.2, "candidateMultiplier": 6}},
        })
        self.assertTrue(any("store.vector.enabled expected True" in failure for failure in failures))

    def test_builtin_vector_config_verification_rejects_disabled_hybrid_query(self):
        _, failures = verify_builtin_vector_memory_search({
            "provider": "ollama",
            "remote": {"baseUrl": "http://127.0.0.1:11434"},
            "model": "qwen3-embedding:0.6b",
            "store": {"vector": {"enabled": True}},
            "query": {"hybrid": {"enabled": False, "vectorWeight": 0.8, "textWeight": 0.2, "candidateMultiplier": 6}},
        })
        self.assertTrue(any("query.hybrid.enabled expected True" in failure for failure in failures))

    def test_openclaw_backend_forwards_per_sample_agent_override(self):
        """Regression: per-sample agent must reach the wire, not the base agent."""
        backend = OpenClawBackend(
            backend_id="oc-builtin",
            base_url="http://127.0.0.1:19002",
            token="token",
            agent="base-agent",
            expected_memory_backend="builtin",
        )
        with mock.patch("lib.backends.send_message_with_retry", return_value=("ok", {})) as send:
            backend.ingest("user-1", "msg", agent="base-agent-conv-26")
            backend.answer("user-1", "q?", agent="base-agent-conv-26")
        self.assertEqual(send.call_args_list[0].kwargs["agent"], "base-agent-conv-26")
        self.assertEqual(send.call_args_list[1].kwargs["agent"], "base-agent-conv-26")

    def test_openclaw_backend_falls_back_to_self_agent_when_no_override(self):
        backend = OpenClawBackend(
            backend_id="oc-builtin",
            base_url="http://127.0.0.1:19002",
            token="token",
            agent="base-agent",
            expected_memory_backend="builtin",
        )
        with mock.patch("lib.backends.send_message_with_retry", return_value=("ok", {})) as send:
            backend.ingest("user-1", "msg")
        self.assertEqual(send.call_args.kwargs["agent"], "base-agent")


if __name__ == "__main__":
    unittest.main()
