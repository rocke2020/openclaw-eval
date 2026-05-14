import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib.artifacts import (
    render_comparison_report_html,
    render_report_html,
    sha256_file,
    write_answers,
    write_manifest,
)
import main as main_module
from main import (
    canary_record_leaked,
    count_canary_leakage,
    select_adversarial_canary_pairs,
    select_canary_pairs,
    verify_strict_eval_isolation,
)


class EvalArtifactsTests(unittest.TestCase):
    def test_sha256_file_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("abc", encoding="utf-8")
            self.assertEqual(
                sha256_file(str(path)),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )

    def test_write_manifest_sorts_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            write_manifest(path, {"b": 2, "a": 1})
            self.assertLess(path.read_text().index('"a": 1'), path.read_text().index('"b": 2'))

    def test_write_answers_uses_results_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answers.json"
            write_answers(path, [{"question": "q"}], {"total": 1})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["results"], [{"question": "q"}])
            self.assertEqual(data["summary"], {"total": 1})

    def test_render_report_html_includes_score_and_manifest(self):
        html = render_report_html({"run_id": "r1"}, {"total": 2}, {"score": 0.5})
        self.assertIn("r1", html)
        self.assertIn("50.00%", html)

    def test_comparison_report_orders_builtin_first(self):
        html = render_comparison_report_html(
            {"run_group_id": "g1"},
            [
                {"backend_id": "openviking", "judge_score": 0.1},
                {"backend_id": "oo-builtin", "judge_score": 0.2},
            ],
        )
        self.assertLess(html.index("oo-builtin"), html.index("openviking"))

    def test_canary_pairs_next_sample_questions_to_current_user(self):
        pairs = select_canary_pairs(
            [
                {"sample_id": "conv-26", "qa": [{"question": "q1", "answer": "a1"}]},
                {"sample_id": "conv-30", "qa": [{"question": "q2", "answer": "a2"}]},
            ],
            1,
        )
        self.assertEqual(pairs[0]["source_sample_id"], "conv-30")
        self.assertEqual(pairs[0]["target_user"], "eval-conv-26")

    def test_adversarial_canary_pairs_include_standard_live_cases(self):
        samples = [
            {"sample_id": "conv-47", "qa": []},
            {"sample_id": "conv-48", "qa": []},
            {"sample_id": "conv-49", "qa": []},
            {"sample_id": "conv-50", "qa": []},
        ]
        args = argparse.Namespace(
            openclaw_home="/tmp/openclaw-eval",
            agent_workspace="/tmp/workspace",
            agent="eval-locomo",
        )

        pairs = select_adversarial_canary_pairs(samples, args)

        self.assertEqual(len(pairs), 7)
        self.assertEqual(
            {pair["suite"] for pair in pairs},
            {"deborah_karlie", "calvin_ferrari"},
        )
        self.assertTrue(
            any(
                pair["question"].startswith("Strict isolation canary. What items did Calvin buy in March 2023?")
                for pair in pairs
            )
        )
        self.assertTrue(all(pair["type"] == "adversarial_isolation_canary" for pair in pairs))

    def test_run_canaries_uses_target_sample_agent(self):
        samples = [
            {"sample_id": "conv-26", "qa": [{"question": "q1", "answer": "alpha beta"}]},
            {"sample_id": "conv-30", "qa": [{"question": "q2", "answer": "gamma delta"}]},
        ]
        args = argparse.Namespace(canary_count=1, user=None, agent="base-agent")
        called_agents = []

        def fake_resolve(_args, sample_id):
            return f"base-agent-{sample_id}", f"/tmp/{sample_id}"

        def fake_call(call_args, user_key, question):
            called_agents.append((call_args.agent, user_key, question))
            return ("I don't have any information about that.", {})

        with (
            mock.patch.object(main_module, "_resolve_sample_agent", side_effect=fake_resolve),
            mock.patch.object(main_module, "_call_answer", side_effect=fake_call),
            mock.patch.object(main_module, "_maybe_reset_session"),
        ):
            records = main_module.run_canaries(samples, args)

        self.assertEqual(
            called_agents,
            [
                ("base-agent-conv-26", "eval-conv-26", "q2"),
                ("base-agent-conv-30", "eval-conv-30", "q1"),
            ],
        )
        self.assertEqual(records[0]["target_agent"], "base-agent-conv-26")
        self.assertEqual(records[1]["target_agent"], "base-agent-conv-30")

    def test_count_canary_leakage_scores_non_refusal_expected_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "canary.jsonl"
            records = [
                {
                    "expected": "mansion in Japan, luxury car Ferrari 488 GTB",
                    "response": "Calvin bought a mansion and a luxury Ferrari.",
                },
                {
                    "expected": "between 26 March and 20 April 2023",
                    "response": "I don't have any information about Calvin traveling to Tokyo.",
                },
                {
                    "expected": "get endorsements, build his brand, do charity work",
                    "leak_detected": True,
                    "response": "I searched my memory files and there is no mention of anyone named John or his basketball career.",
                },
            ]
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(count_canary_leakage(path), 1)

    def test_marker_canary_does_not_count_prompt_terms_as_leaks(self):
        self.assertFalse(
            canary_record_leaked(
                {
                    "leak_markers": ["ferrari 488", "488 gtb", "mansion"],
                    "response": "I don't have any information about Calvin, Ferrari, Dave, or Aerosmith.",
                }
            )
        )
        self.assertFalse(
            canary_record_leaked(
                {
                    "leak_markers": ["karlie", "january 25", "both parents"],
                    "response": "I found no information about Deborah or Karlie.",
                }
            )
        )
        self.assertTrue(
            canary_record_leaked(
                {
                    "leak_markers": ["ferrari 488", "488 gtb", "mansion"],
                    "response": "Calvin bought a Ferrari 488 GTB and a mansion.",
                }
            )
        )

    def test_verify_strict_eval_isolation_requires_memory_only_tools(self):
        responses = {
            ("eval", "config", "get", "tools.allow", "--json"): ["memory_search", "memory_get"],
            ("eval", "config", "get", "tools.deny", "--json"): sorted(main_module.STRICT_FORBIDDEN_TOOLS),
            ("eval", "config", "get", "tools.elevated.enabled", "--json"): False,
            ("eval", "skills", "check", "--agent", "eval-locomo", "--json"): {
                "modelVisible": [],
                "commandVisible": [],
            },
        }

        def fake_openclaw_json(profile, *args):
            return responses[(profile, *args)]

        with mock.patch.object(main_module, "_openclaw_json", side_effect=fake_openclaw_json):
            report = verify_strict_eval_isolation("eval", "eval-locomo")

        self.assertTrue(report["ok"])
        self.assertEqual(report["tools_allow"], ["memory_get", "memory_search"])

    def test_verify_strict_eval_isolation_fails_when_exec_allowed(self):
        responses = {
            ("eval", "config", "get", "tools.allow", "--json"): ["memory_search", "memory_get", "exec"],
            ("eval", "config", "get", "tools.deny", "--json"): sorted(main_module.STRICT_FORBIDDEN_TOOLS - {"exec"}),
            ("eval", "config", "get", "tools.elevated.enabled", "--json"): False,
            ("eval", "skills", "check", "--agent", "eval-locomo", "--json"): {
                "modelVisible": [],
                "commandVisible": [],
            },
        }

        def fake_openclaw_json(profile, *args):
            return responses[(profile, *args)]

        with mock.patch.object(main_module, "_openclaw_json", side_effect=fake_openclaw_json):
            report = verify_strict_eval_isolation("eval", "eval-locomo")

        self.assertFalse(report["ok"])
        self.assertIn("tools.allow must be exactly", report["failures"][0])
        self.assertIn("exec", report["failures"][1])

    def test_eval_isolation_gate_checks_backend_agents(self):
        args = argparse.Namespace(
            mode="eval",
            backends="oo-builtin,openviking",
            agent="default-agent",
            builtin_agent="builtin-agent",
            qmd_agent="qmd-agent",
        )

        self.assertEqual(main_module.strict_isolation_agents_for_args(args), ["builtin-agent"])

    def test_run_qa_writes_strict_artifacts_with_mocked_backend(self):
        sample = {
            "sample_id": "conv-26",
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1": [{"speaker": "Alice", "text": "hello"}],
            },
            "qa": [{"question": "What?", "answer": "hello", "category": 5}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "locomo.json"
            data_path.write_text(json.dumps([sample]), encoding="utf-8")
            run_dir = Path(tmp) / "run"
            args = argparse.Namespace(
                input=str(data_path),
                sample=None,
                user=None,
                count=None,
                output=None,
                base_url="http://127.0.0.1:19002",
                token="token",
                agent="eval-locomo",
                openclaw_home=None,
                backend=None,
                include_categories="1,2,3,4,5",
                exclude_categories=None,
                parallel=1,
                run_dir=str(run_dir),
                tail="[remember what's said, keep existing memory]",
                sessions=None,
                openclaw_profile="eval",
                agent_workspace=None,
                openviking_account=None,
                openviking_user=None,
                openviking_agent_id="eval-locomo-openviking",
                judge_model=None,
                judge_base_url=None,
                run_group_id=None,
                backend_id="oo-builtin",
                backend_kind="openclaw",
                canary=False,
                canary_count=3,
                viking=False,
            )
            with (
                mock.patch.object(main_module, "_call_answer", return_value=("hello", {})),
                mock.patch.object(main_module, "_maybe_reset_session"),
            ):
                main_module.run_qa(args)

            self.assertTrue((run_dir / "manifest.json").exists())
            self.assertTrue((run_dir / "qa.jsonl").exists())
            answers = json.loads((run_dir / "answers.json").read_text(encoding="utf-8"))
            self.assertEqual(answers["results"][0]["category"], 5)


if __name__ == "__main__":
    unittest.main()
