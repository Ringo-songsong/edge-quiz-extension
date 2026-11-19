import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure
import model_api as api
import server


class ClaudeSetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / ".env"
        env = patch.dict(os.environ, {"QUIZ_ENV_FILE": str(self.path)}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def serve(self, httpd):
        worker = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        worker.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd

    def test_official_and_custom_key_isolation(self):
        for name in ("claude", "anthropic"):
            cfg = api.config_from({"MODEL_PROVIDER": name, "ANTHROPIC_API_KEY": "fixture"})
            self.assertEqual(cfg.endpoint, "https://api.anthropic.com/v1/messages")
            self.assertEqual(cfg.protocol, "anthropic")
        with self.assertRaisesRegex(api.AnswerError, "ANTHROPIC_API_KEY"):
            api.config_from({"MODEL_PROVIDER": "anthropic", "OPENAI_API_KEY": "fixture"})
        for base in ("https://example.org/p", "https://example.org/p/v1/", "https://example.org/p/v1/messages"):
            cfg = api.config_from({"MODEL_PROVIDER": "custom", "CUSTOM_API_FORMAT": "anthropic",
                                   "CUSTOM_BASE_URL": base, "CUSTOM_MODEL": "my-model", "CUSTOM_API_KEY": "custom",
                                   "ANTHROPIC_API_KEY": "ignored", "ANTHROPIC_WORKSPACE_ID": "ignored"})
            self.assertEqual((cfg.endpoint, cfg.key, cfg.workspace),
                             ("https://example.org/p/v1/messages", "custom", ""))

    def test_native_protocol_over_http(self):
        received = []
        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path, self.headers, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"type": "message", "stop_reason": "end_turn", "content": [
                    {"type": "thinking", "thinking": "ignore"}, {"type": "text", "text": '{"choice":2}'}]}).encode())

            def log_message(self, *args):
                pass

        port = self.serve(HTTPServer(("127.0.0.1", 0), Endpoint)).server_port
        self.path.write_text(f"MODEL_PROVIDER=custom\nCUSTOM_BASE_URL=http://127.0.0.1:{port}/v1\n"
                             "CUSTOM_API_FORMAT=anthropic\nCUSTOM_API_KEY=fixture\nCUSTOM_MODEL=test-model\n")
        for images in ([], [{"part": 0, "data": "data:image/png;base64,iVBORw0KGgo="},
                            {"part": 2, "data": "data:image/jpeg;base64,/9j/"}]):
            self.assertEqual(server.answer_question({"stem": "Q?", "options": ["A", "B"], "images": images}), {"choice": 2})
            path, headers, payload = received[-1]
            self.assertEqual(path, "/v1/messages")
            self.assertEqual(headers["x-api-key"], "fixture")
            self.assertEqual(headers["anthropic-version"], "2023-06-01")
            self.assertNotIn("Authorization", headers)
            self.assertEqual(set(payload), {"model", "system", "messages", "max_tokens"})
            self.assertGreater(payload["max_tokens"], 0)
            message, = payload["messages"]
            self.assertEqual(message["role"], "user")
            if images:
                prompt, stem, picture, caption, option = message["content"]
                self.assertEqual((stem["text"], caption["text"]), ("题干配图", "选项 2 配图"))
                self.assertEqual(picture, {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}})
                self.assertEqual(option["source"], {"type": "base64", "media_type": "image/jpeg", "data": "/9j/"})
            else:
                self.assertEqual(json.loads(message["content"])["question"], "Q?")

    def test_only_completed_valid_claude_answers_are_used(self):
        cfg = api.config_from({"MODEL_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "fixture"})
        for reason, content in (("max_tokens", '{"choice":2}'), ("refusal", '{"choice":2}'),
                                ("end_turn", '{"choice":9}'), ("end_turn", 'no answer')):
            resp = {"type": "message", "stop_reason": reason, "content": [{"type": "text", "text": content}]}
            with patch.object(api, "request_model", return_value=resp), self.assertRaises(api.AnswerError):
                api.answer("Q", ["A", "B"], [], cfg)

    def test_form_is_local_one_use_and_preserves_configuration(self):
        self.path.write_text("# original\nOPENAI_API_KEY=old-fixture\nMODEL_PROVIDER=openai\n")
        setup = self.serve(configure.SetupServer(self.path, "anthropic", {}))
        url = setup.origin + setup.route
        with urlopen(url) as r:
            form = r.read().decode()
            self.assertIn('type="password"', form)
            self.assertNotIn("old-fixture", form)
            self.assertEqual(r.headers["Cache-Control"], "no-store")
        data = urlencode({"key": "new-fixture", "model": "chosen-model"}).encode()
        def post(origin, target=url):
            return urlopen(Request(target, data=data, headers={"Origin": origin}), timeout=3)
        for origin, target in (("https://example.org", url), (setup.origin, setup.origin + "/wrong")):
            with self.assertRaises(HTTPError) as cm:
                post(origin, target)
            self.assertEqual(cm.exception.code, 403)
        self.assertFalse(setup.saved)
        with post(setup.origin) as r:
            self.assertNotIn(b"new-fixture", r.read())
        self.assertTrue(setup.saved)
        self.assertEqual((api.settings().key, api.settings().provider), ("new-fixture", "anthropic"))
        self.assertIn("OPENAI_API_KEY=old-fixture", self.path.read_text())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        with self.assertRaises(HTTPError):
            post(setup.origin)

    def test_invalid_setup_keeps_original(self):
        self.path.write_text("OPENAI_API_KEY=old-fixture\n")
        for updates in ({"MODEL_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": ""},
                        {"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "test\nOTHER=broken"},
                        {"MODEL_PROVIDER": "custom", "CUSTOM_BASE_URL": "https://example.org",
                         "CUSTOM_MODEL": "model", "CUSTOM_API_KEY": ""}):
            with self.assertRaises(api.AnswerError):
                configure.save_config(self.path, updates)
            self.assertEqual(self.path.read_text(), "OPENAI_API_KEY=old-fixture\n")
            self.assertEqual(list(self.path.parent.iterdir()), [self.path])
