import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib.artifacts import per_category_summary
from lib.judge_util import grade_answers_incremental, load_answers, locomo_grader


class _Message:
    content = json.dumps({"is_correct": "CORRECT", "reasoning": "same answer"})


class _Choice:
    message = _Message()


class _Response:
    choices = [_Choice()]


class _Completions:
    async def create(self, **_kwargs):
        return _Response()


class _Chat:
    completions = _Completions()


class _Client:
    chat = _Chat()


class JudgeUtilTests(unittest.IsolatedAsyncioTestCase):
    def test_load_answers_accepts_results_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "answers.json"
            path.write_text(json.dumps({"results": [{"question": "q"}]}), encoding="utf-8")
            self.assertEqual(load_answers(str(path)), [{"question": "q"}])

    def test_per_category_summary_counts_each_category(self):
        summary = per_category_summary(
            [
                {"category": 1, "grade": True},
                {"category": 1, "grade": False},
                {"category": 5, "grade": True},
            ]
        )
        self.assertEqual(summary["1"], {"correct": 1, "total": 2, "score": 0.5})
        self.assertEqual(summary["5"], {"correct": 1, "total": 1, "score": 1.0})

    async def test_grader_parses_json_label(self):
        result = await locomo_grader(_Client(), "judge-model", "q", "a", "a")
        self.assertTrue(result["grade"])
        self.assertEqual(result["label"], "CORRECT")
        self.assertEqual(result["judge_model"], "judge-model")

    async def test_incremental_grader_reuses_existing_records(self):
        answers = [
            {"sample_id": "conv-1", "qi": 1, "question": "q1", "expected": "a1", "response": "r1"},
            {"sample_id": "conv-1", "qi": 2, "question": "q2", "expected": "a2", "response": "r2"},
        ]
        existing = {"conv-1\t1": {**answers[0], "grade": True, "label": "CORRECT"}}
        completed = []

        async def fake_grader(_client, model, question, expected, response):
            self.assertEqual((model, question, expected, response), ("judge-model", "q2", "a2", "r2"))
            return {"grade": False, "label": "WRONG", "reasoning": "no", "judge_model": model}

        with mock.patch("lib.judge_util.locomo_grader", side_effect=fake_grader):
            graded = await grade_answers_incremental(
                answers,
                api_key="test-key",
                model="judge-model",
                parallel=1,
                existing_by_key=existing,
                key_fn=lambda item: f"{item['sample_id']}\t{item['qi']}",
                on_grade=completed.append,
            )

        self.assertEqual(graded[0]["label"], "CORRECT")
        self.assertEqual(graded[1]["label"], "WRONG")
        self.assertEqual(completed, [graded[1]])


if __name__ == "__main__":
    unittest.main()
