"""Language contracts at model boundaries; every model/network dependency is mocked."""
import io
import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easyread.app import config, i18n
from easyread.chat import answer_styles, chat, chat_models, notehelp, smart_annotations
from easyread.engines import engines
from easyread.library import planning_store
from easyread.library.store import Workspace, empty_reader, write_json_atomic
from easyread.research import comparison, deep_analysis, mindmaps, obsidian_export, prompts, proposals, store, tasks, workflows, workspace
from easyread.research.language import output_rule
from easyread.translate import langs


class AILanguageTest(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.ws = Workspace(self.root / "paper-a")
        self.other = Workspace(self.root / "paper-b")
        self.quote = "原始引句：這項證據不可改寫。"
        self.note = "我的筆記：保留資料、公式 $x=1$ 與 ID source-1。"
        for ws in (self.ws, self.other):
            ws.root.mkdir()
            write_json_atomic(ws.root / "paper.json", {
                "meta": {"title_en": "Source title"},
                "blocks": [{"id": "b1", "type": "para", "page": 1, "en": self.quote}],
            })
            reader = empty_reader()
            reader["paper_note"] = {"body": self.note}
            reader["notes"] = {"n1": {"anchor": "b1", "body": self.note}}
            write_json_atomic(ws.root / "reader.json", reader)
        self.lib = SimpleNamespace(root=self.root, all=lambda: [self.ws, self.other],
                                   ws=lambda pid: {self.ws.id: self.ws, self.other.id: self.other}.get(pid))
        self.app = SimpleNamespace(lib=self.lib)
        self.context.enter_context(patch.object(config, "load", return_value={}))
        self.context.enter_context(patch.object(config, "HOME", self.root))
        self.context.enter_context(patch.object(chat_models, "engine_cfg", return_value=({"engine": "test"}, {"id": "test", "name": "Test"})))
        self.context.enter_context(patch.object(engines, "for_translation", side_effect=lambda cfg: cfg))
        self.context.enter_context(patch.object(tasks, "submit", side_effect=self.run_task))
        for module in (proposals, store, obsidian_export, workflows):
            self.context.enter_context(patch.object(module, "vault_path", return_value=self.root))
        self.context.enter_context(patch.object(proposals, "state_dir", return_value=self.root / "state"))
        self.sources = [{"title": "Source title", "quote": self.quote, "path": "paper-a", "block": "b1", "section": "Original section"}]
        self.context.enter_context(patch.object(workflows, "gather", return_value={"sources": self.sources, "index": {}}))
        self.context.enter_context(patch.object(workspace, "_search_works", return_value={"results": []}))
        self.context.enter_context(patch.object(workspace, "_openalex", side_effect=AssertionError("No network in language tests")))
        self.prompts = []
        self.reply = "Generated body"
        self.context.enter_context(patch.object(engines, "run", side_effect=self.model))

    @staticmethod
    def run_task(kind, runner, **kwargs):
        return {"kind": kind, "result": runner(threading.Event(), lambda *args, **kw: None)}

    def model(self, cfg, prompt, *args, **kwargs):
        self.prompts.append(prompt)
        return self.reply

    def set_target(self, target):
        self.ws.update("paper", lambda paper: paper["meta"].update(target=target))

    def assert_language(self, target, prompt=None):
        text = prompt if prompt is not None else self.prompts[-1]
        self.assertIn(output_rule(target), text)
        for other in ("zh", "en", "zh-Hant", "it"):
            if other != target:
                self.assertNotIn("输出语言：只用" + langs.reply_lang({"target": other}), text)
        self.assertIn("原文引句必须逐字保留，不翻译", text)

    def test_resolver_aliases_and_existing_reply_semantics(self):
        with patch.object(i18n, "lang", return_value="en"):
            self.assertEqual(langs.reply_code({}), "en")
            self.assertEqual(langs.reply_code({"title_zh": "旧译文"}), "zh")
            for alias in ("zh-TW", "zh_HK", "ZH-hant", "zh-MO"):
                self.assertEqual(langs.reply_code({"target": alias}), "zh-Hant")
                self.assertEqual(langs.of_paper({"target": alias}), "zh-Hant")
            self.assertEqual(langs.reply_code({"target": "zh-CN"}), "zh")
            self.assertEqual(langs.reply_code({"target": "unknown"}), "en")
        self.assertIn("Simplified Chinese，仅用简体字", langs.reply_lang({"target": "zh"}))
        self.assertIn("Traditional Chinese，仅用繁体字", langs.reply_lang({"target": "zh-Hant"}))

    def test_smart_annotation_generation_preserves_quotes_and_records_target(self):
        self.reply = json.dumps({"annotations": [{"anchor": "b1", "key": "b1", "quote": self.quote,
            "type": "highlight", "color": "yellow", "note": "AI note", "reason": "AI reason", "confidence": 0.9}]})
        for target in ("zh", "en", "zh-Hant", "it"):
            with self.subTest(target=target), patch.object(i18n, "lang", return_value="en"):
                self.set_target(target)
                result = smart_annotations.generate(self.ws)
                self.assert_language(target)
                self.assertIn(self.quote, self.prompts[-1])
                self.assertEqual(result["target"], target)
                saved = list(self.ws.load("reader")["ai_annotations"].values())
                self.assertEqual(saved[-1]["target"], target)
                self.assertEqual(saved[-1]["quote"], self.quote)
                self.assertEqual(self.ws.load("reader")["paper_note"]["body"], self.note)

    def test_deep_analysis_and_all_nine_mindmap_targets_at_engine_boundary(self):
        for target in langs.TARGETS:
            with self.subTest(target=target), patch.object(i18n, "lang", return_value="en"):
                self.set_target(target)
                self.reply = "Generated report"
                result = deep_analysis.start_deep_analysis_task(self.app, self.ws.id)["result"]["result"]
                self.assert_language(target)
                self.assertEqual(result["target"], target)
                self.assertEqual(deep_analysis.get_report(self.ws)["target"], target)
                self.assertIn(self.quote, self.prompts[-1])
                self.reply = "mindmap\n  root((Generated))"
                result = workspace.post(self.app, f"/paper/{self.ws.id}/mindmap", {})
                self.assert_language(target)
                self.assertEqual(result["target"], target)
                for branch in prompts.MINDMAP_BRANCHES[target]:
                    self.assertIn(branch, self.prompts[-1])
                cached = workspace.get(self.app, workspace.PREFIX + f"/paper/{self.ws.id}/mindmap")
                self.assertTrue(cached["cached"])
                self.assertEqual(cached["target"], target)
        self.assertIn("研究背景と課題", prompts.MINDMAP_BRANCHES["ja"][0])
        self.assertIn("Contesto", prompts.MINDMAP_BRANCHES["it"][0])

    def test_notehelp_draft_revise_review_at_stream_boundary(self):
        def stream(cfg, text, *args):
            self.prompts.append(text)
            yield "Generated note"
        handler = SimpleNamespace(wfile=io.BytesIO(), send_response=lambda *a: None,
                                  send_header=lambda *a: None, end_headers=lambda: None)
        with patch.object(chat, "stream", side_effect=stream):
            for target in ("zh", "en", "zh-Hant", "it"):
                self.set_target(target)
                for mode in notehelp.ASK:
                    with self.subTest(target=target, mode=mode):
                        handler.wfile = io.BytesIO()
                        notehelp.handle(handler, self.ws, {"mode": mode, "note": self.note})
                        self.assert_language(target)
                        self.assertIn(self.note, self.prompts[-1])
                        payload = [json.loads(line) for line in handler.wfile.getvalue().splitlines()]
                        self.assertEqual(payload[0]["target"], target)
                        self.assertEqual(self.ws.load("reader")["paper_note"]["body"], self.note)

    def test_candidate_summaries_relations_routes_follow_ui_not_body_lang(self):
        paper = {"id": "W1", "openalex_id": "W1", "title": "Source title", "abstract": self.quote}
        for target in ("zh", "en", "zh-Hant"):
            with self.subTest(target=target), patch.object(i18n, "lang", return_value=target):
                self.reply = "Generated summary"
                for endpoint, body in (("/ai-summary", {"papers": [paper]}),
                                       ("/ai-category-explain", {"paper": paper, "category": "My category"})):
                    result = workspace.post(self.app, endpoint, {**body, "lang": "en"})
                    self.assert_language(target)
                    self.assertEqual(result["target"], target)
                    self.assertIn(self.quote, self.prompts[-1])
                self.reply = '[{"id":"openalex:W1","role":"Role","reason":"Reason","priority":1}]'
                result = workspace.post(self.app, "/reading-path", {"topic": "Topic", "papers": [paper], "lang": "en"})
                self.assert_language(target)
                self.assertEqual(result["target"], target)
                self.assertEqual(result["path"]["target"], target)
                self.assertEqual(result["results"][0]["paper_key"], "openalex:W1")

    def test_background_candidate_summary_metadata_and_trash_roundtrip(self):
        for target in ("zh", "en", "zh-Hant"):
            with self.subTest(target=target), patch.object(i18n, "lang", return_value=target):
                row = planning_store.candidate_add(self.root, "doi:10.1234/" + target, {"doi": "10.1234/" + target, "title": "Source", "abstract": self.quote})
                key = row["paper_key"]
                self.reply = json.dumps([{"paper_key": key, "summary_markdown": "Generated summary"}])
                with patch.object(workspace._time, "sleep"):
                    workspace._summary_worker(self.app)
                self.assert_language(target)
                saved = planning_store.summary(self.root, key)
                self.assertEqual(saved["summary_target"], target)
                trashed = planning_store.summary_move_to_trash(self.root, key)
                planning_store.summary_trash_restore(self.root, trashed["trash_id"])
                self.assertEqual(planning_store.summary(self.root, key)["summary_target"], target)

    def test_comparison_extract_condense_report_title_preserve_wire_and_custom_dimensions(self):
        dims = ["研究問題", "資料集", "評估指標", "實驗條件", "CUSTOM 資料"]
        dictionaries = {"zh": {}, "en": {"研究问题": "Research problem", "资料集": "Datasets", "评估指标": "Metrics", "实验条件": "Experimental conditions"},
                        "zh-Hant": {"研究问题": "研究問題", "资料集": "資料集", "评估指标": "評估指標", "实验条件": "實驗條件"}}
        for target in dictionaries:
            with self.subTest(target=target), patch.object(i18n, "lang", return_value=target), patch.object(i18n, "ui_dict", side_effect=lambda code: dictionaries[code]):
                self.prompts.clear()
                result = comparison.start(self.lib, [self.ws.id, self.other.id], dims)
                self.assertEqual(len(self.prompts), 6)  # extract/card per paper, report, title
                for prompt in self.prompts:
                    self.assert_language(target, prompt)
                    self.assertIn("CUSTOM 資料", prompt)
                    self.assertIn(dictionaries[target].get("研究问题", "研究问题"), prompt)
                self.assertEqual(result["result"]["proposal"]["output_target"], target)
                self.assertIn(self.quote, self.prompts[0])
                self.assertIn(self.note, self.prompts[0])
        self.assertEqual(dims[0], "研究問題")
        self.assertEqual(comparison.DEFAULT_DIMENSIONS[0], "研究問題")

    def test_research_note_answers_and_proposals_use_ui_language(self):
        self.set_target("it")  # research-note workflows remain UI-scoped
        for target in ("zh", "en", "zh-Hant"):
            with self.subTest(target=target), patch.object(i18n, "lang", return_value=target):
                for kind in workflows.KIND_GUIDANCE:
                    result = workflows.answer("Task", kind, self.lib, paper_id=self.ws.id)
                    self.assert_language(target)
                    self.assertEqual(result["target"], target)
                proposal = proposals.create("Original user title", "paper", "Task", self.lib)
                self.assert_language(target)
                self.assertEqual(proposal["output_target"], target)
                self.assertEqual(proposal["title"], "Original user title")
                self.assertFalse((self.root / proposal["target"]).exists())

    def test_intentionally_english_query_rewriting_and_paraphrasing(self):
        self.reply = '["English alternative"]'
        for target in ("zh", "en", "zh-Hant"):
            with patch.object(i18n, "lang", return_value=target):
                for endpoint, body in (("/ai-query", {"query": "研究主題"}),
                                       ("/ai-query", {"title": "研究主題", "abstract": self.quote}),
                                       ("/ai-rewrite", {"selected_text": "Source claim", "context": self.note})):
                    result = workspace.post(self.app, endpoint, body)
                    self.assertEqual(result["target"], "en")
                    self.assertIn("英文", self.prompts[-1])
                    self.assertNotIn("繁体中文研究主题", self.prompts[-1])

    def test_locale_switch_cannot_reuse_mindmap_or_reading_path_cache(self):
        _, source_hash = workspace._mindmap_source(self.ws.load("paper"))
        planning_store.cache_put(self.root, "mindmap:" + sha256(source_hash.encode()).hexdigest(), {"mermaid": "mindmap\n  root((Legacy))"})
        with patch.object(i18n, "lang", return_value="en"):
            self.assertFalse(mindmaps.offline_snapshot(self.ws)["mindmap"]["cached"])
            self.reply = "mindmap\n  root((English))"
            workspace.post(self.app, f"/paper/{self.ws.id}/mindmap", {})
            english = planning_store.replace_reading_path(self.root, {"target": "en", "results": [{"paper_key": "W1"}]})
        with patch.object(i18n, "lang", return_value="zh-Hant"):
            self.assertFalse(workspace.get(self.app, workspace.PREFIX + f"/paper/{self.ws.id}/mindmap")["cached"])
            self.assertFalse(mindmaps.offline_snapshot(self.ws)["mindmap"]["cached"])
            self.assertIsNone(planning_store.latest_reading_path(self.root))
        with patch.object(i18n, "lang", return_value="en"):
            self.assertEqual(planning_store.latest_reading_path(self.root)["path_id"], english["path_id"])
            self.assertTrue(mindmaps.offline_snapshot(self.ws)["mindmap"]["cached"])

    def test_default_status_labels_translate_but_user_renames_do_not(self):
        with patch.object(i18n, "lang", return_value="en"), patch.object(i18n, "ui_dict", return_value={"待阅读": "To read", "阅读中": "Reading"}):
            values = planning_store.statuses(self.root)
            self.assertEqual(values[0]["label"], "To read")
            values[1]["label"] = "我的自訂閱讀狀態"
            values = planning_store.save_statuses(self.root, values)
            self.assertEqual(values[1]["label"], "我的自訂閱讀狀態")
        with patch.object(i18n, "lang", return_value="zh"):
            values = planning_store.statuses(self.root)
            self.assertEqual(values[0]["label"], "待阅读")
            self.assertEqual(values[1]["label"], "我的自訂閱讀狀態")

    def test_export_labels_follow_ui_without_converting_document_or_user_folders(self):
        docs = [{"id": "paper:original", "kind": "analysis", "title": "原始標題", "body": self.note,
                 "subfolder": "我的資料夾", "links": ["paper:linked"]},
                {"id": "paper:linked", "kind": "mindmap", "title": "Linked", "body": self.quote}]
        labels = {"01-论文分析": "01-Paper Analysis", "02-心智图": "02-Mindmaps", "## 相关笔记": "## Related notes"}
        with patch.object(i18n, "lang", return_value="en"), patch.object(i18n, "ui_dict", return_value=labels):
            result = obsidian_export.export_to_vault(docs)
        self.assertIn("Research/01-Paper Analysis/我的資料夾/原始標題.md", result["written"])
        note_path = self.root / result["written"][0]
        text = note_path.read_text()
        self.assertIn(self.note, text)
        self.assertIn("## Related notes", text)
        # Re-export in another UI locale preserves a managed note's existing path.
        with patch.object(i18n, "lang", return_value="zh"):
            updated = obsidian_export.export_to_vault(docs)
        self.assertEqual(updated["updated"], result["written"])
        self.assertIn(self.note, note_path.read_text())

    def test_paper_task_captures_language_before_background_generation(self):
        # A later UI change cannot change a queued task's requested output language.
        self.reply = "Generated report"
        queued = []
        with patch.object(tasks, "submit", side_effect=lambda kind, run, **kw: queued.append(run) or {}), \
                patch.object(i18n, "lang", return_value="zh-Hant"):
            deep_analysis.start_deep_analysis_task(self.app, self.ws.id)
        with patch.object(i18n, "lang", return_value="en"):
            result = queued[0](threading.Event(), lambda *args, **kw: None)
        self.assert_language("zh-Hant")
        self.assertEqual(result["result"]["target"], "zh-Hant")

    def test_ste_style_never_reintroduces_fixed_chinese_output(self):
        for target in ("zh", "en", "zh-Hant", "it"):
            text = answer_styles.ste100_instructions({"target": target})
            self.assertIn(langs.reply_lang({"target": target}), text)
            self.assertNotIn("只输出中文回答", text)


if __name__ == "__main__":
    unittest.main()
