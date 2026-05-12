import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from eval_artifacts import (
    render_comparison_report_html,
    render_report_html,
    sha256_file,
    write_answers,
    write_manifest,
)
import eval as eval_module
from eval import select_canary_pairs


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
                mock.patch.object(eval_module, "_call_answer", return_value=("hello", {})),
                mock.patch.object(eval_module, "_maybe_reset_session"),
            ):
                eval_module.run_qa(args)

            self.assertTrue((run_dir / "manifest.json").exists())
            self.assertTrue((run_dir / "qa.jsonl").exists())
            answers = json.loads((run_dir / "answers.json").read_text(encoding="utf-8"))
            self.assertEqual(answers["results"][0]["category"], 5)


if __name__ == "__main__":
    unittest.main()
