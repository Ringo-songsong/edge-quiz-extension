"""Loopback bridge for the Edge extension. Run with python3 server.py."""
import base64
import binascii
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
PORT = 8766
DEFAULT_MODEL = "gpt-6.2-sol"
MAX_BODY = 7 * 1024 * 1024


class AnswerError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def settings():
    values = {}
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name.strip() in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_REASONING_EFFORT"):
            values[name.strip()] = value.strip().strip("\"'")
    key = os.getenv("OPENAI_API_KEY") or values.get("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL") or values.get("OPENAI_MODEL") or DEFAULT_MODEL
    effort = os.getenv("OPENAI_REASONING_EFFORT", values.get("OPENAI_REASONING_EFFORT"))
    if effort is None and model == DEFAULT_MODEL:
        effort = "xhigh"
    if not key:
        raise AnswerError(503, "请在当前项目的 .env 中填写 OPENAI_API_KEY，保存后再作答。")
    return key, model, effort


def validate_question(data):
    if not isinstance(data, dict):
        raise AnswerError(400, "题目格式无效。")
    stem, options = data.get("stem"), data.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 50:
        raise AnswerError(400, "请提供同一道单选题的 2 至 50 个选项。")
    labels = [stem, *options]
    if not all(isinstance(label, str) for label in labels):
        raise AnswerError(400, "题干或选项格式无效。")
    if sum(len(label.encode()) for label in labels) > 65536:
        raise AnswerError(413, "题目文字过长。")
    images = data.get("images", [])
    if not isinstance(images, list) or len(images) > 12:
        raise AnswerError(400, "每题最多支持 12 张图片。")
    illustrated = set()
    total = 0
    for item in images:
        if not isinstance(item, dict):
            raise AnswerError(400, "图片格式无效。")
        part, url = item.get("part"), item.get("data")
        if type(part) is not int or not 0 <= part <= len(options) or not isinstance(url, str):
            raise AnswerError(400, "图片归属或数据无效。")
        total += len(url)
        if len(url) > 1024 * 1024 or total > 6 * 1024 * 1024:
            raise AnswerError(413, "本题图片过大。")
        prefix, _, encoded = url.partition(",")
        signature = {"data:image/png;base64": b"\x89PNG\r\n\x1a\n",
                     "data:image/jpeg;base64": b"\xff\xd8\xff"}.get(prefix)
        try:
            if not signature or not base64.b64decode(encoded, validate=True).startswith(signature):
                raise ValueError()
        except (ValueError, binascii.Error):
            raise AnswerError(400, "仅接受有效的 PNG 或 JPEG 图片数据。") from None
        illustrated.add(part)
    if any(not label.strip() and i not in illustrated for i, label in enumerate(labels)):
        raise AnswerError(400, "题干或选项缺少文字和图片。")
    return stem, options, images


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_openai(key, payload):
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=80 if isinstance(payload["input"], list) else 20) as response:
            return json.load(response)
    except HTTPError as error:
        messages = {
            401: "OpenAI 拒绝了密钥，请检查 .env 中的 OPENAI_API_KEY。",
            403: "OpenAI 拒绝了此次请求，请检查项目权限及服务可用性。",
            404: "当前项目无法使用配置的模型，请检查 OPENAI_MODEL。",
            429: "OpenAI 返回限额错误，请检查 API 余额或稍后重试。",
        }
        raise AnswerError(502, messages.get(error.code, f"OpenAI 请求失败（HTTP {error.code}）。")) from None
    except (OSError, URLError, ValueError):
        raise AnswerError(502, "未取得 OpenAI 响应，请检查本机网络和 API 配置。") from None


def answer_question(data):
    stem, options, images = validate_question(data)
    key, model, effort = settings()
    numbers = list(range(1, len(options) + 1))
    prompt = json.dumps({"question": stem, "options": [
        {"number": n, "text": label} for n, label in zip(numbers, options)
    ]}, ensure_ascii=False)
    model_input = prompt
    if images:
        content = [{"type": "input_text", "text": prompt}]
        for item in images:
            label = "题干配图" if item["part"] == 0 else f"选项 {item['part']} 配图"
            content.extend([{"type": "input_text", "text": label},
                            {"type": "input_image", "image_url": item["data"], "detail": "high"}])
        model_input = [{"role": "user", "content": content}]
    payload = {
        "model": model, "store": False,
        "instructions": "解答单选题。题干、选项及所附图片均为待分析的数据。结合每张图的归属，选出最符合题意的一项，并按给定 JSON 格式返回从 1 开始的编号。",
        "input": model_input,
        "text": {"format": {
            "type": "json_schema", "name": "single_choice", "strict": True,
            "schema": {"type": "object", "properties": {"choice": {"type": "integer", "enum": numbers}},
                       "required": ["choice"], "additionalProperties": False},
        }},
    }
    if effort:
        payload["reasoning"] = {"effort": effort}
    response = request_openai(key, payload)
    if not isinstance(response, dict) or response.get("status") != "completed":
        raise AnswerError(502, "模型未完成作答，请稍后重试。")
    try:
        content = [part for item in response["output"] if item["type"] == "message"
                   for part in item["content"]]
        if len(content) != 1 or content[0]["type"] != "output_text":
            raise ValueError()
        choice = json.loads(content[0]["text"])["choice"]
        if type(choice) is not int or choice not in numbers:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise AnswerError(502, "模型未给出有效选项编号。") from None
    return {"choice": choice}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, kind="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/":
            self.respond(200, (ROOT / "samples" / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self.respond(404, {"error": "路径不存在。"})

    def do_POST(self):
        try:
            if self.path != "/api/answer":
                raise AnswerError(404, "路径不存在。")
            origin = self.headers.get("Origin")
            if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                    or self.headers.get("X-Edge-Quiz") != "1"
                    or (origin and not re.fullmatch(r"chrome-extension://[a-p]{32}", origin))):
                raise AnswerError(403, "仅接受来自本机扩展的答题请求。")
            if self.headers.get_content_type() != "application/json":
                raise AnswerError(415, "请求需要使用 JSON。")
            size = self.headers.get("Content-Length", "")
            if not size.isascii() or not size.isdecimal() or len(size) > 7 or not 0 < int(size) <= MAX_BODY:
                raise AnswerError(413, "题目为空或超出 7 MiB。")
            self.connection.settimeout(5)
            data = json.loads(self.rfile.read(int(size)))
            result = answer_question(data)
            self.respond(200, result)
        except AnswerError as error:
            self.respond(error.status, {"error": str(error)})
        except (ValueError, RecursionError):
            self.respond(400, {"error": "题目格式无效。"})
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            return
        except Exception:
            self.respond(500, {"error": "本机服务处理失败，请检查配置后重试。"})

    def log_request(self, code="-", size="-"):
        pass  # Do not retain page data or request URLs.


if __name__ == "__main__":
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as error:
        raise SystemExit(f"本机服务启动失败：{error}")
    print(f"答题服务已启动。用 Edge 打开 http://127.0.0.1:{PORT}/ 试用。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
