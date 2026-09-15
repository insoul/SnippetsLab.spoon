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
    name = "%s.%013d.data" % (path.stem, int(time.time() * 1000))
    (backup_dir / name).write_bytes(raw)
    olds = sorted(backup_dir.glob(path.stem + ".*.data"))
    for p in olds[:-keep]:
        p.unlink()
