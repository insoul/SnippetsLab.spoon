# SnippetsLabAutoTitle 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SnippetsLab 에서 `untitled snippet` 으로 남은 스니펫에 LM Studio 로 만든 제목을 자동으로 넣는 Hammerspoon Spoon 을 만든다.

**Architecture:** Lua(`init.lua`)가 `Snippets/` 디렉토리를 `hs.pathwatcher` 로 보다가 30초 조용해지면 Python CLI 를 한 번 실행한다. Python 은 바뀐 스니펫 파일을 읽어 판정 표에 따라 제목을 생성하고 plist 파일에 직접 쓴 뒤 JSON 요약을 출력한다. 제목을 하나라도 썼으면 Lua 가 앱이 숨겨져 있고 5분간 조용할 때 SnippetsLab 을 백그라운드로 재실행해 새 제목이 보이게 한다.

**Tech Stack:** Hammerspoon (Lua), Python 3.9+ 표준 라이브러리만(`plistlib`, `urllib`, `json`, `unittest`), LM Studio OpenAI 호환 API.

**Spec:** `docs/design.md` (이 리포). 실행자는 스펙과 이 계획을 같이 읽는다.

## Global Constraints

- Python 은 `/usr/bin/python3`(3.9.6) 로 실행된다. Hammerspoon 의 PATH 가 `/usr/bin:/bin:/usr/sbin:/sbin` 이라 `#!/usr/bin/env python3` 가 그것을 고른다. 3.10+ 문법(`match`, `X | Y` 타입, `dataclass(slots=True)`)을 쓰지 않는다. 테스트도 `/usr/bin/python3` 로 돌린다.
- 외부 패키지 없음. 테스트는 `unittest` 다.
- 스니펫 파일은 NSKeyedArchiver binary plist 다. 제목 외의 객체는 절대 바꾸지 않는다.
- 기본 제목 문자열은 정확히 `untitled snippet` 이다.
- 상태 디렉토리는 `~/.local/state/snippetslab-autotitle/`, 설정은 `~/.config/snippetslab-autotitle/config.json`.
- 모델 기본값 `qwen/qwen3.6-35b-a3b`, 엔드포인트 `http://localhost:1234/v1/chat/completions`, 타임아웃 60초, 본문 4000자, 제목 40자.
- 리포는 `~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon/` 이며 이미 `git init` 돼 있고 `docs/design.md` 가 커밋돼 있다. 커밋 메시지는 한글. push 는 하지 않는다.
- 사용자의 실제 라이브러리에 쓰는 것은 Task 8 에서만 한다. 그 전 태스크는 전부 임시 디렉토리로 시험한다.

## 파일 구조

```
SnippetsLabAutoTitle.spoon/
├── init.lua                     # Spoon: 감시, 디바운스, Python 실행, 재실행
├── bin/snippetslab-autotitle    # 실행 진입점. lib/ 를 sys.path 에 넣고 cli.main() 호출
├── lib/sla/
│   ├── __init__.py
│   ├── snippet.py               # plist 읽기/쓰기, content_hash, 백업
│   ├── state.py                 # 상태 파일, 판정(decide)
│   ├── titler.py                # LM Studio 호출, 응답 다듬기, 설정 기본값
│   └── cli.py                   # 인자 처리, 처리 루프, 로그, JSON 요약
├── tests/
│   ├── helpers.py               # 합성 스니펫 plist 생성기
│   ├── test_snippet.py
│   ├── test_state.py
│   ├── test_titler.py
│   └── test_cli.py
├── docs/design.md
├── docs/plan.md
├── README.md
└── .gitignore
```

테스트 실행 명령(모든 태스크 공통):

```bash
cd ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon && PYTHONPATH=lib /usr/bin/python3 -m unittest discover -s tests -v
```

---

### Task 1: 스니펫 파일 읽기/쓰기 (`snippet.py`)

**Files:**
- Create: `.gitignore`, `lib/sla/__init__.py`, `lib/sla/snippet.py`, `tests/helpers.py`, `tests/test_snippet.py`

**Interfaces:**
- Produces:
  - `snippet.UNTITLED = "untitled snippet"`
  - `snippet.load(path) -> Snippet` — 필드 `path: Path, uuid: str, title: str, contents: list[str], content_hash: str`
  - `snippet.content_hash(contents: list[str]) -> str` (SHA-1 hex)
  - `snippet.write_title(path, new_title: str, backup_dir=None) -> None`
  - `tests.helpers.make_snippet(path, uuid, title, contents) -> None` (합성 plist 파일 생성)

- [ ] **Step 1: 리포 기본 파일**

`.gitignore`:
```
.DS_Store
__pycache__/
*.pyc
```

`lib/sla/__init__.py` 는 빈 파일.

- [ ] **Step 2: 합성 스니펫 생성기 `tests/helpers.py`**

실제 파일의 구조를 흉내낸다. `$objects[0]` 은 `$null`, root dict 의 값은 전부 `plistlib.UID` 로 다른 객체를 가리킨다.

```python
import plistlib
from pathlib import Path

K = "com.renfei.SnippetsLab.Key."


def make_snippet(path, uuid, title, contents, modified=797499964.641164):
    """SnippetsLab 형식의 NSKeyedArchiver plist 를 만든다. title=None 이면 $null."""
    objs = ["$null"]

    def add(o):
        objs.append(o)
        return plistlib.UID(len(objs) - 1)

    root = {}
    root_uid = add(root)
    root["$class"] = add({"$classname": "SLSnippet", "$classes": ["SLSnippet", "NSObject"]})
    root[K + "SnippetTitle"] = plistlib.UID(0) if title is None else add(title)
    root[K + "SnippetUUID"] = add(uuid)
    root[K + "SnippetDateModified"] = add({"NS.time": modified})
    parts = {"NS.objects": []}
    root[K + "SnippetParts"] = add(parts)
    for c in contents:
        part = {}
        part_uid = add(part)
        part[K + "SnippetPartContent"] = add(c)
        part[K + "SnippetPartLanguage"] = add("TextLexer")
        parts["NS.objects"].append(part_uid)
    pl = {
        "$version": 100000,
        "$archiver": "NSKeyedArchiver",
        "$top": {"root": root_uid},
        "$objects": objs,
    }
    Path(path).write_bytes(plistlib.dumps(pl, fmt=plistlib.FMT_BINARY))
```

- [ ] **Step 3: 실패하는 테스트 `tests/test_snippet.py`**

```python
import plistlib
import tempfile
import unittest
from pathlib import Path

from helpers import K, make_snippet
from sla import snippet


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "AAAA.data"

    def test_reads_title_uuid_and_contents(self):
        make_snippet(self.path, "AAAA", "hello", ["one", "two"])
        s = snippet.load(self.path)
        self.assertEqual(s.uuid, "AAAA")
        self.assertEqual(s.title, "hello")
        self.assertEqual(s.contents, ["one", "two"])
        self.assertEqual(s.content_hash, snippet.content_hash(["one", "two"]))

    def test_null_title_reads_as_empty_string(self):
        make_snippet(self.path, "AAAA", None, ["x"])
        self.assertEqual(snippet.load(self.path).title, "")

    def test_hash_depends_on_part_boundaries(self):
        self.assertNotEqual(snippet.content_hash(["ab", "c"]), snippet.content_hash(["a", "bc"]))


class WriteTitleTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "BBBB.data"
        make_snippet(self.path, "BBBB", "untitled snippet", ["body"])

    def _objects_without_title(self, path):
        pl = plistlib.loads(Path(path).read_bytes())
        root = pl["$objects"][pl["$top"]["root"].data]
        title_uid = root[K + "SnippetTitle"].data
        return [o for i, o in enumerate(pl["$objects"]) if i != title_uid], root[K + "SnippetDateModified"]

    def test_changes_only_the_title(self):
        before, _ = self._objects_without_title(self.path)
        snippet.write_title(self.path, "새 제목")
        s = snippet.load(self.path)
        self.assertEqual(s.title, "새 제목")
        self.assertEqual(s.contents, ["body"])
        # 제목 문자열은 새 객체로 덧붙이므로, 원래 있던 객체는 전부 그대로 남아 있어야 한다
        after, after_mod = self._objects_without_title(self.path)
        for o in before:
            self.assertIn(o, after)
        pl = plistlib.loads(self.path.read_bytes())
        self.assertEqual(pl["$objects"][after_mod.data], {"NS.time": 797499964.641164})

    def test_write_is_atomic_no_tmp_left(self):
        snippet.write_title(self.path, "t")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["BBBB.data"])

    def test_backup_keeps_three_newest(self):
        backup = self.dir / "backup"
        for i in range(5):
            snippet.write_title(self.path, "t%d" % i, backup_dir=backup)
        files = sorted(backup.glob("BBBB.*.data"))
        self.assertEqual(len(files), 3)
        # 가장 오래 남은 백업은 세 번째 쓰기 직전 상태(t1)여야 한다
        self.assertEqual(snippet.load(files[0]).title, "t1")

    def test_null_title_gets_new_string(self):
        make_snippet(self.path, "BBBB", None, ["body"])
        snippet.write_title(self.path, "made")
        self.assertEqual(snippet.load(self.path).title, "made")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 실패 확인**

Run: `cd ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon && PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_snippet -v`
Expected: `ModuleNotFoundError: No module named 'sla.snippet'` 또는 AttributeError.

주의: `helpers` 를 임포트하려면 `tests` 도 PYTHONPATH 에 있어야 한다. 앞으로 모든 테스트 명령은 `PYTHONPATH=lib:tests` 를 쓴다.

- [ ] **Step 5: 구현 `lib/sla/snippet.py`**

제목 문자열은 제자리에서 바꾸지 않고 새 객체를 덧붙여 root 의 UID 를 옮긴다. NSKeyedArchiver 는 같은 문자열을 하나의 객체로 공유하므로, 제자리 수정은 다른 곳의 같은 문자열까지 바꿀 수 있다.

```python
"""SnippetsLab 스니펫 파일(NSKeyedArchiver binary plist) 읽기와 제목 쓰기."""
import hashlib
import os
import plistlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

K = "com.renfei.SnippetsLab.Key."
UNTITLED = "untitled snippet"


@dataclass
class Snippet:
    path: Path
    uuid: str
    title: str
    contents: List[str] = field(default_factory=list)
    content_hash: str = ""


def content_hash(contents):
    return hashlib.sha1("\x00".join(contents).encode("utf-8")).hexdigest()


def _root(pl):
    return pl["$objects"][pl["$top"]["root"].data]


def _deref(pl, uid):
    if uid is None or uid.data == 0:
        return None
    return pl["$objects"][uid.data]


def load(path):
    path = Path(path)
    pl = plistlib.loads(path.read_bytes())
    root = _root(pl)
    title = _deref(pl, root.get(K + "SnippetTitle")) or ""
    uuid = _deref(pl, root.get(K + "SnippetUUID")) or path.stem
    parts = _deref(pl, root.get(K + "SnippetParts")) or {}
    contents = []
    for part_uid in parts.get("NS.objects", []):
        part = _deref(pl, part_uid) or {}
        contents.append(_deref(pl, part.get(K + "SnippetPartContent")) or "")
    return Snippet(path, uuid, title, contents, content_hash(contents))


def write_title(path, new_title, backup_dir=None):
    path = Path(path)
    raw = path.read_bytes()
    pl = plistlib.loads(raw)
    root = _root(pl)
    pl["$objects"].append(new_title)
    root[K + "SnippetTitle"] = plistlib.UID(len(pl["$objects"]) - 1)
    if backup_dir is not None:
        _backup(path, raw, Path(backup_dir))
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_bytes(plistlib.dumps(pl, fmt=plistlib.FMT_BINARY))
    os.replace(tmp, path)


def _backup(path, raw, backup_dir, keep=3):
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "%s.%013d.data" % (path.stem, int(time.time() * 1000))).write_bytes(raw)
    olds = sorted(backup_dir.glob(path.stem + ".*.data"))
    for p in olds[:-keep]:
        p.unlink()
```

- [ ] **Step 6: 통과 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_snippet -v`
Expected: 8 tests OK. `test_backup_keeps_three_newest` 가 같은 밀리초에 두 번 써서 실패하면 백업 파일명에 카운터를 더하지 말고 테스트에서 쓰기 사이에 `time.sleep(0.002)` 를 넣는다.

- [ ] **Step 7: 커밋**

```bash
git add .gitignore lib tests && git commit -m "snippet: plist 읽기와 제목 쓰기"
```

---

### Task 2: 상태 파일과 판정 (`state.py`)

**Files:**
- Create: `lib/sla/state.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: `snippet.UNTITLED`
- Produces:
  - `state.State(path)` — 속성 `last_run: float`, `snippets: dict[uuid -> {"auto_title", "content_hash"}]`, `locked: dict[uuid -> str]`, `force: list[uuid]`; 메서드 `State.load(path) -> State`, `save()`
  - `state.decide(st, uuid, title, content_hash, has_content) -> "generate" | "regenerate" | "lock" | "skip"`

- [ ] **Step 1: 실패하는 테스트 `tests/test_state.py`**

```python
import tempfile
import unittest
from pathlib import Path

from sla.state import State, decide


class StateFileTest(unittest.TestCase):
    def test_missing_file_is_empty_state(self):
        st = State.load(Path(tempfile.mkdtemp()) / "state.json")
        self.assertEqual(st.last_run, 0.0)
        self.assertEqual(st.snippets, {})
        self.assertEqual(st.locked, {})
        self.assertEqual(st.force, [])

    def test_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "sub" / "state.json"
        st = State.load(path)
        st.last_run = 12.5
        st.snippets["A"] = {"auto_title": "t", "content_hash": "h"}
        st.locked["B"] = "mine"
        st.force.append("C")
        st.save()
        again = State.load(path)
        self.assertEqual(again.last_run, 12.5)
        self.assertEqual(again.snippets, {"A": {"auto_title": "t", "content_hash": "h"}})
        self.assertEqual(again.locked, {"B": "mine"})
        self.assertEqual(again.force, ["C"])


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.st = State.load(Path(tempfile.mkdtemp()) / "state.json")
        self.st.snippets["A"] = {"auto_title": "auto", "content_hash": "h1"}

    def test_untitled_generates(self):
        self.assertEqual(decide(self.st, "X", "untitled snippet", "h", True), "generate")

    def test_same_auto_title_same_hash_skips(self):
        self.assertEqual(decide(self.st, "A", "auto", "h1", True), "skip")

    def test_same_auto_title_new_hash_regenerates(self):
        self.assertEqual(decide(self.st, "A", "auto", "h2", True), "regenerate")

    def test_changed_title_with_record_locks(self):
        self.assertEqual(decide(self.st, "A", "user wrote this", "h1", True), "lock")

    def test_user_title_without_record_skips(self):
        self.assertEqual(decide(self.st, "X", "user wrote this", "h", True), "skip")

    def test_empty_content_never_generates(self):
        self.assertEqual(decide(self.st, "X", "untitled snippet", "h", False), "skip")
        self.assertEqual(decide(self.st, "A", "auto", "h2", False), "skip")

    def test_force_generates_over_user_title(self):
        self.st.force.append("X")
        self.assertEqual(decide(self.st, "X", "user wrote this", "h", True), "generate")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_state -v`
Expected: `ModuleNotFoundError: No module named 'sla.state'`

- [ ] **Step 3: 구현 `lib/sla/state.py`**

```python
"""상태 파일(UUID -> 자동 제목 기록)과 판정 규칙."""
import json
import os
from pathlib import Path

from .snippet import UNTITLED


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.last_run = 0.0
        self.snippets = {}
        self.locked = {}
        self.force = []

    @classmethod
    def load(cls, path):
        st = cls(path)
        if st.path.exists():
            data = json.loads(st.path.read_text("utf-8"))
            st.last_run = float(data.get("last_run", 0.0))
            st.snippets = dict(data.get("snippets", {}))
            st.locked = dict(data.get("locked", {}))
            st.force = list(data.get("force", []))
        return st

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_run": self.last_run,
            "snippets": self.snippets,
            "locked": self.locked,
            "force": self.force,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, self.path)


def decide(st, uuid, title, content_hash, has_content):
    """design.md 2단계 판정 표. 실패는 항상 skip 쪽이다."""
    if uuid in st.force or title == UNTITLED:
        action = "generate"
    else:
        rec = st.snippets.get(uuid)
        if rec is None:
            return "skip"
        if title != rec.get("auto_title"):
            return "lock"
        action = "skip" if content_hash == rec.get("content_hash") else "regenerate"
    if action != "skip" and not has_content:
        return "skip"
    return action
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_state -v`
Expected: 9 tests OK.

- [ ] **Step 5: 커밋**

```bash
git add lib/sla/state.py tests/test_state.py && git commit -m "state: 상태 파일과 판정 규칙"
```

---

### Task 3: LM Studio 제목 생성 (`titler.py`)

**Files:**
- Create: `lib/sla/titler.py`, `tests/test_titler.py`

**Interfaces:**
- Produces:
  - `titler.DEFAULTS: dict` — `base_url, model, timeout, max_chars, max_title_len`
  - `titler.clean_title(raw: str, max_len=40) -> str`
  - `titler.generate_title(text: str, config: dict, opener=urllib.request.urlopen) -> str` — 실패 시 `titler.TitleError`

- [ ] **Step 1: 실패하는 테스트 `tests/test_titler.py`**

```python
import io
import json
import unittest

from sla import titler


class CleanTitleTest(unittest.TestCase):
    def test_strips_quotes_period_and_whitespace(self):
        self.assertEqual(titler.clean_title('  "제목입니다."  \n'), "제목입니다")

    def test_first_line_only(self):
        self.assertEqual(titler.clean_title("first\nsecond"), "first")

    def test_removes_think_block(self):
        self.assertEqual(titler.clean_title("<think>blah\nblah</think>\nReal title"), "Real title")

    def test_unclosed_think_is_empty(self):
        self.assertEqual(titler.clean_title("<think>still thinking"), "")

    def test_truncates_to_max_len(self):
        self.assertEqual(titler.clean_title("a" * 50, max_len=40), "a" * 40)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_opener_returning(content):
    calls = []

    def opener(req, timeout=None):
        calls.append((req, timeout))
        body = {"choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(body).encode("utf-8"))

    opener.calls = calls
    return opener


class GenerateTitleTest(unittest.TestCase):
    def test_sends_truncated_text_and_returns_clean_title(self):
        opener = fake_opener_returning(' "Git 키 롤오버 현황" ')
        cfg = dict(titler.DEFAULTS, max_chars=5)
        title = titler.generate_title("0123456789", cfg, opener=opener)
        self.assertEqual(title, "Git 키 롤오버 현황")
        req, timeout = opener.calls[0]
        self.assertEqual(timeout, cfg["timeout"])
        self.assertEqual(req.full_url, cfg["base_url"] + "/chat/completions")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], cfg["model"])
        self.assertEqual(body["messages"][1]["content"], "01234")

    def test_empty_title_raises(self):
        opener = fake_opener_returning("<think>hmm")
        with self.assertRaises(titler.TitleError):
            titler.generate_title("x", titler.DEFAULTS, opener=opener)

    def test_network_error_raises_title_error(self):
        def opener(req, timeout=None):
            raise OSError("connection refused")
        with self.assertRaises(titler.TitleError):
            titler.generate_title("x", titler.DEFAULTS, opener=opener)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_titler -v`
Expected: `ModuleNotFoundError: No module named 'sla.titler'`

- [ ] **Step 3: 구현 `lib/sla/titler.py`**

```python
"""LM Studio(OpenAI 호환 API)로 제목 한 줄을 받는다."""
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
        raw = data["choices"][0]["message"]["content"]
    except (OSError, ValueError, KeyError, IndexError) as e:
        raise TitleError("LM Studio 호출 실패: %s" % e)
    title = clean_title(raw, config["max_title_len"])
    if not title:
        raise TitleError("빈 제목: %r" % raw[:80])
    return title
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_titler -v`
Expected: 8 tests OK.

- [ ] **Step 5: 커밋**

```bash
git add lib/sla/titler.py tests/test_titler.py && git commit -m "titler: LM Studio 제목 생성과 응답 다듬기"
```

---

### Task 4: CLI 처리 루프 (`cli.py`, `bin/snippetslab-autotitle`)

**Files:**
- Create: `lib/sla/cli.py`, `bin/snippetslab-autotitle`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `snippet.load / write_title / UNTITLED`, `state.State / decide`, `titler.generate_title / DEFAULTS / TitleError`
- Produces:
  - `cli.main(argv=None, generate=None) -> int` — `generate(text) -> str` 를 주입하면 LM Studio 를 부르지 않는다
  - 인자: `--all`, `--dry-run`, `--status`, `--unlock UUID`, `--library DIR`, `--state-dir DIR`, `--config FILE`
  - stdout 마지막 줄: `{"generated": n, "written": n, "locked": n, "skipped": n, "errors": n}`
  - 로그 한 줄: `YYYY-MM-DD HH:MM:SS  <uuid 앞 8자>  <action>  <title>`

- [ ] **Step 1: 실패하는 테스트 `tests/test_cli.py`**

```python
import json
import os
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from helpers import make_snippet
from sla import cli, snippet
from sla.state import State


def old(path, seconds=60):
    t = time.time() - seconds
    os.utime(path, (t, t))


class CliTest(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.lib = base / "Snippets"
        self.lib.mkdir()
        self.state_dir = base / "state"
        self.calls = []

    def run_cli(self, *extra, generate=None):
        def gen(text):
            self.calls.append(text)
            return "생성된 제목"
        argv = ["--library", str(self.lib), "--state-dir", str(self.state_dir)] + list(extra)
        out = StringIO()
        with mock.patch("sys.stdout", out):
            code = cli.main(argv, generate=generate or gen)
        self.assertEqual(code, 0)
        return json.loads(out.getvalue().strip().splitlines()[-1])

    def test_untitled_snippet_gets_title_and_record(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello", "world"])
        old(p)
        summary = self.run_cli()
        self.assertEqual(summary["written"], 1)
        self.assertEqual(snippet.load(p).title, "생성된 제목")
        self.assertEqual(self.calls, ["hello\n\nworld"])
        st = State.load(self.state_dir / "state.json")
        self.assertEqual(st.snippets["A"]["auto_title"], "생성된 제목")
        self.assertTrue((self.state_dir / "backup").exists())
        self.assertIn("generate", (self.state_dir / "log").read_text("utf-8"))

    def test_second_run_skips_own_write(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        old(p)
        summary = self.run_cli("--all")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["skipped"], 1)

    def test_user_title_locks_and_never_changes(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        make_snippet(p, "A", "내가 쓴 제목", ["hello changed"])
        old(p)
        summary = self.run_cli("--all")
        self.assertEqual(summary["locked"], 1)
        self.assertEqual(snippet.load(p).title, "내가 쓴 제목")
        st = State.load(self.state_dir / "state.json")
        self.assertNotIn("A", st.snippets)
        self.assertEqual(st.locked["A"], "내가 쓴 제목")

    def test_recent_files_are_left_alone(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])   # mtime = now
        summary = self.run_cli()
        self.assertEqual(summary["written"], 0)
        self.assertEqual(snippet.load(p).title, "untitled snippet")

    def test_only_files_changed_since_last_run(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p, 600)
        st = State.load(self.state_dir / "state.json")
        st.last_run = time.time() - 300
        st.save()
        self.assertEqual(self.run_cli()["written"], 0)
        self.assertEqual(self.run_cli("--all")["written"], 1)

    def test_dry_run_writes_nothing(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        summary = self.run_cli("--dry-run")
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["written"], 0)
        self.assertEqual(snippet.load(p).title, "untitled snippet")
        self.assertFalse((self.state_dir / "state.json").exists())

    def test_generate_failure_is_counted_not_raised(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)

        def boom(text):
            raise cli.titler.TitleError("down")
        summary = self.run_cli(generate=boom)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(snippet.load(p).title, "untitled snippet")

    def test_unlock_then_regenerates_over_user_title(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "내가 쓴 제목", ["hello"])
        old(p)
        st = State.load(self.state_dir / "state.json")
        st.locked["A"] = "내가 쓴 제목"
        st.save()
        self.run_cli("--unlock", "A")
        summary = self.run_cli("--all")
        self.assertEqual(summary["written"], 1)
        st = State.load(self.state_dir / "state.json")
        self.assertEqual(st.force, [])
        self.assertNotIn("A", st.locked)

    def test_status_prints_locked(self):
        st = State.load(self.state_dir / "state.json")
        st.locked["A"] = "내가 쓴 제목"
        st.save()
        out = StringIO()
        with mock.patch("sys.stdout", out):
            cli.main(["--library", str(self.lib), "--state-dir", str(self.state_dir), "--status"])
        self.assertIn("내가 쓴 제목", out.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_cli -v`
Expected: `ModuleNotFoundError: No module named 'sla.cli'`

- [ ] **Step 3: 구현 `lib/sla/cli.py`**

```python
"""snippetslab-autotitle 명령행. 바뀐 스니펫을 판정·생성·기록하고 JSON 요약을 출력한다."""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import snippet, titler
from .state import State, decide

HOME = Path.home()
DEFAULT_LIBRARY = (
    HOME / "Library/Mobile Documents/iCloud~com~renfei~SnippetsLab"
    / "main.snippetslablibrary/Database/Snippets"
)
DEFAULT_STATE_DIR = HOME / ".local/state/snippetslab-autotitle"
DEFAULT_CONFIG = HOME / ".config/snippetslab-autotitle/config.json"
RECENT_SECONDS = 10       # 이보다 최근에 바뀐 파일은 아직 쓰는 중일 수 있다
LOG_ROTATE_BYTES = 1_000_000


class Log:
    def __init__(self, path):
        self.path = Path(path)

    def write(self, uuid, action, title=""):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > LOG_ROTATE_BYTES:
            os.replace(self.path, self.path.with_name(self.path.name + ".1"))
        line = "%s  %-8s  %-10s  %s\n" % (
            time.strftime("%Y-%m-%d %H:%M:%S"), uuid[:8], action, title.replace("\n", " "))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line)


def load_config(path):
    cfg = dict(titler.DEFAULTS)
    path = Path(path)
    if path.exists():
        cfg.update(json.loads(path.read_text("utf-8")))
    return cfg


def parse(argv):
    ap = argparse.ArgumentParser(prog="snippetslab-autotitle")
    ap.add_argument("--all", action="store_true", help="last_run 을 무시하고 모든 파일을 본다")
    ap.add_argument("--dry-run", action="store_true", help="판정과 생성만 하고 쓰지 않는다")
    ap.add_argument("--status", action="store_true", help="상태와 잠금 목록을 보여 준다")
    ap.add_argument("--unlock", metavar="UUID", help="잠금을 풀어 다음 실행에서 다시 생성한다")
    ap.add_argument("--library", default=str(DEFAULT_LIBRARY))
    ap.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    return ap.parse_args(argv)


def show_status(st):
    print("last_run: %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.last_run)) if st.last_run else "-"))
    print("auto-titled: %d" % len(st.snippets))
    print("locked: %d" % len(st.locked))
    for uuid, title in sorted(st.locked.items()):
        print("  %s  %s" % (uuid, title))
    if st.force:
        print("force: %s" % ", ".join(st.force))


def process(path, st, gen, log, backup_dir, dry_run, counts):
    s = snippet.load(path)
    has_content = any(c.strip() for c in s.contents)
    action = decide(st, s.uuid, s.title, s.content_hash, has_content)
    if action == "skip":
        counts["skipped"] += 1
        return
    if action == "lock":
        st.snippets.pop(s.uuid, None)
        st.locked[s.uuid] = s.title
        counts["locked"] += 1
        log.write(s.uuid, "lock", s.title)
        return
    title = gen("\n\n".join(s.contents))
    counts["generated"] += 1
    log.write(s.uuid, action + ("(dry)" if dry_run else ""), title)
    if dry_run:
        return
    snippet.write_title(path, title, backup_dir=backup_dir)
    st.snippets[s.uuid] = {"auto_title": title, "content_hash": s.content_hash}
    st.locked.pop(s.uuid, None)
    if s.uuid in st.force:
        st.force.remove(s.uuid)
    counts["written"] += 1


def main(argv=None, generate=None):
    args = parse(argv)
    state_dir = Path(args.state_dir)
    st = State.load(state_dir / "state.json")
    log = Log(state_dir / "log")

    if args.status:
        show_status(st)
        return 0
    if args.unlock:
        st.locked.pop(args.unlock, None)
        if args.unlock not in st.force:
            st.force.append(args.unlock)
        st.save()
        print("unlocked: %s" % args.unlock)
        return 0

    config = load_config(args.config)
    gen = generate or (lambda text: titler.generate_title(text, config))
    started = time.time()
    counts = {"generated": 0, "written": 0, "locked": 0, "skipped": 0, "errors": 0}

    for path in sorted(Path(args.library).glob("*.data")):
        mtime = path.stat().st_mtime
        if not args.all and mtime <= st.last_run:
            continue
        if started - mtime < RECENT_SECONDS:
            continue
        try:
            process(path, st, gen, log, state_dir / "backup", args.dry_run, counts)
        except Exception as e:            # 한 파일의 실패가 다른 파일을 막지 않는다
            counts["errors"] += 1
            log.write(path.stem, "error", "%s: %s" % (type(e).__name__, e))

    if not args.dry_run:
        # 최근 RECENT_SECONDS 안에 바뀌어 건너뛴 파일이 다음 실행에 잡히도록 그만큼 앞당긴다
        st.last_run = started - RECENT_SECONDS
        st.save()
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest tests.test_cli -v`
Expected: 9 tests OK.

- [ ] **Step 5: 실행 진입점 `bin/snippetslab-autotitle`**

```python
#!/usr/bin/env python3
"""snippetslab-autotitle 진입점. 자기 옆의 lib/ 를 경로에 넣고 cli.main 을 부른다."""
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from sla.cli import main  # noqa: E402

sys.exit(main())
```

```bash
chmod +x bin/snippetslab-autotitle
ln -sfn ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon/bin/snippetslab-autotitle ~/.local/bin/snippetslab-autotitle
snippetslab-autotitle --status
```
Expected: `last_run: -` / `auto-titled: 0` / `locked: 0`. 실제 라이브러리에는 아직 아무것도 쓰지 않는다(`--status` 는 읽기 전용).

- [ ] **Step 6: 전체 테스트**

Run: `PYTHONPATH=lib:tests /usr/bin/python3 -m unittest discover -s tests -v`
Expected: 34 tests OK.

- [ ] **Step 7: 커밋**

```bash
git add lib/sla/cli.py bin/snippetslab-autotitle tests/test_cli.py && git commit -m "cli: 처리 루프, 로그, 상태 명령, 실행 진입점"
```

---

### Task 5: LM Studio 실제 호출 확인 (dry-run, 임시 라이브러리)

**Files:** 없음 (검증만)

**Interfaces:**
- Consumes: `bin/snippetslab-autotitle --library --state-dir --dry-run --all`

- [ ] **Step 1: 합성 스니펫 세 개로 임시 라이브러리 생성**

```bash
cd ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon
T=$(mktemp -d) && mkdir -p $T/lib $T/state && PYTHONPATH=lib:tests /usr/bin/python3 - "$T/lib" <<'EOF'
import sys, os, time
from pathlib import Path
from helpers import make_snippet
lib = Path(sys.argv[1])
make_snippet(lib/"A.data", "A", "untitled snippet", ["ALTER TABLE users ADD INDEX idx_email (email);"])
make_snippet(lib/"B.data", "B", "untitled snippet", ["Hammerspoon 에서 hs.pathwatcher 로 디렉토리를 감시하고 30초 디바운스 후 스크립트를 실행하는 방법 정리"])
make_snippet(lib/"C.data", "C", "untitled snippet", ["def fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)"])
t = time.time() - 60
for p in lib.glob("*.data"): os.utime(p, (t, t))
EOF
echo $T
```

- [ ] **Step 2: dry-run 으로 제목 품질 확인**

LM Studio 가 떠 있어야 한다(`curl -s localhost:1234/v1/models | head -c 200`).

```bash
bin/snippetslab-autotitle --library $T/lib --state-dir $T/state --dry-run --all; cat $T/state/log
```
Expected: 마지막 줄 `{"generated": 3, "written": 0, ...}`. 로그의 세 제목이 40자 이내, 따옴표 없음, 본문 언어와 같음. 첫 호출은 모델 로드로 수십 초 걸릴 수 있다.

제목이 설명문처럼 길거나 영어로 나오면 `titler.SYSTEM_PROMPT` 를 고치고 Task 3 테스트를 다시 돌린 뒤 커밋한다. `<think>` 가 제목에 섞이면 `clean_title` 테스트를 추가한다.

- [ ] **Step 3: 커밋 (프롬프트를 고쳤을 때만)**

```bash
git add lib/sla/titler.py tests/test_titler.py && git commit -m "titler: 프롬프트 조정"
```

---

### Task 6: Spoon (`init.lua`)

**Files:**
- Create: `init.lua`

**Interfaces:**
- Consumes: `bin/snippetslab-autotitle --library DIR` 의 마지막 줄 JSON `{"written": n, ...}`
- Produces: `spoon.SnippetsLabAutoTitle` — 속성 `library, bundleID, quietSeconds, relaunchIdleSeconds, relaunchCheckSeconds, tool, logger`; 메서드 `init(), start(), stop(), runNow()`

- [ ] **Step 1: `init.lua` 작성**

```lua
--- === SnippetsLabAutoTitle ===
---
--- Give untitled SnippetsLab snippets a title from a local LLM (LM Studio).
---
--- SnippetsLab loads its library into memory at launch and never re-reads
--- local file changes, so the title is written straight into the snippet file
--- and the app is relaunched in the background once it is hidden and idle.
--- The app never becomes frontmost (its quick window is a non-activating
--- panel), so "leaving the app" is not an event. The app saving the snippet
--- file is the only reliable signal, and that is what this Spoon watches.
---
--- Titles this Spoon wrote are regenerated when the body changes. A title the
--- person typed is never touched. That bookkeeping lives in the Python side
--- (bin/snippetslab-autotitle); this file only watches, debounces, and relaunches.
---
--- Download: https://github.com/insoul/SnippetsLabAutoTitle.spoon

local obj = {}
obj.__index = obj

obj.name = "SnippetsLabAutoTitle"
obj.version = "0.1"
obj.author = "insoul <insoo.jung+github@gmail.com>"
obj.homepage = "https://github.com/insoul/SnippetsLabAutoTitle.spoon"
obj.license = "MIT - https://opensource.org/licenses/MIT"

local function scriptPath()
    return debug.getinfo(2, "S").source:sub(2):match("(.*/)")
end
obj.spoonPath = scriptPath()

--- SnippetsLabAutoTitle.library
--- Variable
--- Directory that holds one .data file per snippet.
obj.library = os.getenv("HOME")
    .. "/Library/Mobile Documents/iCloud~com~renfei~SnippetsLab/main.snippetslablibrary/Database/Snippets"

obj.bundleID = "com.renfei.SnippetsLab"
obj.quietSeconds = 30          -- run the tool after this much silence
obj.relaunchIdleSeconds = 300  -- relaunch only after this much silence
obj.relaunchCheckSeconds = 60
obj.logger = hs.logger.new("SLAutoTitle", "info")

local task, rerun, quietTimer, relaunchTimer
local lastEvent = 0
local relaunchPending = false

local function lastLine(s)
    local last
    for line in (s or ""):gmatch("[^\n]+") do last = line end
    return last
end

local function runTool(self)
    if task then rerun = true; return end
    task = hs.task.new(self.tool, function(code, out, err)
        task = nil
        local ok, e = pcall(function()
            if code ~= 0 then
                self.logger.e("tool exit " .. tostring(code) .. ": " .. (err or ""))
                return
            end
            local summary = hs.json.decode(lastLine(out) or "") or {}
            self.logger.i(lastLine(out) or "no summary")
            if (summary.written or 0) > 0 then
                relaunchPending = true
                self:_armRelaunch()
            end
        end)
        if not ok then self.logger.e(tostring(e)) end
        if rerun then rerun = false; runTool(self) end
    end, { "--library", self.library })
    if task then task:start() end
end

function obj:_onEvent()
    lastEvent = os.time()
    if quietTimer then quietTimer:stop() end
    quietTimer = hs.timer.doAfter(self.quietSeconds, function()
        quietTimer = nil
        runTool(self)
    end)
end

function obj:_armRelaunch()
    if relaunchTimer then return end
    relaunchTimer = hs.timer.doEvery(self.relaunchCheckSeconds, function()
        local ok, e = pcall(function() self:_tryRelaunch() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
end

local function disarm()
    if relaunchTimer then relaunchTimer:stop(); relaunchTimer = nil end
end

function obj:_tryRelaunch()
    if not relaunchPending then disarm(); return end
    local app = hs.application.get(self.bundleID)
    if not app then
        -- Not running: the next launch reads the new titles on its own.
        relaunchPending = false; disarm(); return
    end
    if os.time() - lastEvent < self.relaunchIdleSeconds then return end
    if not app:isHidden() and #app:visibleWindows() > 0 then return end

    relaunchPending = false
    disarm()
    local pid = app:pid()
    self.logger.i("relaunching SnippetsLab")
    app:kill()
    local tries = 0
    hs.timer.waitUntil(function()
        tries = tries + 1
        return hs.application.applicationForPID(pid) == nil or tries > 20
    end, function()
        if hs.application.applicationForPID(pid) then
            self.logger.w("SnippetsLab did not quit within 10s; not relaunching")
            relaunchPending = true
            self:_armRelaunch()
            return
        end
        -- `open -g` keeps focus where it is. hs.application.launchOrFocus would steal it.
        local t = hs.task.new("/usr/bin/open", nil, { "-g", "-b", self.bundleID })
        if t then t:start() end
        self.logger.i("relaunched")
    end, 0.5)
end

--- SnippetsLabAutoTitle:init()
--- Method
--- Resolves the bundled tool path. Called for you when the Spoon is loaded.
function obj:init()
    if not self.tool then
        self.tool = self.spoonPath .. "bin/snippetslab-autotitle"
    end
    return self
end

--- SnippetsLabAutoTitle:start()
--- Method
--- Start watching the library. Returns the Spoon object.
function obj:start()
    self:stop()
    self.watcher = hs.pathwatcher.new(self.library, function()
        local ok, e = pcall(function() self:_onEvent() end)
        if not ok then self.logger.e(tostring(e)) end
    end)
    self.watcher:start()
    self.logger.i("watching " .. self.library)
    return self
end

--- SnippetsLabAutoTitle:stop()
--- Method
--- Stop watching and cancel pending timers.
function obj:stop()
    if self.watcher then self.watcher:stop(); self.watcher = nil end
    if quietTimer then quietTimer:stop(); quietTimer = nil end
    disarm()
    return self
end

--- SnippetsLabAutoTitle:runNow()
--- Method
--- Run the tool immediately, without waiting for the quiet period.
function obj:runNow()
    runTool(self)
    return self
end

return obj
```

- [ ] **Step 2: 문법 확인**

```bash
cd ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon && luac -p init.lua 2>&1 || /Applications/Hammerspoon.app/Contents/Frameworks/*/luac -p init.lua 2>&1 || echo "luac 없음 — Step 3 의 reload 로 확인"
```
Expected: 출력 없음(문법 OK).

- [ ] **Step 3: 임시 라이브러리로 Hammerspoon 안에서 시험**

`~/.hammerspoon/init.lua` 는 아직 건드리지 않는다. Hammerspoon 콘솔(메뉴바 → Console)에서 Task 5 의 `$T` 경로를 넣어 실행한다.

```lua
local s = hs.loadSpoon("SnippetsLabAutoTitle")
s.library = "/private/tmp/…/lib"        -- Task 5 의 $T/lib
s.tool = s.spoonPath .. "bin/snippetslab-autotitle"
s.quietSeconds = 5
s:start()
```

그다음 터미널에서 파일 하나의 mtime 을 60초 전으로 바꿔 pathwatcher 이벤트를 만든다. Task 5 는 dry-run 이었으므로 제목은 아직 `untitled snippet` 이고, 이번엔 실제로 써진다(임시 라이브러리라 괜찮다):

```bash
/usr/bin/python3 -c 'import os,time,sys; t=time.time()-60; os.utime(sys.argv[1],(t,t))' $T/lib/A.data
```

Expected(콘솔 로그, 약 5초 후): `SLAutoTitle: {"generated": 1, "written": 1, "locked": 0, "skipped": 0, "errors": 0}`. 이어서 도구 자신의 쓰기로 이벤트가 한 번 더 오고 5초 뒤 `"skipped": 1` 인 줄이 찍혀야 한다(루프가 여기서 끝난다). `written > 0` 이었으므로 `relaunching` 은 앱이 숨겨져 있고 5분 조용해야 나온다. 이 시험에서는 기다리지 않는다. 단, Python 이 기본 상태 디렉토리(`~/.local/state/snippetslab-autotitle`)를 쓴다는 점을 기억한다. 실제 라이브러리와 무관한 `last_run` 이 기록되므로 시험이 끝나면 지운다:

```bash
rm -rf ~/.local/state/snippetslab-autotitle
```

`s:runNow()` 도 콘솔에서 한 번 부르고 같은 로그가 나오는지 본다. 끝나면 `s:stop()`.

- [ ] **Step 4: 재실행 조건값 확인 (앱을 죽이지는 않는다)**

`_tryRelaunch` 가 보는 두 값이 실제 앱 상태를 맞게 읽는지만 본다. 콘솔에서, SnippetsLab 창이 닫힌 상태로:

```lua
local app = hs.application.get("com.renfei.SnippetsLab"); print(app:isHidden(), #app:visibleWindows())
```

Expected: 두 번째 값이 `0`. 그다음 단축키로 SnippetsLab 창을 연 채 같은 줄을 다시 실행한다.
Expected: 두 번째 값이 `1` 이상이거나 첫 값이 `false`. 이 둘이 구분되면 조건식 `not app:isHidden() and #app:visibleWindows() > 0` 이 "창이 보인다" 를 맞게 잡는다. 실제 kill → `open -g` 는 스파이크에서 검증했으므로(포커스·숨김 유지) 여기서 반복하지 않는다.

- [ ] **Step 5: 커밋**

```bash
git add init.lua && git commit -m "Spoon: 감시·디바운스·백그라운드 재실행"
```

---

### Task 7: README 와 로드 연결

**Files:**
- Create: `README.md`
- Modify: `~/.hammerspoon/init.lua` (`imehint:start()` 다음 줄, 현재 839행 부근)

- [ ] **Step 1: `README.md`**

```markdown
# SnippetsLabAutoTitle.spoon

SnippetsLab 에서 제목 없이 저장한 스니펫에 LM Studio 로 만든 제목을 넣는다.

- 도구가 넣은 제목은 본문이 바뀌면 다시 만든다.
- 사용자가 직접 쓴 제목은 바꾸지 않는다.
- 포커스·선택·창 상태를 건드리지 않는다. 앱이 숨겨져 있고 5분간 조용할 때만 백그라운드로 재실행한다.

왜 이런 모양인지는 `docs/design.md` 에 있다.

## 설치

```sh
git clone https://github.com/insoul/SnippetsLabAutoTitle.spoon ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon
ln -sfn ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon/bin/snippetslab-autotitle ~/.local/bin/snippetslab-autotitle
```

`~/.hammerspoon/init.lua`:

```lua
hs.loadSpoon("SnippetsLabAutoTitle"):start()
```

LM Studio 가 `localhost:1234` 에서 서버 모드로 떠 있어야 한다.

## 설정

`~/.config/snippetslab-autotitle/config.json` (없으면 기본값):

```json
{
  "model": "qwen/qwen3.6-35b-a3b",
  "base_url": "http://localhost:1234/v1",
  "timeout": 60,
  "max_chars": 4000,
  "max_title_len": 40
}
```

## 명령행

```
snippetslab-autotitle            # 바뀐 파일을 처리 (Spoon 이 부르는 기본 동작)
snippetslab-autotitle --all      # 모든 파일을 본다 (처음 적용할 때)
snippetslab-autotitle --dry-run  # 쓰지 않고 판정·생성만
snippetslab-autotitle --status   # 상태와 잠금 목록
snippetslab-autotitle --unlock <UUID>   # 잠금을 풀고 다음 실행에서 다시 생성
```

상태·로그·백업은 `~/.local/state/snippetslab-autotitle/` 에 있다.

## 테스트

```sh
PYTHONPATH=lib:tests /usr/bin/python3 -m unittest discover -s tests -v
```
```

- [ ] **Step 2: `~/.hammerspoon/init.lua` 에 로드 추가**

`imehint:start()` 바로 아래에:

```lua
hs.loadSpoon("SnippetsLabAutoTitle"):start()
```

- [ ] **Step 3: Hammerspoon 리로드와 확인**

```bash
osascript -e 'tell application "Hammerspoon" to execute lua code "hs.reload()"' 2>&1 || echo "AppleScript 비활성 — 메뉴바 → Reload Config"
sleep 3
osascript -e 'tell application "Hammerspoon" to execute lua code "return tostring(spoon.SnippetsLabAutoTitle ~= nil)"' 2>&1
```
Expected: 두 번째 명령이 `true`. AppleScript 가 꺼져 있으면 콘솔에서 `spoon.SnippetsLabAutoTitle` 을 쳐서 테이블이 나오는지 본다. 콘솔에 `SLAutoTitle: watching …/Snippets` 가 찍혀야 한다.

- [ ] **Step 4: 커밋 (Spoon 리포)**

```bash
cd ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon && git add README.md && git commit -m "README"
```

`~/.hammerspoon` 리포의 커밋은 Task 8 이 끝난 뒤 서브모듈 등록과 함께 한다.

---

### Task 8: 실제 라이브러리에 첫 적용

**Files:** 없음 (운영 적용)

- [ ] **Step 1: dry-run 으로 실제 untitled 스니펫의 제목 미리 보기**

```bash
snippetslab-autotitle --dry-run --all; tail -20 ~/.local/state/snippetslab-autotitle/log
```
Expected: `generated` 가 현재 untitled 개수(약 13). 제목들이 본문에 맞는지 눈으로 본다. 이상하면 Task 5 처럼 프롬프트를 고친다.

- [ ] **Step 2: 실제 적용**

```bash
snippetslab-autotitle --all; snippetslab-autotitle --status
```
Expected: `written` 이 dry-run 의 `generated` 와 같음. `auto-titled: 13`. 백업이 `~/.local/state/snippetslab-autotitle/backup/` 에 생김.

- [ ] **Step 3: 재실행 후 앱에 보이는지 확인**

Spoon 의 pathwatcher 가 방금 쓰기를 봤고 `written > 0` 이므로 앱이 숨겨진 채 5분 지나면 스스로 재실행한다. 기다리기 싫으면 콘솔에서 `spoon.SnippetsLabAutoTitle.relaunchIdleSeconds = 0` 을 넣고 60초 안에 재실행되는지 본다.

```bash
/Applications/SnippetsLab.app/Contents/Helpers/lab search --title-only --nofuzzy --limit 0 "untitled snippet" | /usr/bin/python3 -c 'import json,sys; print(len(json.load(sys.stdin)["snippets"]))'
```
Expected: `0`.

- [ ] **Step 4: 잠금 동작 확인**

SnippetsLab 에서 자동 제목이 붙은 스니펫 하나의 제목을 손으로 고친다. 30초 뒤:

```bash
snippetslab-autotitle --status
```
Expected: `locked: 1` 과 그 UUID·제목. 로그에 `lock` 줄.

- [ ] **Step 5: 서브모듈 등록 (사용자 확인 후)**

GitHub 리포 생성과 push 는 외부로 나가는 작업이므로 사용자에게 확인받은 뒤 한다. 확인되면:

```bash
gh repo create insoul/SnippetsLabAutoTitle.spoon --public --source ~/.hammerspoon/Spoons/SnippetsLabAutoTitle.spoon --push
cd ~/.hammerspoon && git submodule add https://github.com/insoul/SnippetsLabAutoTitle.spoon.git Spoons/SnippetsLabAutoTitle.spoon
git add .gitmodules Spoons/SnippetsLabAutoTitle.spoon init.lua && git commit -m "SnippetsLabAutoTitle.spoon 추가"
```
`~/.hammerspoon` 의 push 도 별도 확인.
