import json
import unittest
from unittest import mock

from lib.openviking import add_memory, normalize_search_output


class EvalOpenVikingTests(unittest.TestCase):
    def test_openviking_add_memory_command_includes_user_and_agent(self):
        result = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch("lib.openviking.subprocess.run", return_value=result) as run:
            add_memory("hello", "acct", "user-1", "agent-1")
        argv = run.call_args.args[0]
        self.assertIn("--user", argv)
        self.assertIn("user-1", argv)
        self.assertIn("--agent-id", argv)
        self.assertIn("agent-1", argv)
        self.assertIn("--account", argv)

    def test_openviking_search_normalizes_json_output(self):
        output = json.dumps({"results": [{"text": "memory", "score": 0.7, "id": "m1"}]})
        self.assertEqual(
            normalize_search_output(output),
            [{"text": "memory", "score": 0.7, "source": "m1"}],
        )


if __name__ == "__main__":
    unittest.main()
