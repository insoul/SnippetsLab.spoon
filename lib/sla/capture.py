"""텍스트 하나를 제목·언어를 붙여 SnippetsLab 에 새 스니펫으로 저장한다.

제목과 언어는 LM Studio 에 한 번에 묻고, 저장은 SnippetsLab 2.7 의 `lab create` 로 한다.
`lab` 은 새 스니펫만 만들 수 있고 기존 것은 못 고치므로(매뉴얼), 제목은 만들 때 붙여야 한다 —
그래야 autotitle 의 "앱 닫고 파일 고치기" 경로를 타지 않는다.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

from . import titler

DEFAULT_LAB = "/Applications/SnippetsLab.app/Contents/Helpers/lab"

# 태그 관련 기본값. config.json 의 같은 키로 덮어쓴다.
#   max_tags:         한 스니펫에 붙이는 최대 태그 수. 0 이면 태그를 뽑지 않는다
#   tag_exclude:      config.json 안의 제외 목록
#   tag_exclude_file: 한 줄에 하나씩 적는 제외 목록 파일. `#` 로 시작하는 줄과 빈 줄은 무시.
#                     config.json 을 열지 않고 목록만 손보는 용도
TAG_DEFAULTS = {
    "max_tags": 3,
    "tag_exclude": [],
    "tag_exclude_file": os.path.expanduser("~/.config/snippetslab-autotitle/tag-exclude.txt"),
}

# LM 에 고르게 할 언어. 값은 SnippetsLab 이 받는 렉서 별칭(pygments 계열)이다.
# 여기 없는 답은 버리고 언어 없이 저장한다 — 앱 기본 언어가 붙는다.
LANGUAGES = {
    "text": "text", "plain": "text", "plaintext": "text",
    "markdown": "markdown", "md": "markdown",
    "bash": "bash", "sh": "bash", "shell": "bash", "zsh": "bash",
    "python": "python", "python3": "python", "py": "python",
    "ruby": "ruby", "rb": "ruby",
    "lua": "lua",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "json": "json", "yaml": "yaml", "yml": "yaml", "toml": "toml", "xml": "xml", "html": "html", "css": "css",
    "sql": "sql",
    "swift": "swift", "objective-c": "objective-c", "objc": "objective-c",
    "go": "go", "golang": "go", "rust": "rust", "java": "java", "kotlin": "kotlin",
    "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "csharp", "c#": "csharp",
    "dockerfile": "dockerfile", "makefile": "makefile", "nginx": "nginx", "ini": "ini",
    "diff": "diff", "graphql": "graphql", "protobuf": "protobuf", "applescript": "applescript",
}

SYSTEM_PROMPT = (
    "The user gives you a note or code snippet. Answer with one JSON object only, no prose: "
    '{"title": "...", "language": "...", "tags": [...]}. '
    "title: one line, at most 40 characters, in the same language as the note, no quotes, no trailing period. "
    "language: the snippet's language as one of these lowercase names, or null for prose/notes: "
    + ", ".join(sorted(set(LANGUAGES.values()))) + ". "
    "tags: at most 3 short keywords naming the tool, service, or topic the snippet is clearly about "
    "(e.g. docker, kubernetes, aws, git, regex). Be conservative: prefer an empty list to a guess, "
    "never tag the language itself, never generic words like code, snippet, command, example, note."
)


class CaptureError(Exception):
    pass


def _normalize_language(value):
    if not isinstance(value, str):
        return None
    return LANGUAGES.get(value.strip().lower())


def load_exclude(path):
    """제외 목록 파일을 읽는다. 없으면 빈 목록. 한 줄에 하나, `#` 주석과 빈 줄은 무시, 앞뒤 공백 제거."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def filter_tags(tags, exclude, language, max_tags):
    """LM 이 준 태그를 보수적으로 거른다: 공백 제거·소문자·중복 제거, 제외 목록(대소문자 무시),
    언어 이름과 그 렉서 이름(bash, BashLexer)은 뺀다 — 언어 필터가 이미 그 역할을 한다. 앞에서 max_tags 개."""
    if not max_tags or not isinstance(tags, list):
        return []
    banned = {str(e).strip().lower() for e in exclude or []}
    if language:
        banned.add(language.lower())
        banned.add(language.lower() + "lexer")
    out, seen = [], set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        t = tag.strip().lower()
        if not t or t in seen or t in banned:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_tags:
            break
    return out


def _first_json_object(text):
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    return None


def describe(text, config, opener=urllib.request.urlopen):
    """LM 에 제목·언어·태그를 한 번에 묻는다. (title, language|None, tags). 제목이 없으면 TitleError.
    태그는 filter_tags 로 거른다 — config 의 max_tags, tag_exclude, tag_exclude_file 이 기준이다."""
    body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text[: config["max_chars"]]},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
        "stream": False,
        "reasoning_effort": "none",   # qwen3.6 기본 thinking 은 max_tokens 를 다 써서 content 가 빈다
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
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        raise titler.TitleError("LM Studio 호출 실패: %s" % e)
    stripped = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    obj = _first_json_object(stripped)
    if isinstance(obj, dict):
        title = titler.clean_title(str(obj.get("title") or ""), config["max_title_len"])
        language = _normalize_language(obj.get("language"))
        raw_tags = obj.get("tags")
    else:
        title = titler.clean_title(stripped, config["max_title_len"])
        language, raw_tags = None, []
    if not title:
        raise titler.TitleError("빈 제목: %r" % raw[:80])
    exclude = list(config.get("tag_exclude") or []) + load_exclude(config.get("tag_exclude_file") or "")
    tags = filter_tags(raw_tags, exclude, language, config.get("max_tags", TAG_DEFAULTS["max_tags"]))
    return title, language, tags


def _run(argv, stdin_text):
    p = subprocess.run(argv, input=stdin_text, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _argv(lab, title, language, folder, tags):
    argv = [lab, "create", "--launch", "--title", title]
    if language:
        argv += ["--language", language]
    if folder:
        argv += ["--folder", folder]
    for tag in tags or []:
        argv += ["--tag", tag]
    return argv


def create(text, title, language, lab=DEFAULT_LAB, runner=_run, folder=None, tags=None):
    """`lab create` 로 저장하고 {uuid, title, language, folder, tags} 를 돌려준다. 없는 태그는 lab 이 만든다.
    앱이 꺼져 있으면 --launch 가 띄운다. lab 이 언어나 폴더를 거부하면(모르는 별칭, 없는 폴더) 그것만 빼고
    다시 시도한다 — 저장 자체가 안 되는 것보다 루트에 언어 없이 들어가는 편이 낫다. 결과의 None 이 그 표시다."""
    tags = list(tags or [])
    code, out, err = runner(_argv(lab, title, language, folder, tags), text)
    for _ in range(2):
        if code == 0:
            break
        msg = (err or "").lower()
        if language and "language" in msg:
            language = None
        elif folder and "folder" in msg:
            folder = None
        else:
            break
        code, out, err = runner(_argv(lab, title, language, folder, tags), text)
    if code != 0:
        raise CaptureError((err or out or "lab exit %d" % code).strip())
    try:
        result = json.loads((out or "").strip().splitlines()[-1])
        uuid = result["uuid"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise CaptureError("lab 의 응답을 읽지 못함: %r" % (out or "")[:120])
    return {"uuid": uuid, "title": result.get("title", title), "language": language, "folder": folder, "tags": tags}


def parse(argv):
    ap = argparse.ArgumentParser(prog="snippetslab-capture",
                                 description="표준 입력의 텍스트를 제목·언어를 붙여 SnippetsLab 에 저장한다")
    ap.add_argument("--lab", default=DEFAULT_LAB, help="lab 명령 경로")
    ap.add_argument("--folder", default=None, help="저장할 폴더(이름 또는 UUID). 없는 폴더면 루트에 저장한다")
    ap.add_argument("--config", default=None, help="LM Studio 설정 (기본: autotitle 과 같은 파일)")
    return ap.parse_args(argv)


def main(argv=None, stdin=None, stdout=None, opener=urllib.request.urlopen, runner=_run, config=None):
    """결과를 JSON 한 줄로 찍는다: {uuid, title, language} 또는 {error}. 실패는 1."""
    args = parse(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    text = stdin.read()
    if not text.strip():
        print(json.dumps({"error": "저장할 텍스트가 없다"}, ensure_ascii=False), file=stdout)
        return 1
    if config is None:
        from .cli import DEFAULT_CONFIG, load_config
        config, _ = load_config(args.config or DEFAULT_CONFIG)
    config = dict(TAG_DEFAULTS, **config)
    try:
        title, language, tags = describe(text, config, opener)
        result = create(text, title, language, args.lab, runner, folder=args.folder, tags=tags)
    except (titler.TitleError, CaptureError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=stdout)
        return 1
    print(json.dumps(result, ensure_ascii=False), file=stdout)
    return 0
