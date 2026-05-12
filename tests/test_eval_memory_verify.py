import tempfile
import unittest
from pathlib import Path

from eval_memory_verify import diff_memory_snapshots, snapshot_memory_files


class EvalMemoryVerifyTests(unittest.TestCase):
    def test_snapshot_memory_files_reads_memory_and_daily_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "MEMORY.md").write_text("durable", encoding="utf-8")
            (root / "memory").mkdir()
            (root / "memory" / "2026-05-12.md").write_text("daily", encoding="utf-8")
            snapshot = snapshot_memory_files(str(root))
            self.assertEqual(len(snapshot), 2)

    def test_diff_memory_snapshots_detects_modified_file(self):
        before = {"MEMORY.md": {"sha256": "old"}}
        after = {"MEMORY.md": {"sha256": "new"}}
        self.assertTrue(diff_memory_snapshots(before, after)["write_detected"])


if __name__ == "__main__":
    unittest.main()
