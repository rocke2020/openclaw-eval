import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import mock

from lib import agent_provision


class AgentProvisionTests(unittest.TestCase):
    def test_created_sample_agent_removes_bootstrap_template(self):
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace-conv-26"
            workspace.mkdir()
            (workspace / "BOOTSTRAP.md").write_text("first run", encoding="utf-8")

            def fake_run(cmd, capture_output, text, check):
                if cmd[-1] == "--json":
                    return mock.Mock(returncode=0, stdout="[]", stderr="")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with (
                mock.patch.object(agent_provision, "sample_workspace", return_value=str(workspace)),
                mock.patch.object(agent_provision.subprocess, "run", side_effect=fake_run),
            ):
                result = agent_provision.ensure_sample_agent(
                    profile="eval",
                    base_agent="base",
                    base_workspace=str(Path(tmp) / "workspace"),
                    sample_id="conv-26",
                )

            self.assertTrue(result["_created"])
            self.assertFalse((workspace / "BOOTSTRAP.md").exists())


if __name__ == "__main__":
    unittest.main()
