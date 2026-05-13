import unittest
from unittest import mock

from lib.backends import OpenClawBackend, backend_run_dir, build_backend


class Args:
    base_url = "http://127.0.0.1:19002"
    token = "token"
    builtin_agent = "eval-locomo-builtin"
    qmd_agent = "eval-locomo-qmd"
    openviking_account = None
    openviking_agent_id = "eval-locomo-openviking"


class EvalBackendsTests(unittest.TestCase):
    def test_backend_registry_requires_known_backend(self):
        with self.assertRaisesRegex(ValueError, "unknown backend"):
            build_backend("missing", Args())

    def test_compare_run_paths_are_backend_scoped(self):
        self.assertEqual(str(backend_run_dir("group", "oo-builtin")), "group/oo-builtin")

    def test_openclaw_backend_manifest_records_expected_backend(self):
        backend = OpenClawBackend(
            backend_id="oo-qmd",
            base_url="http://127.0.0.1:19002",
            token="token",
            agent="eval-locomo-qmd",
            expected_memory_backend="qmd",
        )
        self.assertEqual(backend.manifest_config()["expected_memory_backend"], "qmd")

    def test_openclaw_backend_forwards_per_sample_agent_override(self):
        """Regression: per-sample agent must reach the wire, not the base agent."""
        backend = OpenClawBackend(
            backend_id="oo-builtin",
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
            backend_id="oo-builtin",
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
