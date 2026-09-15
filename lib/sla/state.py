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
