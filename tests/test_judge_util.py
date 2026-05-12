import json
import tempfile
import unittest
from pathlib import Path

from lib.artifacts import per_category_summary
from lib.judge_util import load_answers, locomo_grader


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


if __name__ == "__main__":
    unittest.main()
