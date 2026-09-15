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
