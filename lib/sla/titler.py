"""LM Studio(OpenAI 호환 API)로 제목 한 줄을 받는다."""
import http.client
import json
import re
import urllib.request

DEFAULTS = {
    "base_url": "http://localhost:1234/v1",
    "model": "qwen/qwen3.6-35b-a3b",
    "timeout": 60,
    "max_chars": 4000,
    "max_title_len": 40,
}

SYSTEM_PROMPT = (
    "You write a title for the note the user gives you. "
    "Answer with the title only: one line, at most 40 characters, "
    "in the same language as the note, no quotes, no trailing period, no explanation."
)

_QUOTES = "\"'“”‘’`「」『』«»"


class TitleError(Exception):
    pass


def clean_title(raw, max_len=40):
    text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
    if "<think>" in text:
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    line = lines[0].strip(_QUOTES + " ").rstrip(".。").strip()
    if len(line) > max_len:
        line = line[:max_len].rstrip()
    return line


def generate_title(text, config, opener=urllib.request.urlopen):
    body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[: config["max_chars"]]},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
        "stream": False,
        # qwen3.6 기본 thinking 은 max_tokens 를 다 써서 content 가 빈다
        "reasoning_effort": "none",
    }
    req = urllib.request.Request(
        config["base_url"] + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(req, timeout=config["timeout"]) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"].get("content") or ""
    except (OSError, ValueError, KeyError, IndexError, TypeError, http.client.HTTPException) as e:
        raise TitleError("LM Studio 호출 실패: %s" % e)
    title = clean_title(raw, config["max_title_len"])
    if not title:
        raise TitleError("빈 제목: %r" % raw[:80])
    return title
