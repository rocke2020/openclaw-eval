import unittest

from eval_backends import OpenClawBackend, backend_run_dir, build_backend


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


if __name__ == "__main__":
    unittest.main()
