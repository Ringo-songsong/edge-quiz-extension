"""Local HTTP test server with a simulated OpenAI transport and no credentials."""
import base64
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import model_api
import server


def simulate_response(config, payload):
    assert config.key == "fixture" and payload["store"] is False
    assert payload["model"] == "gpt-6.2-sol" and payload["reasoning"] == {"effort": "xhigh"}
    frames = []
    if isinstance(payload["input"], list):
        [message] = payload["input"]
        assert message["role"] == "user"
        first, *parts = message["content"]
        assert first["type"] == "input_text" and len(parts) % 2 == 0
        question = json.loads(first["text"])
        for caption, picture in zip(parts[::2], parts[1::2]):
            assert caption["type"] == "input_text" and picture["type"] == "input_image"
            prefix, data = picture["image_url"].split(",", 1)
            assert prefix == "data:image/png;base64" and picture["detail"] == "high"
            png = base64.b64decode(data, validate=True)
            assert png.startswith(b"\x89PNG\r\n\x1a\n")
            frames.append((caption["text"], struct.unpack(">II", png[16:24])))
    else:
        question = json.loads(payload["input"])
    options = question["options"]
    numbers = list(range(1, len(options) + 1))
    assert [opt["number"] for opt in options] == numbers
    assert payload["text"]["format"]["schema"]["properties"]["choice"]["enum"] == numbers
    if question["question"] == "图中有几个蓝色圆形？":
        assert frames == [("题干配图", (260, 80))]
        number = 2
    elif question["question"] == "下列哪张图中的箭头朝左？":
        assert all(opt["text"] == "" for opt in options)
        assert frames == [(f"选项 {i} 配图", (80, 80)) for i in numbers]
        number = 3
    elif "无效编号" in question["question"]:
        number = len(numbers) + 1
    else:
        answers = {
            "古人说的「望」通常指哪种月相？": "满月",
            "哪颗行星离太阳最近？": "水星",
            "哪颗行星最大？": "木星",
            "下列哪种颜色的可见光波长最长？": "红光",
            "单选题 · 一刻钟是多少分钟？": "15 分钟",
        }
        number = next(opt["number"] for opt in options if opt["text"] == answers[question["question"]])
    time.sleep(.3)
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": json.dumps({"choice": number})}
    ]}]}


if __name__ == "__main__":
    server.settings = lambda: model_api.Config("openai", "", "gpt-6.2-sol", "fixture", "xhigh")
    model_api.request_model = simulate_response
    with server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler) as httpd:
        print(httpd.server_port, flush=True)
        httpd.serve_forever()
