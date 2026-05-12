import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib.openclaw import get_session_id, reset_session, send_message


class EvalOpenClawTests(unittest.TestCase):
    def test_send_message_targets_named_agent(self):
        response = mock.Mock()
        response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
            "usage": {"total_tokens": 1},
        }
        response.raise_for_status.return_value = None

        with mock.patch("lib.openclaw.requests.post", return_value=response) as post:
            text, usage = send_message(
                "http://127.0.0.1:19002",
                "token",
                "eval-conv-26",
                "hello",
                agent="eval-locomo",
            )

        self.assertEqual(text, "ok")
        self.assertEqual(usage, {"total_tokens": 1})
        self.assertEqual(post.call_args.kwargs["json"]["model"], "openclaw/eval-locomo")

    def test_get_session_id_reads_named_agent_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "agents" / "eval-locomo" / "sessions"
            sessions.mkdir(parents=True)
            (sessions / "sessions.json").write_text(
                json.dumps(
                    {
                        "agent:eval-locomo:openresponses-user:eval-conv-26": {
                            "sessionId": "abc"
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(get_session_id("eval-locomo", "eval-conv-26", tmp), "abc")

    def test_reset_session_archives_named_agent_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp) / "agents" / "eval-locomo" / "sessions"
            sessions.mkdir(parents=True)
            transcript = sessions / "abc.jsonl"
            transcript.write_text("{}", encoding="utf-8")

            self.assertTrue(reset_session("eval-locomo", "abc", tmp))
            self.assertFalse(transcript.exists())
            self.assertEqual(len(list(sessions.glob("abc.jsonl.*"))), 1)


if __name__ == "__main__":
    unittest.main()
