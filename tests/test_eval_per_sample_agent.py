"""Integration tests for per-sample agent wiring through the harness.

Codex's review of the 2026-05-13 postmortem flagged that the existing regression
tests (tests/test_eval_backends.py) cover OpenClawBackend in isolation but never
the actual call chain through _ingest_one_sample / _call_ingest / backend.ingest /
send_message_with_retry. A regression in main.py that dropped the agent forwarding
would still pass the unit tests. These tests close that gap.
"""

import argparse
import unittest
from unittest import mock

import main as eval_module
from lib.backends import OpenClawBackend


def _locomo_sample(sample_id: str) -> dict:
    return {
        "sample_id": sample_id,
        "conversation": {
            "speaker_a": "Alice",
            "speaker_b": "Bob",
            "session_1": [{"speaker": "Alice", "text": "hello"}],
        },
        "qa": [
            {
                "question": "What did Alice say?",
                "answer": "hello",
                "category": 1,
                "evidence": ["D1:1"],
            }
        ],
    }


def _base_args(**overrides) -> argparse.Namespace:
    backend = OpenClawBackend(
        backend_id="oc-builtin",
        base_url="http://127.0.0.1:19002",
        token="tok",
        agent="base-agent",
        expected_memory_backend="builtin",
    )
    defaults = dict(
        input="locomo.json",
        sample=None,
        sessions=None,
        tail="[]",
        user=None,
        viking=False,
        base_url="http://127.0.0.1:19002",
        token="tok",
        output=None,
        run_dir=None,
        agent="base-agent",
        builtin_agent="base-agent",
        openclaw_home=None,
        openclaw_profile="eval",
        agent_workspace="/tmp/test-ws-does-not-exist",
        ingest_parallel=1,
        backend=backend,
        include_categories=None,
        exclude_categories=None,
        openviking_account=None,
        openviking_agent_id="ov",
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _stub_ensure_sample_agent(profile, base_agent, base_workspace, sample_id):
    return {
        "agent_id": f"{base_agent}-{sample_id}",
        "workspace": f"{base_workspace}-{sample_id}",
        "_created": False,
    }


class PerSampleAgentReachesWireTests(unittest.TestCase):
    def test_ingest_routes_each_sample_to_its_own_agent_on_the_wire(self):
        """Per-sample agent override must show up as the `agent=` kwarg to send_message."""
        args = _base_args()
        wire_calls: list[dict] = []

        def fake_send(_base_url, _token, user, _message, agent="main", **_):
            wire_calls.append({"user": user, "agent": agent})
            return "ok", {}

        with (
            mock.patch.object(
                eval_module,
                "load_locomo_data",
                return_value=[_locomo_sample("conv-26"), _locomo_sample("conv-30")],
            ),
            mock.patch.object(eval_module, "provision_sample_agents", return_value=[]),
            mock.patch.object(
                eval_module, "ensure_sample_agent", side_effect=_stub_ensure_sample_agent,
            ),
            mock.patch("lib.backends.send_message_with_retry", side_effect=fake_send),
            mock.patch.object(eval_module, "get_session_id", return_value=None),
            mock.patch.object(eval_module, "reset_session"),
            mock.patch.object(eval_module, "snapshot_memory_files", return_value={}),
        ):
            eval_module.run_ingest(args)

        agents_seen = {call["agent"] for call in wire_calls}
        self.assertIn("base-agent-conv-26", agents_seen)
        self.assertIn("base-agent-conv-30", agents_seen)
        self.assertNotIn(
            "base-agent", agents_seen,
            msg="bare base agent reached the wire — per-sample override was dropped somewhere",
        )

    def test_ingest_pairs_each_sample_agent_with_its_own_user_key(self):
        """Sample conv-26 messages must go to (agent=...conv-26, user=eval-conv-26)."""
        args = _base_args()
        wire_calls: list[dict] = []

        def fake_send(_base_url, _token, user, _message, agent="main", **_):
            wire_calls.append({"user": user, "agent": agent})
            return "ok", {}

        with (
            mock.patch.object(
                eval_module,
                "load_locomo_data",
                return_value=[_locomo_sample("conv-26"), _locomo_sample("conv-30")],
            ),
            mock.patch.object(eval_module, "provision_sample_agents", return_value=[]),
            mock.patch.object(
                eval_module, "ensure_sample_agent", side_effect=_stub_ensure_sample_agent,
            ),
            mock.patch("lib.backends.send_message_with_retry", side_effect=fake_send),
            mock.patch.object(eval_module, "get_session_id", return_value=None),
            mock.patch.object(eval_module, "reset_session"),
            mock.patch.object(eval_module, "snapshot_memory_files", return_value={}),
        ):
            eval_module.run_ingest(args)

        # Every wire call's agent must match its user's sample.
        for call in wire_calls:
            sample_id = call["user"].removeprefix("eval-")
            expected_agent = f"base-agent-{sample_id}"
            self.assertEqual(
                call["agent"], expected_agent,
                msg=f"user={call['user']} routed to agent={call['agent']}, expected {expected_agent}",
            )


if __name__ == "__main__":
    unittest.main()
