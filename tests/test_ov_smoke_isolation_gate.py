"""Smoke isolation gate: a row that writes to the wrong OV scope must abort
BEFORE the full ingest.

The 2026-05-20 incident: oc-ov-plugin-bare ran the full 6-hour eval with
extractions landing in `viking://user/default/memories/` instead of
per-sample agent scope. 23/37 canary cross-sample leaks confirmed
contamination. This gate catches that failure mode (and adjacent ones)
in a sub-15-second smoke before any meaningful token spend.

Coverage:
  - Original 05-20 failure: per-sample writes missed → abort
  - Recall returns items but none contain the canary → abort (codex #3)
  - Dual-write to witness agent (cross-agent leak) → abort (codex #2)
  - Dual-write to user="default" (shared-scope leak) → abort (codex #2)
  - Polling deadline reached without a session → abort (codex #5)
  - Re-runs of the same row-agent produce unique smoke scopes (codex #1)
  - server URL passed through to probes (codex #6)
  - Happy path: per-sample writes land + canary matches + no leaks
  - No --allow-non-publishable bypass
"""

import argparse
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lib.backends import OpenClawOVPluginBackend
from main import _ov_plugin_smoke_isolation_gate, _smoke_recall_contains_canary


def _fast_clock(step_s: float = 1.0):
    """Return a callable that advances a virtual monotonic clock per call.

    Lets polling tests hit the gate's 15s deadline in ~15 mock-clock ticks
    instead of 15 real seconds."""
    state = {"now": 0.0}

    def tick():
        state["now"] += step_s
        return state["now"]

    return tick


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


def _args(**overrides) -> argparse.Namespace:
    defaults = {"openclaw_profile": "eval", "agent_workspace": None}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _session_ok():
    return {"write_detected": True, "sessions_count": 1}


def _session_empty():
    return {"write_detected": False, "sessions_count": 0}


def _recall_with_canary(canary_text: str):
    return {
        "recall_hit": True,
        "hit_count": 1,
        "top_score": 0.87,
        "items": [{"text": f"... {canary_text} was the marker ..."}],
    }


def _recall_empty():
    return {"recall_hit": False, "hit_count": 0, "top_score": None, "items": []}


def _recall_noise():
    """Items returned, but none contain the canary string."""
    return {
        "recall_hit": True,
        "hit_count": 2,
        "top_score": 0.4,
        "items": [
            {"text": "scaffold template — fill in during first conversation"},
            {"text": "unrelated semantic neighbor"},
        ],
    }


class SmokeRecallContainsCanaryHelper(unittest.TestCase):
    def test_dict_with_text_field_matching(self):
        self.assertTrue(_smoke_recall_contains_canary(
            [{"text": "stuff smoke-isolation-canary-abc more stuff"}],
            "smoke-isolation-canary-abc",
        ))

    def test_dict_with_unrelated_text(self):
        self.assertFalse(_smoke_recall_contains_canary(
            [{"text": "template"}, {"content": "other"}],
            "smoke-isolation-canary-abc",
        ))

    def test_empty_items(self):
        self.assertFalse(_smoke_recall_contains_canary([], "anything"))

    def test_string_items(self):
        self.assertTrue(_smoke_recall_contains_canary(
            ["smoke-isolation-canary-abc found here"],
            "smoke-isolation-canary-abc",
        ))


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
                probe_sess.return_value = _session_empty()
                probe_recall.return_value = _recall_empty()
                with patch("time.sleep"), patch("time.monotonic", _fast_clock()):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertIn("zero sessions", str(ctx.exception))
            self.assertIn("user/default", str(ctx.exception))
            self.assertTrue(backend.smoke_isolation_failures)
            ingest_mock.assert_called_once()
            evidence = json.loads((run_dir / "openviking_smoke_isolation.json").read_text())
            self.assertFalse(evidence["ok"])
            self.assertTrue(evidence["polling"]["attempts"] > 1)

    def test_aborts_when_recall_returns_only_noise(self):
        """Recall returns items but none contain the canary substring —
        e.g. plugin returns scaffold/template records. Codex finding #3."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()]
                probe_recall.return_value = _recall_noise()
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertIn("NONE contained the canary", str(ctx.exception))

    def test_aborts_when_canary_leaks_to_witness_agent(self):
        """Codex finding #2 (cross-agent leak). After positive probe passes,
        a never-used witness agent must also be queried — a hit there means
        the plugin is writing to a shared scope."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()]
                # Side-effect closure captures the canary the gate generated.
                def recall_side_effect(*, canary_text, **_):
                    # ALL agent scopes return the canary → cross-agent leak.
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertIn("leaked to witness", str(ctx.exception))

    def test_aborts_when_canary_appears_at_user_default(self):
        """Codex finding #2 (shared-scope dual-write). Positive probe and
        witness probe pass, but user='default' under the smoke agent also
        contains the canary → dual-write contamination."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()]

                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    # Positive probe (smoke agent + smoke_user) hits;
                    # witness agent does NOT hit;
                    # default-user probe at smoke agent DOES hit → leak.
                    if user == "default":
                        return _recall_with_canary(canary_text)
                    if "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertIn("user='default'", str(ctx.exception))
            self.assertIn("dual-writing", str(ctx.exception))

    def test_polling_succeeds_after_initial_misses(self):
        """probe_session_exists returns empty on first two attempts then
        lands a session on the third. Codex finding #5 — async extraction
        latency must not false-fail."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [
                    _session_empty(),  # pre-empty
                    _session_empty(),  # poll attempt 1
                    _session_empty(),  # poll attempt 2
                    _session_ok(),     # poll attempt 3
                ]

                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    if user == "default" or "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            evidence = json.loads((run_dir / "openviking_smoke_isolation.json").read_text())
            self.assertTrue(evidence["ok"])
            self.assertGreaterEqual(evidence["polling"]["attempts"], 3)

    def test_run_unique_smoke_agent_per_invocation(self):
        """Codex finding #1 — two consecutive invocations on the same
        backend.agent must use different smoke OV scopes, so the second
        run's pre-empty check does not see the first run's leftover."""
        backend = _make_backend()
        smoke_agents_seen = []
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()] * 5
                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    smoke_agents_seen.append((ov_agent_id, user))
                    if user == "default" or "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
                    _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            primary_agents = {entry[0] for entry in smoke_agents_seen if "witness" not in entry[0]}
            self.assertGreaterEqual(len(primary_agents), 2,
                f"expected two distinct smoke agents across runs, got {primary_agents}")

    def test_server_url_passed_through_to_probes(self):
        """Codex finding #6 — backend.openviking_server_base_url must
        reach every probe so the `ov` CLI talks to the same server the
        plugin talks to."""
        backend = _make_backend()
        backend.openviking_server_base_url = "http://10.0.0.42:1933"
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()]
                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    if user == "default" or "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            for call in probe_sess.call_args_list:
                self.assertEqual(call.kwargs.get("base_url"), "http://10.0.0.42:1933")
            for call in probe_recall.call_args_list:
                self.assertEqual(call.kwargs.get("base_url"), "http://10.0.0.42:1933")

    def test_aborts_when_ingest_call_raises(self):
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", side_effect=RuntimeError("gateway 503")), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall"):
                probe_sess.return_value = _session_empty()
                with patch("time.sleep"):
                    with self.assertRaises(SystemExit) as ctx:
                        _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertIn("gateway 503", str(ctx.exception))

    def test_passes_happy_path(self):
        """Per-sample writes land, canary matches, no cross-agent leak,
        no shared-scope leak. Gate must not raise."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {"input_tokens": 100})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.side_effect = [_session_empty(), _session_ok()]
                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    if user == "default" or "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(backend, run_dir, _args())
            self.assertFalse(backend.smoke_isolation_failures)
            evidence = json.loads((run_dir / "openviking_smoke_isolation.json").read_text())
            self.assertTrue(evidence["ok"])
            self.assertEqual(evidence["failures"], [])
            self.assertTrue(evidence["session_probe"]["write_detected"])
            self.assertTrue(evidence["recall_probe"]["recall_hit"])
            self.assertFalse(evidence["negative_witness_probe"]["recall_hit"])
            self.assertFalse(evidence["negative_default_user_probe"]["recall_hit"])

    def test_provisions_smoke_agent_when_agent_workspace_set(self):
        """Codex finding #4 — when --agent-workspace is set, real samples
        go through ensure_sample_agent; the smoke must do the same."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            ws = tmp + "/ws"
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall, \
                 patch("main.ensure_sample_agent") as ensure_mock:
                probe_sess.side_effect = [_session_empty(), _session_ok()]
                def recall_side_effect(*, ov_agent_id, user, canary_text, **_):
                    if user == "default" or "witness" in ov_agent_id:
                        return _recall_empty()
                    return _recall_with_canary(canary_text)
                probe_recall.side_effect = recall_side_effect
                ensure_mock.return_value = {
                    "agent_id": "eval-locomo-ov-test-provisioned",
                    "workspace": ws + "/_smoke",
                }
                with patch("time.sleep"):
                    _ov_plugin_smoke_isolation_gate(
                        backend, run_dir, _args(agent_workspace=ws),
                    )
            ensure_mock.assert_called_once()
            kwargs = ensure_mock.call_args.kwargs
            self.assertEqual(kwargs["profile"], "eval")
            self.assertEqual(kwargs["base_agent"], "eval-locomo-ov-test")
            self.assertEqual(kwargs["base_workspace"], ws)
            self.assertIn("_smoke", kwargs["sample_id"])

    def test_no_allow_non_publishable_bypass(self):
        """Gate raises unconditionally — no flag honors a bypass."""
        backend = _make_backend()
        with TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(backend, "ingest", return_value=("ok", {})), \
                 patch("main.probe_session_exists") as probe_sess, \
                 patch("main.probe_positive_recall") as probe_recall:
                probe_sess.return_value = _session_empty()
                probe_recall.return_value = _recall_empty()
                with patch("time.sleep"), patch("time.monotonic", _fast_clock()):
                    with self.assertRaises(SystemExit):
                        _ov_plugin_smoke_isolation_gate(
                            backend, run_dir,
                            _args(allow_non_publishable=True),
                        )


if __name__ == "__main__":
    unittest.main()
