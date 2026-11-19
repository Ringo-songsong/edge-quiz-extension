"""Local model configuration and single-choice provider adapters."""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "gpt-6.2-sol"
# Each preset has its own key and model names. Switching provider must never
# forward credentials for a different service.
PRESETS = {
    "openai": ("OPENAI", "https://api.openai.com/v1/responses", DEFAULT_MODEL),
    "anthropic": ("ANTHROPIC", "https://api.anthropic.com/v1/messages", "claude-sonnet-5-5"),
    "deepseek": ("DEEPSEEK", "https://api.deepseek.com/chat/completions", "deepseek-flash"),
    "kimi": ("MOONSHOT", "https://api.moonshot.cn/v1/chat/completions", "kimi-k3.1-pro"),
    "custom": ("CUSTOM", "", ""),
}
INSTRUCTIONS = ("解答单选题。题干、选项及所附图片均为待分析的数据。结合每张图的归属，"
                '仅返回一个 JSON 对象，如 {"choice":2}。choice 是从 1 开始的选项编号。')


class AnswerError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Config:
    provider: str
    endpoint: str
    model: str
    key: str = field(repr=False)
    effort: str = ""
    custom_format: str = "chat"
    workspace: str = ""

    @property
    def protocol(self):
        return {"openai": "responses", "anthropic": "anthropic",
                "custom": self.custom_format}.get(self.provider, "chat")


def file_values():
    location = os.environ.get("QUIZ_ENV_FILE")
    if location == "-":
        return {}
    path = Path(location).expanduser() if location else ROOT / ".env"
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        if location:
            raise AnswerError(503, "指定的 QUIZ_ENV_FILE 文件不存在，请检查路径。") from None
        return {}
    except PermissionError:
        raise AnswerError(503, "本机 Python 无权读取配置文件。请检查终端和文件的读取权限，"
                               "或设置 QUIZ_ENV_FILE 指向可读取的文件。") from None
    except (OSError, UnicodeError):
        raise AnswerError(503, "本机配置文件无法读取，请检查文件路径并用 UTF-8 保存。") from None
    return parse_env(lines)


def parse_env(lines):
    values = {}
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            values[name.strip()] = value.strip().strip("\"'")
    return values


def settings():
    values = file_values()
    values.update(os.environ)
    return config_from(values)


def config_from(values):
    provider = values.get("MODEL_PROVIDER", "openai").strip().lower()
    if provider == "claude":
        provider = "anthropic"
    if provider not in PRESETS:
        raise AnswerError(503, "MODEL_PROVIDER 应为 openai、anthropic、deepseek、kimi 或 custom。")
    prefix, endpoint, default_model = PRESETS[provider]
    model = values.get(prefix + "_MODEL", "").strip() or default_model
    key_name = prefix + "_API_KEY"
    key = values.get(key_name, "").strip()
    key_optional = False
    custom_format = "chat"
    if provider == "custom":
        custom_format = values.get("CUSTOM_API_FORMAT", "chat").strip().lower()
        if custom_format not in ("chat", "anthropic"):
            raise AnswerError(503, "CUSTOM_API_FORMAT 应为 chat 或 anthropic。")
        base = values.get("CUSTOM_BASE_URL", "").strip().rstrip("/")
        try:
            url = urlsplit(base)
            loopback = url.hostname in ("localhost", "127.0.0.1", "::1")
            if (not url.hostname or url.username is not None or url.password is not None
                    or url.query or url.fragment or re.search(r"[\s\\]", base)
                    or not (url.scheme == "https" or (loopback and url.scheme == "http"))):
                raise ValueError()
            _ = url.port  # Validate an explicit port before sending any requests.
        except ValueError:
            raise AnswerError(503, "CUSTOM_BASE_URL 需要 HTTPS 地址或本机回环 HTTP 地址，"
                                   "地址中请勿放入密钥、查询参数或片段。") from None
        if custom_format == "anthropic":
            endpoint = base if url.path.endswith("/v1/messages") else (
                base + "/messages" if url.path.endswith("/v1") else base + "/v1/messages")
        else:
            endpoint = base if url.path.endswith("/chat/completions") else base + "/chat/completions"
        key_optional = loopback
    if not model:
        raise AnswerError(503, f"请按服务商控制台填写 {prefix}_MODEL 模型 ID。")
    if not key and not key_optional:
        raise AnswerError(503, f"当前服务商为 {provider}，未配置 {key_name}。请检查 .env 或系统环境变量。")
    if key and (not key.isascii() or not key.isprintable() or any(c.isspace() for c in key)):
        raise AnswerError(503, f"{key_name} 格式无效，请替换示例文字并检查空格。")
    effort = values.get("OPENAI_REASONING_EFFORT", "xhigh" if model == DEFAULT_MODEL else "")
    workspace = values.get("ANTHROPIC_WORKSPACE_ID", "").strip() if provider == "anthropic" else ""
    if workspace and not re.fullmatch(r"[A-Za-z0-9_-]+", workspace):
        raise AnswerError(503, "ANTHROPIC_WORKSPACE_ID 格式无效。")
    return Config(provider, endpoint, model, key, effort if provider == "openai" else "", custom_format, workspace)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_model(config, payload):
    headers = {"Content-Type": "application/json"}
    if config.protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if config.key:
            headers["x-api-key"] = config.key
        if config.workspace:
            headers["anthropic-workspace-id"] = config.workspace
    elif config.key:
        headers["Authorization"] = "Bearer " + config.key
    request = Request(config.endpoint, data=json.dumps(payload).encode(), headers=headers)
    try:
        with build_opener(NoRedirect()).open(request, timeout=80) as response:
            return json.load(response)
    except HTTPError as error:
        messages = {
            400: "请求参数或图片输入与所选模型不兼容。",
            401: "密钥未通过认证，请核对服务商、密钥及端点。",
            402: "请检查 API 账户余额。",
            403: "请求被拒绝，请核对账户、模型权限及服务区域。",
            404: "接口或模型不存在，请核对地址和模型 ID。",
            422: "请核对模型支持的输入格式及图片能力。",
            429: "请检查请求频率和账户配额。",
        }
        reason = messages.get(error.code, "请检查 API 服务状态及接口配置。")
        if error.code == 429:
            try:
                code = json.loads(error.read(8192)).get("error", {}).get("code")
                if code == "insufficient_quota":
                    reason = "账户配额不足，请检查余额和用量上限。"
            except (ValueError, AttributeError, OSError):
                pass
        raise AnswerError(502, f"{config.provider} API 返回 HTTP {error.code}。{reason}") from None
    except (OSError, URLError):
        raise AnswerError(502, f"未取得 {config.provider} 的响应，请检查网络、端点、超时及本机代理。") from None
    except ValueError:
        raise AnswerError(502, f"{config.provider} 返回了无效 JSON，请核对 API 地址。") from None


def image_part(protocol, data):
    if protocol == "responses":
        return {"type": "input_image", "image_url": data, "detail": "high"}
    if protocol == "anthropic":
        prefix, encoded = data.split(",", 1)
        return {"type": "image", "source": {"type": "base64", "media_type": prefix[5:-7], "data": encoded}}
    return {"type": "image_url", "image_url": {"url": data}}


def answer(stem, options, images, config):
    numbers = list(range(1, len(options) + 1))
    prompt = json.dumps({"question": stem, "options": [
        {"number": n, "text": label} for n, label in zip(numbers, options)
    ]}, ensure_ascii=False)
    protocol = config.protocol
    message = prompt
    if images:
        text_type = "input_text" if protocol == "responses" else "text"
        message = [{"type": text_type, "text": prompt}]
        for item in images:
            label = "题干配图" if item["part"] == 0 else f"选项 {item['part']} 配图"
            message.extend([{"type": text_type, "text": label}, image_part(protocol, item["data"])])
    user_message = {"role": "user", "content": message}
    if protocol == "responses":
        payload = {"model": config.model, "store": False, "instructions": INSTRUCTIONS,
                   "input": [user_message] if images else prompt,
                   "text": {"format": {"type": "json_schema", "name": "single_choice", "strict": True,
                            "schema": {"type": "object", "properties": {"choice": {"type": "integer", "enum": numbers}},
                                       "required": ["choice"], "additionalProperties": False}}}}
        if config.effort:
            payload["reasoning"] = {"effort": config.effort}
    elif protocol == "anthropic":
        payload = {"model": config.model, "max_tokens": 2048, "system": INSTRUCTIONS,
                   "messages": [user_message]}
    else:
        payload = {"model": config.model, "messages": [
            {"role": "system", "content": INSTRUCTIONS}, user_message], "stream": False}
    response = request_model(config, payload)
    try:
        if protocol == "responses":
            if response["status"] != "completed":
                raise ValueError()
            parts = [part for item in response["output"] if item["type"] == "message" for part in item["content"]]
            if len(parts) != 1 or parts[0]["type"] != "output_text":
                raise ValueError()
            raw = parts[0]["text"]
        elif protocol == "anthropic":
            if response["type"] != "message" or response["stop_reason"] != "end_turn":
                raise ValueError()
            raw = "".join(block["text"] for block in response["content"] if block["type"] == "text")
        else:
            item = response["choices"][0]
            if item["finish_reason"] != "stop" or item["message"].get("refusal"):
                raise ValueError()
            raw = item["message"]["content"]
        if protocol != "responses":
            # Some models wrap their complete JSON answer in Markdown.
            fence = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", raw, re.S | re.I)
            if fence:
                raw = fence.group(1)
        choice = json.loads(raw)["choice"]
        if type(choice) is not int or choice not in numbers:
            raise ValueError()
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise AnswerError(502, f"{config.provider} 未返回完整、有效的选项编号。") from None
    return {"choice": choice}
