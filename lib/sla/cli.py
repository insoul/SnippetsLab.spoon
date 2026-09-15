"""snippetslab-autotitle 명령행.

두 단계로 나뉜다. 기본 실행(계획)은 바뀐 스니펫을 판정하고 제목을 생성해 상태 파일의
planned 에 쌓기만 한다. --apply 는 planned 를 파일에 쓴다. 파일 쓰기를 분리한 이유:
SnippetsLab 은 저장할 때마다 패키지를 통째로 다시 쓰면서 자기 캐시와 다른 파일을
캐시 내용으로 되돌리므로, 파일은 앱이 닫힌 동안에만 써야 한다. 그 순서는 Lua 가 맡는다.
"""
import argparse
import fcntl
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
    if not path.exists():
        return cfg, None
    try:
        cfg.update(json.loads(path.read_text("utf-8")))
        return cfg, None
    except (ValueError, OSError) as e:
        return dict(titler.DEFAULTS), str(e)


def parse(argv):
    ap = argparse.ArgumentParser(prog="snippetslab-autotitle")
    ap.add_argument("--apply", action="store_true", help="계획된 제목을 파일에 쓴다 (앱이 닫힌 상태에서)")
    ap.add_argument("--all", action="store_true", help="last_run 을 무시하고 모든 파일을 본다")
    ap.add_argument("--dry-run", action="store_true", help="판정과 생성만 하고 상태를 저장하지 않는다")
    ap.add_argument("--status", action="store_true", help="상태와 잠금·계획 목록을 보여 준다")
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
    print("planned: %d" % len(st.planned))
    for uuid, plan in sorted(st.planned.items()):
        print("  %s  %s" % (uuid, plan.get("title", "")))
    if st.force:
        print("force: %s" % ", ".join(st.force))
    if st.pending:
        print("pending: %s" % ", ".join(st.pending))


def _forget(st, uuid):
    if uuid in st.pending:
        st.pending.remove(uuid)
    st.planned.pop(uuid, None)


def plan_one(path, st, gen, log, dry_run, counts):
    """스니펫 하나를 판정하고, 제목이 필요하면 생성해 planned 에 넣는다. 파일은 건드리지 않는다."""
    s = snippet.load(path)
    has_content = any(c.strip() for c in s.contents)
    action = decide(st, s.uuid, s.title, s.content_hash, has_content)
    if action == "skip":
        counts["skipped"] += 1
        _forget(st, s.uuid)
        return
    if action == "lock":
        st.snippets.pop(s.uuid, None)
        st.locked[s.uuid] = s.title
        counts["locked"] += 1
        log.write(s.uuid, "lock" + ("(dry)" if dry_run else ""), s.title)
        _forget(st, s.uuid)
        return
    title = gen("\n\n".join(s.contents))
    counts["generated"] += 1
    log.write(s.uuid, "plan" + ("(dry)" if dry_run else ""), title)
    if dry_run:
        return
    # seen_title/content_hash 는 적용 직전에 "계획 시점과 같은 파일인지" 를 확인하는 기준이다
    st.planned[s.uuid] = {"title": title, "seen_title": s.title, "content_hash": s.content_hash}
    if s.uuid in st.pending:
        st.pending.remove(s.uuid)


def apply_one(path, uuid, plan, st, log, backup_dir, counts):
    """planned 항목 하나를 파일에 쓴다. 계획 시점과 파일이 다르면 계획을 버린다."""
    if not path.exists():
        log.write(uuid, "skip-gone")
        st.planned.pop(uuid, None)
        counts["skipped"] += 1
        return
    fresh = snippet.load(path)
    if fresh.title != plan.get("seen_title") or fresh.content_hash != plan.get("content_hash"):
        # 계획 후 사용자가 손댔다. 다음 계획 때 다시 판정한다.
        log.write(uuid, "skip-changed")
        st.planned.pop(uuid, None)
        counts["skipped"] += 1
        return
    snippet.write_title(path, plan["title"], backup_dir=backup_dir)
    st.snippets[uuid] = {"auto_title": plan["title"], "content_hash": plan["content_hash"]}
    st.locked.pop(uuid, None)
    if uuid in st.force:
        st.force.remove(uuid)
    st.planned.pop(uuid, None)
    log.write(uuid, "apply", plan["title"])
    counts["written"] += 1


def run_plan(args, st, log, gen, counts):
    started = time.time()
    for path in sorted(Path(args.library).glob("*.data")):
        mtime = path.stat().st_mtime
        # snippet filenames are the snippet UUID
        if not (args.all or mtime > st.last_run or path.stem in st.pending or path.stem in st.force):
            continue
        if started - mtime < RECENT_SECONDS:
            continue
        try:
            plan_one(path, st, gen, log, args.dry_run, counts)
        except Exception as e:            # 한 파일의 실패가 다른 파일을 막지 않는다
            counts["errors"] += 1
            log.write(path.stem, "error", "%s: %s" % (type(e).__name__, e))
            if path.stem not in st.pending:
                st.pending.append(path.stem)
    if not args.dry_run:
        # 최근 RECENT_SECONDS 안에 바뀌어 건너뛴 파일이 다음 실행에 잡히도록 그만큼 앞당긴다
        st.last_run = started - RECENT_SECONDS


def run_apply(args, st, log, state_dir, counts):
    library = Path(args.library)
    for uuid, plan in sorted(st.planned.items()):
        try:
            apply_one(library / (uuid + ".data"), uuid, plan, st, log, state_dir / "backup", counts)
        except Exception as e:
            counts["errors"] += 1
            log.write(uuid, "error", "%s: %s" % (type(e).__name__, e))
            st.planned.pop(uuid, None)


def main(argv=None, generate=None):
    args = parse(argv)
    state_dir = Path(args.state_dir)
    st = State.load(state_dir / "state.json")
    log = Log(state_dir / "log")
    if st.load_error:
        log.write("-", "error", "state: " + st.load_error)

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

    state_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(state_dir / "lock"), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        print(json.dumps({
            "generated": 0, "written": 0, "locked": 0, "skipped": 0, "errors": 0,
            "planned": len(st.planned), "busy": True,
        }))
        return 0

    try:
        counts = {"generated": 0, "written": 0, "locked": 0, "skipped": 0, "errors": 0}
        if args.apply:
            run_apply(args, st, log, state_dir, counts)
        else:
            config, config_error = load_config(args.config)
            if config_error:
                log.write("-", "error", "config: " + config_error)
            gen = generate or (lambda text: titler.generate_title(text, config))
            run_plan(args, st, log, gen, counts)
        if not args.dry_run:
            try:
                st.save()
            except Exception as e:
                log.write("-", "error", "state save: %s" % e)
        counts["planned"] = len(st.planned)
        print(json.dumps(counts, ensure_ascii=False))
        return 0
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
