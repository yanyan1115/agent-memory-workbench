import contextlib
import io
import json
import math
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_memory_workbench import lifecycle, recall
from agent_memory_workbench.core import MemoryError, atomic_write, resolve_root, safe_path, validate_timeout
from agent_memory_workbench.mirror import publish
from agent_memory_workbench.search import Provider, build_index, cache_path, overlap, search, state_dir


def memory(name, body, *, visibility="public", kind="note"):
    return f"""---
schema_version: 1
name: {name}
description: Notes about {name}
type: {kind}
status: active
visibility: {visibility}
tags: []
---

{body}
"""


class FakeProvider(Provider):
    def __init__(self, fail_on=None):
        super().__init__("fake", "v1", None, "UNUSED")
        self.fail_on = fail_on

    def embed(self, text, *, query):
        if self.fail_on and self.fail_on in text:
            raise MemoryError("synthetic provider failure")
        lowered = text.lower()
        vector = [float(lowered.count("harbor") + 1), float(lowered.count("garden") + 1)]
        norm = math.sqrt(sum(item * item for item in vector))
        return [item / norm for item in vector]


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "memory"
        self.assertEqual(lifecycle.main(["init", str(self.root)]), 0)
        self.state = Path(self.temp.name) / "state"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def refresh(self):
        self.assertEqual(lifecycle.main(["index", "--root", str(self.root), "write"]), 0)

    def test_lifecycle_candidate_promote_and_doctor(self):
        body = self.write("draft.txt", "A durable garden note.")
        rc = lifecycle.main([
            "candidate", "--root", str(self.root), "--name", "garden-note",
            "--description", "Garden note", "--type", "note", "--body-file", str(body),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / "inbox/public/garden-note.md").exists())
        self.assertEqual(lifecycle.main([
            "promote", "--root", str(self.root), "inbox/public/garden-note.md", "--to", "active",
            "--reason", "reviewed and approved"
        ]), 0)
        self.assertTrue((self.root / "active/garden-note.md").exists())
        self.assertEqual(lifecycle.main(["doctor", "--root", str(self.root)]), 0)
        audit = (self.root / ".memory-workbench-audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "candidate"', audit)
        self.assertIn('"action": "promote"', audit)

    def test_doctor_checks_hot_budget_and_memory_links(self):
        self.write("active/target.md", memory("target", "# Existing heading\n\nBody."))
        self.write("active/source.md", memory("source", "Related: [[target#Missing heading]]."))
        self.refresh()
        (self.root / "MEMORY.md").write_text(
            "# Memory\n\n- [Missing](active/missing.md) - " + "x" * 220 + "\n",
            encoding="utf-8",
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(lifecycle.main(["doctor", "--root", str(self.root)]), 1)
        self.assertIn("dead link", output.getvalue())
        self.assertIn("maximum is 200", output.getvalue())
        self.assertIn("broken wiki heading", output.getvalue())

    def test_archive_blocks_hot_link_and_update_records_reason(self):
        self.write("active/target.md", memory("target", "Old body."))
        self.refresh()
        (self.root / "MEMORY.md").write_text(
            "# Memory\n\n- [Target](active/target.md) - Hot pointer.\n", encoding="utf-8"
        )
        self.assertEqual(lifecycle.main([
            "archive", "--root", str(self.root), "target", "--reason", "superseded"
        ]), 2)
        body = self.write("new-body.txt", "New body.")
        self.assertEqual(lifecycle.main([
            "update", "--root", str(self.root), "target", "--reason", "corrected evidence",
            "--body-file", str(body)
        ]), 0)
        audit = (self.root / ".memory-workbench-audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("corrected evidence", audit)
        self.assertIn("before_sha256", audit)

    def test_private_candidate_and_search_are_opt_in(self):
        self.write("active/public.md", memory("public", "The public harbor guide."))
        self.write("private/secret.md", memory("secret", "The private moon harbor.", visibility="private"))
        self.write("active/misplaced.md", memory("misplaced", "The misplaced moon harbor.", visibility="private"))
        self.refresh()
        public = search(self.root, "moon harbor", directory=self.state, provider=None,
                        include_private=False, limit=10, lock_timeout=1)
        private = search(self.root, "moon harbor", directory=self.state, provider=None,
                         include_private=True, limit=10, lock_timeout=1)
        self.assertEqual([item["path"] for item in public], ["active/public.md"])
        self.assertIn("private/secret.md", [item["path"] for item in private])
        self.assertNotIn("active/misplaced.md", [item["path"] for item in public])

    def test_candidates_are_not_searchable(self):
        self.write("inbox/public/draft.md", memory("draft", "orphan comet"))
        results = search(self.root, "orphan comet", directory=self.state, provider=None,
                         include_private=False, limit=10, lock_timeout=1)
        self.assertEqual(results, [])

    def test_semantic_cache_is_outside_root_and_has_no_plaintext(self):
        self.write("active/harbor.md", memory("harbor", "A harbor maintenance checklist."))
        self.refresh()
        self.assertEqual(build_index(self.root, self.state, FakeProvider(), False, 1), 0)
        path = cache_path(self.state, False)
        self.assertFalse(path.is_relative_to(self.root))
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("maintenance checklist", raw)
        self.assertNotIn("content", json.loads(raw)["records"][0])

    def test_failed_index_does_not_replace_previous_generation(self):
        self.write("active/harbor.md", memory("harbor", "A stable harbor note."))
        self.refresh()
        build_index(self.root, self.state, FakeProvider(), False, 1)
        path = cache_path(self.state, False)
        before = path.read_bytes()
        self.write("active/harbor.md", memory("harbor", "FAIL changed harbor note."))
        with self.assertRaises(MemoryError):
            build_index(self.root, self.state, FakeProvider("FAIL"), False, 1)
        self.assertEqual(path.read_bytes(), before)

    def test_changed_content_cannot_use_stale_vector(self):
        self.write("active/topic.md", memory("topic", "The harbor is important."))
        self.refresh()
        build_index(self.root, self.state, FakeProvider(), False, 1)
        self.write("active/topic.md", memory("topic", "The garden is important."))
        results = search(self.root, "harbor", directory=self.state, provider=FakeProvider(),
                         include_private=False, limit=5, lock_timeout=1)
        self.assertEqual(results, [])

    def test_overlap_finds_cross_file_near_duplicates(self):
        self.write("active/harbor-one.md", memory("harbor-one", "Harbor safety checklist."))
        self.write("active/harbor-two.md", memory("harbor-two", "Harbor safety checklist."))
        self.refresh()
        build_index(self.root, self.state, FakeProvider(), False, 1)
        pairs = overlap(self.root, directory=self.state, include_private=False,
                        threshold=0.99, limit=5, target=None, exclude=[], lock_timeout=1)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["left"]["path"], "active/harbor-one.md")

    def test_atomic_write_preserves_mode(self):
        path = self.root / "mode.txt"
        path.write_text("old", encoding="utf-8")
        path.chmod(0o640)
        atomic_write(path, "new")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_paths_and_finite_timeout(self):
        with self.assertRaises(MemoryError):
            safe_path(self.root, "../escape")
        for value in (math.nan, math.inf, -1):
            with self.assertRaises(MemoryError):
                validate_timeout(value)
        target = Path(self.temp.name) / "outside"
        target.write_text("x", encoding="utf-8")
        (self.root / "active/link.md").symlink_to(target)
        with self.assertRaises(MemoryError):
            safe_path(self.root, "active/link.md", must_exist=True)

    def test_recall_is_bounded_and_fail_open(self):
        self.write("active/harbor.md", memory("harbor", "Harbor clue " * 100))
        self.refresh()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = recall.main([
                "--root", str(self.root), "--state-dir", str(self.state),
                "--max-excerpt-chars", "40", "--max-total-chars", "500", "harbor"
            ])
        self.assertEqual(rc, 0)
        self.assertIn("Historical clues only", output.getvalue())
        with mock.patch("agent_memory_workbench.recall.search", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stdout(io.StringIO()) as failed:
                self.assertEqual(recall.main(["--root", str(self.root), "harbor"]), 0)
                self.assertEqual(failed.getvalue(), "")
        with mock.patch("agent_memory_workbench.recall.search") as skipped:
            self.assertEqual(recall.main(["--root", str(self.root), "thanks"]), 0)
            skipped.assert_not_called()

    def test_mirror_is_validated_versioned_and_read_only(self):
        self.write("active/harbor.md", memory("harbor", "A stable harbor note."))
        self.refresh()
        destination = Path(self.temp.name) / "mirror"
        release = publish(self.root, destination, keep=2, lock_timeout=1)
        self.assertTrue((destination / "current/MEMORY.md").is_file())
        self.assertEqual((destination / "current").resolve(), release)
        self.assertEqual(stat.S_IMODE((release / "MEMORY.md").stat().st_mode) & 0o222, 0)


if __name__ == "__main__":
    unittest.main()
