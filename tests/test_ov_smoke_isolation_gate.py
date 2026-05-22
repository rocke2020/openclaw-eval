"""Smoke isolation gate: a row that writes to shared user/default scope
instead of per-sample agent scope must abort BEFORE the full ingest.

The 2026-05-20 incident: oc-ov-plugin-bare ran the full 6-hour eval with
extractions landing in `viking://user/default/memories/` instead of
per-sample agent scope. 23/37 canary cross-sample leaks confirmed
contamination. This gate catches that failure mode in a 5-second smoke
before any meaningful token spend.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lib.backends import OpenClawOVPluginBackend
from main import _ov_plugin_smoke_isolation_gate


def _make_backend() -> OpenClawOVPluginBackend:
    return OpenClawOVPluginBackend(
        backend_id="oc-ov-plugin-bare",
        base_url="http://127.0.0.1:19002",
        token="test-token",
        agent="eval-locomo-ov-test",
        memory_core_enabled=False,
        context_engine_slot="openviking",
        openviking_server_base_url="http://127.0.0.1:1933",
        openviking_agent_prefix="eval-locomo-ov",
        answer_model="deepseek/deepseek-v4-flash",
    )


class SmokeIsolationGateTests(unittest.TestCase):
    def test_aborts_when_writes_miss_per_sample_scope(self):
        """The 2026-05-20 failure: ingest succeeds but per-sample scope
        stays empty because writes go to user/default. Gate MUST abort."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok stored", {"input_tokens": 100})) as ingest_mock, \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [
                    {"write_detected": False, "sessions_count": 0},  # pre-empty check passes
                    {"write_detected": False, "sessions_count": 0},  # post-ingest: WRITES MISSED
                ]
                probe_recall.return_value = {"recall_hit": False, "hit_count": 0, "top_score": None}
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir)
            self.assertIn("zero sessions", str(ctx.exception))
            self.assertIn("user/default", str(ctx.exception))
            self.assertTrue(backend.smoke_isolation_failures)
            ingest_mock.assert_called_once()
            evidence_path = run_dir / "openviking_smoke_isolation.json"
            self.assertTrue(evidence_path.exists())
            evidence = json.loads(evidence_path.read_text())
            self.assertFalse(evidence["ok"])
            self.assertTrue(evidence["failures"])

    def test_aborts_when_canary_not_recallable(self):
        """Sessions land but the canary isn't retrievable at agent scope."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok stored", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [
                    {"write_detected": False, "sessions_count": 0},  # pre-empty
                    {"write_detected": True, "sessions_count": 1},   # post-ingest session lands
                ]
                probe_recall.return_value = {"recall_hit": False, "hit_count": 0, "top_score": None}
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir)
            self.assertIn("not retrievable", str(ctx.exception))

    def test_aborts_when_smoke_scope_not_empty(self):
        """A pre-existing smoke session would let a real failure pass on
        stale data. Pre-empty check must abort with a clear remediation."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest") as ingest_mock, \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall"):
                probe_sess.return_value = {"write_detected": True, "sessions_count": 1}
                with self.assertRaises(SystemExit) as ctx:
                    _ov_plugin_smoke_isolation_gate(backend, run_dir)
            self.assertIn("not empty", str(ctx.exception))
            ingest_mock.assert_not_called()

    def test_aborts_when_ingest_call_raises(self):
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", side_effect=RuntimeError("gateway 503")), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall"):
                probe_sess.return_value = {"write_detected": False, "sessions_count": 0}
                with self.assertRaises(SystemExit) as ctx:
                    _ov_plugin_smoke_isolation_gate(backend, run_dir)
            self.assertIn("gateway 503", str(ctx.exception))

    def test_passes_when_writes_land_and_canary_recallable(self):
        """Correct OV plugin behavior: session lands AND canary is retrievable
        at per-sample agent scope. Gate must not raise."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok stored", {"input_tokens": 100})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [
                    {"write_detected": False, "sessions_count": 0},  # pre-empty
                    {"write_detected": True, "sessions_count": 1},   # post-ingest
                ]
                probe_recall.return_value = {
                    "recall_hit": True, "hit_count": 1, "top_score": 0.87,
                }
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(backend, run_dir)
            self.assertFalse(backend.smoke_isolation_failures)
            evidence = json.loads((run_dir / "openviking_smoke_isolation.json").read_text())
            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["failures"], [])
            self.assertTrue(evidence["session_probe"]["write_detected"])
            self.assertTrue(evidence["recall_probe"]["recall_hit"])

    def test_no_allow_non_publishable_bypass(self):
        """Even with allow_non_publishable set elsewhere, the gate itself
        raises unconditionally. The caller cannot reach run_ingest after a
        failure because SystemExit propagates."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [
                    {"write_detected": False, "sessions_count": 0},
                    {"write_detected": False, "sessions_count": 0},
                ]
                probe_recall.return_value = {"recall_hit": False, "hit_count": 0, "top_score": None}
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit):
                        _ov_plugin_smoke_isolation_gate(backend, run_dir)


if __name__ == "__main__":
    unittest.main()
