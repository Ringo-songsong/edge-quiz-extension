"""Loopback bridge for the Edge extension. Run with python3 server.py."""
import argparse
import base64
import binascii
import json
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from model_api import AnswerError, answer, settings

ROOT = Path(__file__).resolve().parent
PORT = 8766
MAX_BODY = 7 * 1024 * 1024


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


def answer_question(data):
    stem, options, images = validate_question(data)
    return answer(stem, options, images, settings())


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
            if error.status >= 500:
                print(str(error), flush=True)  # Controlled diagnostics; no prompts, keys or provider bodies.
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
    parser = argparse.ArgumentParser(description="单选题扩展的本机模型服务")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-config", action="store_true", help="仅检查本机配置")
    mode.add_argument("--test-api", action="store_true", help="向当前模型发送一道测试题")
    args = parser.parse_args()
    if args.check_config or args.test_api:
        try:
            config = settings()
            print(f"本机配置可用。服务商 {config.provider}，模型 {config.model}。", flush=True)
            if args.test_api:
                result = answer("1 + 1 等于几？", ["1", "2"], [], config)
                print(f"API 已返回有效选项 {result['choice']}（该测试题正确选项为 2）。")
        except AnswerError as error:
            parser.exit(1, f"{error}\n")
        parser.exit()
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
