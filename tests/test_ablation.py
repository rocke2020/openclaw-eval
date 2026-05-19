"""Tests for retrieval-only ablation helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lib.ablation import (
    clone_memory_snapshot,
    collect_sample_ids,
    derive_source_base_workspace,
    extract_memory_search_details,
    inspect_search_evidence,
    iter_session_records,
    list_memory_files,
    paired_buckets,
    render_paired_summary_markdown,
    source_workspace_for_sample,
    verify_memory_hashes,
)


def _seed_workspace(workspace: Path, memory_text: str, daily: dict[str, str]) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "MEMORY.md").write_text(memory_text, encoding="utf-8")
    (workspace / "memory").mkdir(exist_ok=True)
    for name, body in daily.items():
        (workspace / "memory" / name).write_text(body, encoding="utf-8")


class CloneMemorySnapshotTests(unittest.TestCase):
    def test_clone_copies_memory_files_and_returns_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            _seed_workspace(src, "durable memory", {"2026-05-08.md": "daily one"})
            (dst).mkdir()
            (dst / "AGENTS.md").write_text("template", encoding="utf-8")

            record = clone_memory_snapshot(src, dst)

            self.assertEqual(
                sorted(r["path"] for r in record["files"]),
                ["MEMORY.md", "memory/2026-05-08.md"],
            )
            self.assertEqual((dst / "MEMORY.md").read_text(encoding="utf-8"), "durable memory")
            self.assertEqual((dst / "AGENTS.md").read_text(encoding="utf-8"), "template")

    def test_clone_overwrites_existing_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            _seed_workspace(src, "new", {"2026-05-08.md": "fresh"})
            _seed_workspace(dst, "stale", {"2026-05-08.md": "stale"})

            clone_memory_snapshot(src, dst)
            self.assertEqual((dst / "MEMORY.md").read_text(encoding="utf-8"), "new")
            self.assertEqual(
                (dst / "memory" / "2026-05-08.md").read_text(encoding="utf-8"), "fresh"
            )

    def test_verify_hashes_detects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            _seed_workspace(src, "alpha", {"2026-05-08.md": "one"})
            _seed_workspace(dst, "alpha", {"2026-05-08.md": "different"})

            verification = verify_memory_hashes(src, dst)
            self.assertFalse(verification["ok"])
            self.assertEqual(len(verification["mismatched"]), 1)
            self.assertEqual(verification["mismatched"][0]["path"], "memory/2026-05-08.md")

    def test_verify_hashes_detects_extra_destination_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dst = Path(tmp) / "dst"
            _seed_workspace(src, "alpha", {"2026-05-08.md": "one"})
            _seed_workspace(dst, "alpha", {"2026-05-08.md": "one", "stray.md": "extra"})

            verification = verify_memory_hashes(src, dst)
            self.assertFalse(verification["ok"])
            self.assertIn("memory/stray.md", verification["only_in_dest"])

    def test_list_memory_files_orders_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _seed_workspace(
                workspace,
                "durable",
                {"2026-05-08.md": "a", "2026-05-09.md": "b"},
            )
            paths = list_memory_files(workspace)
            self.assertEqual(
                [str(p) for p in paths],
                ["MEMORY.md", "memory/2026-05-08.md", "memory/2026-05-09.md"],
            )


class VerificationParseTests(unittest.TestCase):
    def test_derive_source_base_workspace_strips_sample_suffix(self):
        verification = {
            "samples": [
                {
                    "sample_id": "conv-26",
                    "created": [
                        "/tmp/store/workspace-vector-20260518-conv-26/MEMORY.md",
                        "/tmp/store/workspace-vector-20260518-conv-26/memory/2026-05-08.md",
                    ],
                },
                {
                    "sample_id": "conv-30",
                    "created": [
                        "/tmp/store/workspace-vector-20260518-conv-30/MEMORY.md",
                    ],
                },
            ]
        }
        base = derive_source_base_workspace(verification)
        self.assertEqual(base, "/tmp/store/workspace-vector-20260518")

    def test_source_workspace_for_sample_resolves_memory_subdir(self):
        verification = {
            "samples": [
                {
                    "sample_id": "conv-26",
                    "created": [
                        "/tmp/ws-conv-26/memory/2026-05-08.md",
                    ],
                }
            ]
        }
        path = source_workspace_for_sample(verification, "conv-26")
        self.assertEqual(str(path), "/tmp/ws-conv-26")

    def test_collect_sample_ids_preserves_order(self):
        verification = {
            "samples": [
                {"sample_id": "conv-26"},
                {"sample_id": "conv-30"},
                {"sample_id": "conv-41"},
            ]
        }
        self.assertEqual(collect_sample_ids(verification), ["conv-26", "conv-30", "conv-41"])


class SearchEvidenceTests(unittest.TestCase):
    def test_extract_memory_search_details_from_details(self):
        record = {
            "message": {
                "role": "toolResult",
                "toolName": "memory_search",
                "details": {"provider": "ollama", "model": "qwen3-embedding:0.6b"},
            }
        }
        details = extract_memory_search_details(record)
        self.assertIsNotNone(details)
        assert details is not None
        self.assertEqual(details["provider"], "ollama")

    def test_extract_memory_search_details_from_content_text(self):
        payload = {"provider": "builtin", "debug": {"backend": "builtin"}}
        record = {
            "message": {
                "role": "toolResult",
                "toolName": "memory_search",
                "content": [{"type": "text", "text": json.dumps(payload)}],
            }
        }
        details = extract_memory_search_details(record)
        self.assertEqual(details, payload)

    def test_extract_returns_none_for_other_tools(self):
        record = {"message": {"role": "toolResult", "toolName": "memory_get", "details": {}}}
        self.assertIsNone(extract_memory_search_details(record))

    def test_inspect_search_evidence_flags_vector_when_forbidden(self):
        items = [
            {
                "path": "/tmp/a.jsonl",
                "line": 1,
                "details": {
                    "provider": "ollama",
                    "model": "qwen3-embedding:0.6b",
                    "debug": {"backend": "builtin"},
                },
            }
        ]
        report = inspect_search_evidence(items, forbid_vector=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["evidence_count"], 1)
        self.assertTrue(any("vector provider" in f for f in report["failures"]))
        self.assertTrue(any("vector model" in f for f in report["failures"]))

    def test_inspect_search_evidence_ok_for_keyword_only(self):
        items = [
            {
                "path": "/tmp/a.jsonl",
                "line": 5,
                "details": {
                    "provider": "builtin",
                    "model": None,
                    "debug": {"backend": "builtin"},
                },
            }
        ]
        report = inspect_search_evidence(items, forbid_vector=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["backends"], {"builtin": 1})

    def test_inspect_search_evidence_fails_on_empty_evidence(self):
        report = inspect_search_evidence([], forbid_vector=True)
        self.assertFalse(report["ok"])
        self.assertEqual(report["evidence_count"], 0)

    def test_inspect_search_evidence_flags_qmd(self):
        items = [
            {
                "path": "/tmp/a.jsonl",
                "line": 9,
                "details": {"provider": "qmd", "model": "qmd"},
            }
        ]
        report = inspect_search_evidence(items, forbid_vector=False, forbid_qmd=True)
        self.assertFalse(report["ok"])
        self.assertTrue(any("qmd evidence" in f for f in report["failures"]))

    def test_iter_session_records_yields_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / "agents" / "ag-1" / "sessions"
            sessions.mkdir(parents=True)
            log = sessions / "2026-05-19T00-00-00.jsonl"
            log.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "message": {
                                    "role": "toolResult",
                                    "toolName": "memory_search",
                                    "details": {"provider": "builtin"},
                                }
                            }
                        ),
                        "",
                        "{not json",
                    ]
                ),
                encoding="utf-8",
            )
            items = list(iter_session_records(home, "ag-1"))
            self.assertEqual(len(items), 1)
            details = extract_memory_search_details(items[0]["record"])
            self.assertEqual(details, {"provider": "builtin"})


class PairedBucketsTests(unittest.TestCase):
    def _grade(self, sample_id: str, qi: int, grade: bool, category: str = "1") -> dict:
        return {"sample_id": sample_id, "qi": qi, "grade": grade, "category": category}

    def test_paired_buckets_counts_categories(self):
        grades_a = [
            self._grade("conv-26", 1, True, "1"),
            self._grade("conv-26", 2, True, "2"),
            self._grade("conv-30", 1, False, "1"),
            self._grade("conv-30", 2, True, "2"),
        ]
        grades_b = [
            self._grade("conv-26", 1, True, "1"),
            self._grade("conv-26", 2, False, "2"),
            self._grade("conv-30", 1, True, "1"),
            self._grade("conv-30", 2, False, "2"),
        ]
        result = paired_buckets(grades_a, grades_b)
        self.assertEqual(result["paired_total"], 4)
        self.assertEqual(result["buckets"]["both_correct"], 1)
        self.assertEqual(result["buckets"]["a_only_correct"], 2)
        self.assertEqual(result["buckets"]["b_only_correct"], 1)
        self.assertEqual(result["buckets"]["both_wrong"], 0)
        self.assertEqual(result["a_correct"], 3)
        self.assertEqual(result["b_correct"], 2)
        self.assertEqual(result["net_b_minus_a"], -1)
        per_cat = result["per_category"]
        self.assertEqual(per_cat["1"]["b_only_correct"], 1)
        self.assertEqual(per_cat["2"]["a_only_correct"], 2)

    def test_paired_buckets_reports_unpaired_rows(self):
        grades_a = [self._grade("conv-26", 1, True)]
        grades_b = [self._grade("conv-30", 1, True)]
        result = paired_buckets(grades_a, grades_b)
        self.assertEqual(result["paired_total"], 0)
        self.assertEqual(result["only_in_a"], [{"sample_id": "conv-26", "qi": 1}])
        self.assertEqual(result["only_in_b"], [{"sample_id": "conv-30", "qi": 1}])

    def test_render_paired_summary_markdown_includes_buckets(self):
        result = paired_buckets(
            [self._grade("conv-26", 1, True)], [self._grade("conv-26", 1, False)]
        )
        markdown = render_paired_summary_markdown(result, label_a="vector", label_b="no-vector")
        self.assertIn("Both correct | 0", markdown)
        self.assertIn("vector-only correct | 1", markdown)
        self.assertIn("Net no-vector delta | -1", markdown)


if __name__ == "__main__":
    unittest.main()
