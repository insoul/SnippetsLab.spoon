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
