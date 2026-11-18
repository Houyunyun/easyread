import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from easyread.library.library import Library
from easyread.library.store import Workspace, write_json_atomic
from easyread.library.summary_cache import SummaryCache
from easyread.library import trash
from easyread.weblog.cover import COVER


class SummaryCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Library(Path(self.tmp.name))
        self.ws = self.paper("abcdef123456")

    def paper(self, pid):
        ws = Workspace(self.lib.root / pid)
        ws.root.mkdir()
        write_json_atomic(ws.paper_path, {"meta": {"title_en": pid}, "blocks": [], "translation": {}})
        return ws

    def test_warm_list_avoids_json_reads_and_returns_independent_rows(self):
        self.ws.patch_item({"tags": ["original"], "meta_override": {"doi": "test"}})
        expected = self.lib.summary(self.ws)
        first = self.lib.list()
        first[0]["tags"].append("client mutation")
        first[0]["meta_override"]["doi"] = "changed"
        first[0]["links"] = {"web_url": "external"}
        with patch.object(Workspace, "load", side_effect=AssertionError("unexpected JSON read")):
            self.assertEqual(self.lib.list(), [expected])

    def test_each_summary_part_invalidates_only_its_paper(self):
        other = self.paper("bbbbbbbbbbbb")
        changes = {
            "paper": {"meta": {"title_en": "new title"}},
            "item": {"tags": ["new tag"]},
            "reader": {"progress": {"ratio": .5}},
            "discussion": {"entries": [{"body": "answer"}]},
            "job": {"state": "running", "done": 2},
        }
        self.lib.list()
        for part, data in changes.items():
            with self.subTest(part=part):
                write_json_atomic(self.ws.root / f"{part}.json", data)
                with patch.object(self.lib, "_summary", wraps=self.lib._summary) as summary:
                    rows = self.lib.list()
                self.assertEqual(summary.call_count, 1)
                self.assertEqual(summary.call_args.args[0].id, self.ws.id)
                self.assertEqual(rows, [self.lib.summary(ws) for ws in (self.ws, other)])
                if part != "paper":
                    (self.ws.root / f"{part}.json").unlink()
                    self.assertEqual(self.lib.list()[0], self.lib.summary(self.ws))

    def test_thumbnail_and_source_file_changes_invalidate(self):
        self.lib.list()
        for name in ("source.pdf", "source.html", "pages/page-001.webp", COVER):
            path = self.ws.root / name
            path.parent.mkdir(exist_ok=True)
            for operation in (lambda: path.write_bytes(b"first"), lambda: path.write_bytes(b"second"), path.unlink):
                with self.subTest(name=name, operation=operation):
                    operation()
                    with patch.object(self.lib, "_summary", wraps=self.lib._summary) as summary:
                        self.assertEqual(self.lib.list()[0], self.lib.summary(self.ws))
                    self.assertEqual(summary.call_count, 2)  # list miss + explicit reference
        (self.ws.root / COVER).write_bytes(b"cover")
        self.ws.update("paper", lambda p: p["meta"].update(source_type="web"))
        self.assertEqual(self.lib.list()[0]["thumb"], f"/p/{self.ws.id}/{COVER}")

    def test_replacement_with_preserved_size_and_mtime_invalidates(self):
        self.lib.list()
        original = self.ws.paper_path.stat()
        replacement = self.ws.root / "replacement.json"
        replacement.write_bytes(self.ws.paper_path.read_bytes().replace(b"abcdef123456", b"replacement!"))
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(self.ws.paper_path)
        self.assertEqual(self.ws.paper_path.stat().st_size, original.st_size)
        self.assertEqual(self.lib.list()[0]["title_en"], "replacement!")

    def test_deleted_restored_and_replaced_workspaces_do_not_reuse_stale_rows(self):
        self.lib.list()
        dest = self.lib.trash(self.ws.id)
        self.assertEqual(self.lib._summary_cache._papers, {})
        trash.restore(self.lib.root, dest.name)
        self.assertEqual(self.lib.list()[0]["id"], self.ws.id)
        shutil.rmtree(self.ws.root)
        self.assertEqual(self.lib.list(), [])
        self.assertEqual(self.lib._summary_cache._papers, {})
        fresh = self.paper(self.ws.id)
        fresh.patch_item({"tags": ["replacement"]})
        self.assertEqual(self.lib.list()[0]["tags"], ["replacement"])
        dest = self.lib.root / ".old"
        self.ws.root.rename(dest)
        shutil.copytree(dest, self.ws.root)  # Same timestamps, different identities; no intervening list.
        with patch.object(self.lib, "_summary", wraps=self.lib._summary) as summary:
            self.lib.list()
        self.assertEqual(summary.call_count, 1)

    def test_errors_stay_visible_and_recover_without_retaining_cached_data(self):
        self.lib.list()
        self.ws.reader_path.write_bytes(b"\x89broken")
        self.assertIn("load_error", self.lib.list()[0])
        self.assertEqual(self.lib._summary_cache._papers, {})
        self.ws.reader_path.unlink()
        self.assertNotIn("load_error", self.lib.list()[0])

    def test_read_only_summary_never_repairs_or_mutates_cached_rows(self):
        self.ws.update("paper", lambda p: p.update(translation={"done_pages": [1]}))
        before = self.ws.paper_path.read_bytes()
        with patch("easyread.library.library.page_check.repair_done") as repair:
            self.lib.summary(self.ws, repair=False)["links"] = {}
        repair.assert_not_called()
        self.assertEqual(self.ws.paper_path.read_bytes(), before)
        self.lib.list()  # Ordinary list still performs the legacy repair.
        self.assertTrue(self.ws.load("paper")["translation"]["gaps_checked"])
        self.assertNotIn("links", self.lib.list()[0])
        self.lib.summary(self.ws, repair=False)["tags"].append("external")
        self.assertEqual(self.lib.list()[0]["tags"], [])

    def test_failed_legacy_repair_is_retried_instead_of_cached(self):
        self.ws.update("paper", lambda p: p.update(translation={"done_pages": [1]}))
        with patch("easyread.library.library.page_check.repair_done", side_effect=OSError("busy")), \
                self.assertLogs("easyread", level="ERROR"):
            self.assertEqual(self.lib.list()[0]["done_pages"], 1)
        self.assertEqual(self.lib._summary_cache._papers, {})
        self.lib.list()
        self.assertTrue(self.ws.load("paper")["translation"]["gaps_checked"])

    def test_write_during_summary_is_detected_on_next_list(self):
        original = self.lib._summary

        def concurrent_write(ws):
            result = original(ws)
            ws.patch_item({"tags": ["updated during read"]})
            return result

        with patch.object(self.lib, "_summary", side_effect=concurrent_write):
            self.assertEqual(self.lib.list()[0]["tags"], [])
        self.assertEqual(self.lib.list()[0]["tags"], ["updated during read"])

    def test_entry_and_byte_limits_do_not_truncate_the_list_or_thrash_retained_rows(self):
        self.paper("bbbbbbbbbbbb")
        self.lib._summary_cache = SummaryCache(max_entries=1)
        self.assertEqual(len(self.lib.list()), 2)
        self.assertEqual(len(self.lib._summary_cache._papers), 1)
        with patch.object(self.lib, "_summary", wraps=self.lib._summary) as summary:
            self.assertEqual(len(self.lib.list()), 2)
        self.assertEqual(summary.call_count, 1)
        self.lib._summary_cache = SummaryCache(max_bytes=1)
        self.assertEqual(len(self.lib.list()), 2)
        self.assertEqual(self.lib._summary_cache._papers, {})

    def test_concurrent_lists_share_one_fill_and_independent_results(self):
        with patch.object(self.lib, "_summary", wraps=self.lib._summary) as summary:
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows = list(pool.map(lambda _: self.lib.list(), range(32)))
        self.assertEqual(summary.call_count, 1)
        self.assertTrue(all(row == rows[0] for row in rows))
        rows[0][0]["tags"].append("private")
        self.assertEqual(rows[1][0]["tags"], [])
