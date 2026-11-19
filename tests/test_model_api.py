import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_api as api
import server


def reply(content='{"choice":2}', reason="stop"):
    return {"choices": [{"finish_reason": reason, "message": {
        "content": content, "reasoning_content": "ignore this text"}}]}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for p in (patch.object(api, "ROOT", self.root), patch.dict(os.environ, {}, clear=True)):
            p.start()
            self.addCleanup(p.stop)

    def test_legacy_and_environment_precedence(self):
        (self.root / ".env").write_text("OPENAI_API_KEY=legacy\nOPENAI_MODEL=from-file\n")
        with patch.dict(os.environ, OPENAI_MODEL="from-shell"):
            self.assertEqual(api.settings().model, "from-shell")
        cfg = api.settings()
        self.assertEqual((cfg.provider, cfg.key, cfg.model), ("openai", "legacy", "from-file"))

    def test_permission_is_local_and_env_only_bypasses_file(self):
        with patch.object(Path, "read_text", side_effect=PermissionError()), patch.object(api, "request_model") as req:
            with self.assertRaisesRegex(api.AnswerError, "Python"):
                server.answer_question({"stem": "Q", "options": ["a", "b"]})
            req.assert_not_called()
            with patch.dict(os.environ, QUIZ_ENV_FILE="-", OPENAI_API_KEY="from-shell"):
                self.assertEqual(api.settings().key, "from-shell")

    def test_alternate_file_and_missing_file(self):
        path = self.root / "alt.env"
        with patch.dict(os.environ, QUIZ_ENV_FILE=str(path)):
            with self.assertRaisesRegex(api.AnswerError, "QUIZ_ENV_FILE"):
                api.settings()
            path.write_text('MODEL_PROVIDER=kimi\nMOONSHOT_API_KEY="kimi-key"\n', encoding="utf-8-sig")
            self.assertEqual(api.settings().key, "kimi-key")

    def test_no_keys_cross_provider_boundaries(self):
        for provider, name in (("deepseek", "DEEPSEEK_API_KEY"), ("kimi", "MOONSHOT_API_KEY"),
                               ("custom", "CUSTOM_API_KEY")):
            with self.subTest(provider=provider), patch.dict(os.environ, MODEL_PROVIDER=provider,
                    OPENAI_API_KEY="openai-only", CUSTOM_BASE_URL="https://example.org/v1", CUSTOM_MODEL="custom"):
                with self.assertRaisesRegex(api.AnswerError, name):
                    api.settings()

    def test_chat_presets_and_images(self):
        image = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        for provider, endpoint, model in [
                ("deepseek", "https://api.deepseek.com/chat/completions", "deepseek-flash"),
                ("kimi", "https://api.moonshot.cn/v1/chat/completions", "kimi-k3.1-pro")]:
            with self.subTest(provider=provider), patch.dict(os.environ, MODEL_PROVIDER=provider,
                    DEEPSEEK_API_KEY="first", MOONSHOT_API_KEY="second", OPENAI_REASONING_EFFORT="xhigh",
                    OPENAI_MODEL="unrelated"), patch.object(api, "request_model", return_value=reply()) as req:
                result = server.answer_question({"stem": "Question?", "options": ["one", ""],
                                                  "images": [{"part": 0, "data": image}, {"part": 2, "data": image}]})
                self.assertEqual(result, {"choice": 2})
                cfg, payload = req.call_args[0]
                self.assertEqual((cfg.endpoint, cfg.model), (endpoint, model))
                self.assertEqual(set(payload), {"model", "messages", "stream"})
                self.assertEqual(payload["messages"][0]["role"], "system")
                parts = payload["messages"][1]["content"]
                self.assertEqual(json.loads(parts[0]["text"])["options"][1], {"number": 2, "text": ""})
                self.assertEqual([parts[1]["text"], parts[3]["text"]], ["题干配图", "选项 2 配图"])
                self.assertEqual(parts[2], {"type": "image_url", "image_url": {"url": image}})
                self.assertEqual(parts[2], parts[4])

    def test_custom_endpoint(self):
        with patch.dict(os.environ, MODEL_PROVIDER="custom", CUSTOM_MODEL="test"):
            for url in ("http://example.org", "https://u:p@example.org", "https://example.org/?key=abc",
                        "https://example.org:invalid", "file:///etc/test", ""):
                with self.subTest(url=url), patch.dict(os.environ, CUSTOM_BASE_URL=url):
                    with self.assertRaisesRegex(api.AnswerError, "CUSTOM_BASE_URL"):
                        api.settings()
            for url in ("http://localhost:1234/v1/", "http://localhost:1234/v1/chat/completions"):
                with patch.dict(os.environ, CUSTOM_BASE_URL=url):
                    self.assertEqual(api.settings().endpoint, "http://localhost:1234/v1/chat/completions")

    def test_answer_validation(self):
        cfg = api.Config("custom", "http://localhost", "model", "")
        for response in (reply('{"choice":3}'), reply('{"choice":true}'), reply(reason="length"),
                         {"choices": []}, reply("some prose"), reply(None), {}):
            with self.subTest(response=response), patch.object(api, "request_model", return_value=response):
                with self.assertRaises(api.AnswerError):
                    api.answer("Q", ["a", "b"], [], cfg)
        with patch.object(api, "request_model", return_value=reply('```json\n{"choice":2}\n```')):
            self.assertEqual(api.answer("Q", ["a", "b"], [], cfg), {"choice": 2})

    def test_custom_http_and_upstream_diagnostics(self):
        requests = []
        status = 200

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers.get("Authorization"),
                                 json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(status)
                self.end_headers()
                data = reply() if status == 200 else {"error": {"code": "insufficient_quota", "message": "secret-data"}}
                self.wfile.write(json.dumps(data).encode())

            def log_message(self, *args):
                pass

        def start(handler):
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            return f"http://127.0.0.1:{httpd.server_port}"

        upstream, bridge = start(Endpoint), start(server.Handler)
        with patch.dict(os.environ, MODEL_PROVIDER="custom", CUSTOM_BASE_URL=upstream + "/v1", CUSTOM_MODEL="local"):
            data = {"stem": "Q?", "options": ["a", "b"]}
            req = Request(bridge + "/api/answer", data=json.dumps(data).encode(),
                          headers={"Content-Type": "application/json", "X-Edge-Quiz": "1"})
            with urlopen(req, timeout=4) as resp:
                self.assertEqual(json.load(resp), {"choice": 2})
            self.assertEqual(requests[-1][:2], ("/v1/chat/completions", None))
            self.assertEqual(requests[-1][2]["model"], "local")
            with patch.dict(os.environ, CUSTOM_API_KEY="local-key"):
                for status in (401, 403, 404, 429):
                    with self.assertRaisesRegex(api.AnswerError, f"custom API 返回 HTTP {status}") as error:
                        server.answer_question(data)
                    self.assertEqual(requests[-1][1], "Bearer local-key")
                    self.assertNotIn("secret-data", str(error.exception))
                    self.assertNotIn("local-key", str(error.exception))
