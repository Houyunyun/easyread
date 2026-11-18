import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easyread.app import config
from easyread.server import qa_cli_api, settings_api


class Handler:
    command = 'POST'
    def __init__(self, path, body=None, origin=True):
        self.path=path;self.data=json.dumps(body or {}).encode()
        self.headers={'Host':'localhost:8765','Content-Length':str(len(self.data))}
        if origin:self.headers['Origin']='http://localhost:8765'
        self.close_connection=False
    def _body(self):return self.data
    def _json(self,status,body):self.result=(status,body)


class QaApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name)
        self.patches=[patch.object(config,'HOME',self.home/'app'),patch.object(config,'CONFIG_PATH',self.home/'app/config.json'),patch('pathlib.Path.home',return_value=self.home/'native'),patch.dict(os.environ,{'CODEX_HOME':str(self.home/'native/.codex'),'CLAUDE_CONFIG_DIR':str(self.home/'native/.claude')})]
        for p in self.patches:p.start()
        (self.home/'app').mkdir();(self.home/'native').mkdir()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_settings_save_only_selected_qa_engine(self):
        config.save({'engine':'codex','codex':{'model':'keep-model','extra_args':['--example']},'qa_cli':{'claude':{'mode':'default'}}})
        before=config.load()
        h=Handler('/api/chat/cli/codex',{'mode':'full'})
        self.assertTrue(qa_cli_api.handle(h));self.assertEqual(h.result[0],200)
        after=config.load()
        self.assertEqual(after['codex'],before['codex']);self.assertEqual(after['engine'],before['engine'])
        self.assertEqual(after['qa_cli']['claude'],before['qa_cli']['claude'])
        self.assertEqual(after['qa_cli']['codex']['mode'],'full')
        with self.assertRaises(ValueError):settings_api.save_config({'qa_cli':{'codex':{'mode':'full'}}})

    def test_requires_same_origin_and_rejects_unknown_fields(self):
        h=Handler('/api/chat/cli/claude',{'mode':'full'},origin=False)
        qa_cli_api.handle(h);self.assertEqual(h.result[0],403)
        with self.assertRaises(ValueError):qa_cli_api.handle(Handler('/api/chat/cli/claude',{'mode':'full','dangerously_skip_permissions':True}))
        self.assertFalse(config.CONFIG_PATH.exists())

    def test_import_inert_skill_is_qa_only_and_survives_policy_changes(self):
        document='---\nname: paper-review\ndescription: Review a paper\n---\nUse the requested review checklist.\n'
        h=Handler('/api/chat/cli/codex/skills/import',{'filename':'SKILL.md','content_b64':base64.b64encode(document.encode()).decode()})
        qa_cli_api.handle(h);self.assertEqual(h.result[0],200)
        item=h.result[1]['skills'][0]
        self.assertTrue(item['managed']);self.assertTrue(Path(item['path']).is_relative_to(config.HOME/'qa-skills/codex'))
        self.assertFalse((self.home/'native/.agents/skills').exists())
        self.assertFalse((self.home/'native/.codex/skills').exists())
        q=Handler('/api/chat/cli/codex',{'mode':'full','skill_overrides':{item['id']:False}})
        qa_cli_api.handle(q)
        self.assertFalse(q.result[1]['skills'][0]['enabled'])
        self.assertEqual(Path(item['path']).read_text(),document)
        q=Handler('/api/chat/cli/codex',{'mode':'full','skill_overrides':{}})
        qa_cli_api.handle(q)
        self.assertEqual(config.load()['qa_cli']['codex']['skill_overrides'],{})
        self.assertTrue(q.result[1]['skills'][0]['enabled'])
