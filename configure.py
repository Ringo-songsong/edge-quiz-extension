"""One-use, loopback-only configuration form for assisted installation."""
import argparse
import html
import os
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from model_api import AnswerError, PRESETS, ROOT, config_from, parse_env


def save_config(path, updates):
    """Update just the selected settings. Keep the original file on failure."""
    for name, value in updates.items():
        if (value and not value.isprintable()) or value != value.strip("\"'"):
            raise AnswerError(400, f"{name} 中含有无效字符。")
        if name in os.environ and os.environ[name] != value:
            raise AnswerError(400, f"系统环境变量 {name} 优先于文件，请先在启动配置工具的终端取消或调整它。")
    lock = path.with_name(path.name + ".setup-lock")
    try:
        lockfile = lock.open("x")
    except FileExistsError:
        raise AnswerError(409, "其他配置操作正在写入此文件，请稍后重试。") from None
    try:
        with lockfile:
            try:
                original = path.read_text(encoding="utf-8-sig")
            except FileNotFoundError:
                original = ""
            remaining = dict(updates)
            lines = []
            for line in original.splitlines():
                name, sep, _ = line.partition("=")
                name = name.strip()
                if sep and name in updates:
                    if name in remaining:
                        lines.append(f"{name}={remaining.pop(name)}")
                else:
                    lines.append(line)
            lines.extend(f"{name}={value}" for name, value in remaining.items())
            effective = parse_env(lines)
            effective.update(os.environ)
            config_from(effective)
            pending = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=str(path.parent),
                                                 prefix=".env.setup-", delete=False) as f:
                    pending = Path(f.name)
                    f.write("\n".join(lines) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(pending, path)
            finally:
                if pending is not None and pending.exists():
                    pending.unlink()
    finally:
        lock.unlink()


def form(provider, defaults):
    prefix, endpoint, default_model = PRESETS[provider]
    model = html.escape(defaults.get("model") or default_model, quote=True)
    fields = ""
    if provider == "custom":
        base = html.escape(defaults.get("base_url", ""), quote=True)
        selected = " selected" if defaults.get("api_format") == "anthropic" else ""
        fields = f'''<label>接口格式<select name="api_format"><option value="chat">Chat Completions</option>
          <option value="anthropic"{selected}>Claude Messages</option></select></label>
          <label>服务商基础地址<input name="base_url" type="url" value="{base}" required></label>'''
    else:
        fields = f"<p>模型请求将发往 <code>{endpoint}</code>。</p>"
    required = "" if provider == "custom" else " required"
    note = "（本机免认证服务可留空）" if provider == "custom" else ""
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>作答本页 · 配置模型</title>
<style>html{{color-scheme:light dark}}body{{max-width:32rem;margin:8vh auto;padding:1rem;
font:1rem/1.6 Inter,"PingFang SC",sans-serif}}label{{display:block;margin:1rem 0}}
input,select,button{{display:block;font:inherit;padding:.5rem;box-sizing:border-box;width:100%}}
code{{overflow-wrap:anywhere}}button{{margin-top:1.5rem;cursor:pointer}}</style>
<main><h1>配置 {html.escape(provider)} 模型</h1><form method="post" autocomplete="off">
{fields}<label>模型 ID<input name="model" required value="{model}"></label>
<label>API Key{note}<input name="key" type="password" autocomplete="new-password"{required}></label>
<p>密钥将保存在本机配置文件。保存时只检查配置；首次使用模型时才会调用 API。</p>
<button>保存本机配置</button></form></main></html>'''


class SetupServer(HTTPServer):
    def __init__(self, path, provider, defaults):
        super().__init__(("127.0.0.1", 0), SetupHandler)
        self.path = path
        self.provider = provider
        self.defaults = defaults
        self.route = "/" + secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.saved = False


class SetupHandler(BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *args):
        pass  # Neither the one-use URL nor submitted fields belong in logs.

    def reply(self, status, message, content_type="text/plain"):
        data = message.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # Preserve the Origin on native form POSTs without disclosing the URL token.
        self.send_header("Referrer-Policy", "strict-origin")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        return (not self.server.saved and self.path == self.server.route
                and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}")

    def do_GET(self):
        if not self.allowed():
            return self.reply(404, "此配置链接不可用。")
        self.reply(200, form(self.server.provider, self.server.defaults), "text/html")

    def do_POST(self):
        if not self.allowed() or self.headers.get("Origin") != self.server.origin:
            return self.reply(403, "请使用本次安装生成的本机配置页。")
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self.reply(415, "请使用页面上的保存按钮。")
        size = self.headers.get("Content-Length", "")
        if not size.isascii() or not size.isdecimal() or len(size) > 5 or not 0 < int(size) <= 16384:
            return self.reply(400, "配置表单为空或过长。")
        provider = self.server.provider
        prefix = PRESETS[provider][0]
        try:
            fields = parse_qs(self.rfile.read(int(size)).decode(), keep_blank_values=True, strict_parsing=True)
            if any(len(v) != 1 for v in fields.values()):
                raise ValueError()
            updates = {"MODEL_PROVIDER": provider, prefix + "_MODEL": fields["model"][0].strip(),
                       prefix + "_API_KEY": fields["key"][0].strip()}
            if provider == "custom":
                updates.update(CUSTOM_BASE_URL=fields["base_url"][0].strip(), CUSTOM_API_FORMAT=fields["api_format"][0])
            save_config(self.server.path, updates)
        except AnswerError as error:
            return self.reply(error.status, str(error) + " 返回上一页后可以重试。")
        except (KeyError, ValueError, UnicodeError):
            return self.reply(400, "请检查字段和配置文件的 UTF-8 编码。")
        except OSError:
            return self.reply(503, "无法写入配置文件，请检查目录和当前账户的读写权限。")
        self.server.saved = True
        self.reply(200, "配置已保存。可以关闭此页，返回安装助手继续。")


def main():
    parser = argparse.ArgumentParser(description="打开一次性本机页面，填写并保存模型配置")
    parser.add_argument("--provider", required=True, choices=tuple(PRESETS) + ("claude",))
    parser.add_argument("--model", help="预填模型 ID")
    parser.add_argument("--base-url", default="", help="预填自定义服务商地址")
    parser.add_argument("--api-format", choices=("chat", "anthropic"), default="chat")
    parser.add_argument("--no-browser", action="store_true", help="仅显示本机链接")
    args = parser.parse_args()
    location = os.environ.get("QUIZ_ENV_FILE")
    if location == "-":
        parser.exit(1, "当前配置为纯环境变量模式，不写配置文件。\n")
    path = Path(location).expanduser() if location else ROOT / ".env"
    provider = "anthropic" if args.provider == "claude" else args.provider
    with SetupServer(path, provider, vars(args)) as httpd:
        url = httpd.origin + httpd.route
        print(f"请在本机浏览器填写并保存，链接 10 分钟有效：\n{url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        httpd.timeout = 1
        deadline = time.monotonic() + 600
        while not httpd.saved and time.monotonic() < deadline:
            httpd.handle_request()
        if not httpd.saved:
            parser.exit(1, "链接已过期，可重新运行配置命令。\n")
    print("本机配置已保存并通过格式检查。")


if __name__ == "__main__":
    main()
