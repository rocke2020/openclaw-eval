import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from lib.openclaw import (
    get_session_id,
    is_retryable_error,
    reset_session,
    send_message,
    send_message_with_retry,
)


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

    def test_is_retryable_error_classifies_transient_only(self):
        timeout_err = requests.Timeout("read timeout")
        conn_err = requests.ConnectionError("refused")
        http_429 = requests.HTTPError(response=mock.Mock(status_code=429))
        http_503 = requests.HTTPError(response=mock.Mock(status_code=503))
        http_401 = requests.HTTPError(response=mock.Mock(status_code=401))
        http_400 = requests.HTTPError(response=mock.Mock(status_code=400))
        value_err = ValueError("bad input")

        self.assertTrue(is_retryable_error(timeout_err))
        self.assertTrue(is_retryable_error(conn_err))
        self.assertTrue(is_retryable_error(http_429))
        self.assertTrue(is_retryable_error(http_503))
        self.assertFalse(is_retryable_error(http_401))
        self.assertFalse(is_retryable_error(http_400))
        self.assertFalse(is_retryable_error(value_err))

    def test_send_message_with_retry_fails_fast_on_non_retryable(self):
        http_401 = requests.HTTPError(response=mock.Mock(status_code=401))
        with mock.patch("lib.openclaw.send_message", side_effect=http_401) as send:
            with self.assertRaises(requests.HTTPError):
                send_message_with_retry("u", "t", "user", "m", retries=2, backoff_base=0)
        self.assertEqual(send.call_count, 1)

    def test_send_message_with_retry_resets_between_attempts(self):
        timeout_err = requests.Timeout("t")
        success = ("ok", {"total_tokens": 1})
        reset_calls: list[int] = []
        with mock.patch(
            "lib.openclaw.send_message",
            side_effect=[timeout_err, success],
        ):
            result = send_message_with_retry(
                "u", "t", "user", "m",
                retries=2, backoff_base=0,
                reset_between_attempts=lambda: reset_calls.append(1),
            )
        self.assertEqual(result, success)
        self.assertEqual(len(reset_calls), 1)

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
