import fcntl
import json
import os
import shutil
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
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.lib = base / "Snippets"
        self.lib.mkdir()
        self.state_dir = base / "state"
        self.config = base / "config.json"
        self.calls = []

    def run_cli(self, *extra, generate=None, app_running=None):
        def gen(text):
            self.calls.append(text)
            return "생성된 제목"
        if app_running is None:
            app_running = lambda: False
        argv = [
            "--library", str(self.lib),
            "--state-dir", str(self.state_dir),
            "--config", str(self.config),
        ] + list(extra)
        out = StringIO()
        with mock.patch("sys.stdout", out):
            code = cli.main(argv, generate=generate or gen, app_running=app_running)
        self.assertEqual(code, 0)
        last = out.getvalue().strip().splitlines()[-1]
        try:
            return json.loads(last)
        except json.JSONDecodeError:
            return last

    def state(self):
        return State.load(self.state_dir / "state.json")

    def log(self):
        return (self.state_dir / "log").read_text("utf-8")

    # --- 계획 단계 ---

    def test_plan_generates_but_does_not_write(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello", "world"])
        old(p)
        summary = self.run_cli()
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["planned"], 1)
        self.assertEqual(snippet.load(p).title, "untitled snippet")
        self.assertEqual(self.calls, ["hello\n\nworld"])
        plan = self.state().planned["A"]
        self.assertEqual(plan["title"], "생성된 제목")
        self.assertEqual(plan["seen_title"], "untitled snippet")
        self.assertIn("plan", self.log())

    def test_apply_writes_planned_and_records(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        summary = self.run_cli("--apply")
        self.assertEqual(summary["written"], 1)
        self.assertEqual(summary["planned"], 0)
        self.assertEqual(snippet.load(p).title, "생성된 제목")
        st = self.state()
        self.assertEqual(st.snippets["A"]["auto_title"], "생성된 제목")
        self.assertEqual(st.planned, {})
        self.assertTrue((self.state_dir / "backup").exists())
        self.assertIn("apply", self.log())

    def test_apply_does_not_call_generator(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        self.calls.clear()
        self.run_cli("--apply")
        self.assertEqual(self.calls, [])

    def test_replan_updates_existing_plan(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        make_snippet(p, "A", "untitled snippet", ["hello more"])
        old(p)
        summary = self.run_cli("--all", generate=lambda t: "새 계획")
        self.assertEqual(summary["planned"], 1)
        self.assertEqual(self.state().planned["A"]["title"], "새 계획")

    def test_second_plan_skips_own_write(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        self.run_cli("--apply")
        old(p)
        summary = self.run_cli("--all")
        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["planned"], 0)

    def test_user_title_locks_and_never_changes(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        self.run_cli("--apply")
        make_snippet(p, "A", "내가 쓴 제목", ["hello changed"])
        old(p)
        summary = self.run_cli("--all")
        self.assertEqual(summary["locked"], 1)
        self.assertEqual(snippet.load(p).title, "내가 쓴 제목")
        st = self.state()
        self.assertNotIn("A", st.snippets)
        self.assertEqual(st.locked["A"], "내가 쓴 제목")
        self.assertEqual(st.planned, {})

    def test_lock_drops_existing_plan(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        st = self.state()
        st.snippets["A"] = {"auto_title": "옛 자동 제목", "content_hash": "x"}
        st.save()
        make_snippet(p, "A", "내가 쓴 제목", ["hello"])
        old(p)
        self.run_cli("--all")
        self.assertEqual(self.state().planned, {})

    def test_recent_files_are_left_alone(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])   # mtime = now
        summary = self.run_cli()
        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["planned"], 0)

    def test_only_files_changed_since_last_run(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p, 600)
        st = self.state()
        st.last_run = time.time() - 300
        st.save()
        self.assertEqual(self.run_cli()["generated"], 0)
        self.assertEqual(self.run_cli("--all")["generated"], 1)

    def test_dry_run_saves_nothing(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        summary = self.run_cli("--dry-run")
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["planned"], 0)
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
        self.assertEqual(summary["planned"], 0)
        self.assertEqual(self.state().pending, ["A"])

    def test_failed_generation_retries_on_next_plain_run(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)

        def boom(text):
            raise cli.titler.TitleError("down")
        self.run_cli(generate=boom)
        summary = self.run_cli()
        self.assertEqual(summary["planned"], 1)
        self.assertEqual(self.state().pending, [])

    def test_unlock_then_replans_over_user_title(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "내가 쓴 제목", ["hello"])
        old(p)
        st = self.state()
        st.locked["A"] = "내가 쓴 제목"
        st.last_run = time.time()
        st.save()
        self.run_cli("--unlock", "A")
        summary = self.run_cli()
        self.assertEqual(summary["planned"], 1)
        self.run_cli("--apply")
        self.assertEqual(snippet.load(p).title, "생성된 제목")
        st = self.state()
        self.assertEqual(st.force, [])
        self.assertNotIn("A", st.locked)

    # --- 적용 단계의 안전장치 ---

    def test_apply_skips_file_changed_after_plan(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        make_snippet(p, "A", "내가 쓴 제목", ["hello"])
        summary = self.run_cli("--apply")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(snippet.load(p).title, "내가 쓴 제목")
        self.assertEqual(self.state().planned, {})
        self.assertIn("skip-changed", self.log())

    def test_apply_skips_content_changed_after_plan(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        make_snippet(p, "A", "untitled snippet", ["hello edited"])
        summary = self.run_cli("--apply")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(snippet.load(p).title, "untitled snippet")

    def test_apply_drops_plan_for_deleted_file(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        p.unlink()
        summary = self.run_cli("--apply")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(self.state().planned, {})
        self.assertIn("skip-gone", self.log())

    def test_apply_refuses_while_app_running(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        summary = self.run_cli("--apply", app_running=lambda: True)
        self.assertTrue(summary["app_running"])
        self.assertEqual(summary["written"], 0)
        self.assertEqual(summary["planned"], 1)
        self.assertEqual(snippet.load(p).title, "untitled snippet")
        self.assertEqual(len(self.state().planned), 1)
        self.assertIn("apply refused", self.log())

    def test_apply_and_dry_run_are_exclusive(self):
        with self.assertRaises(SystemExit):
            with mock.patch("sys.stderr", StringIO()):
                cli.main(["--apply", "--dry-run", "--library", str(self.lib), "--state-dir", str(self.state_dir)])

    def test_apply_error_moves_plan_to_pending(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        with mock.patch("sla.cli.snippet.write_title", side_effect=OSError("disk")):
            summary = self.run_cli("--apply")
        self.assertEqual(summary["errors"], 1)
        st = self.state()
        self.assertEqual(st.planned, {})
        self.assertEqual(st.pending, ["A"])

    def test_plain_plan_after_apply_skips_own_write(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.run_cli()
        self.run_cli("--apply")
        # 도구 자신의 쓰기로 mtime > last_run 이 된 상태. --all 없이도 skip 이어야 한다.
        summary = self.run_cli()
        self.assertEqual(summary["generated"], 0)
        self.assertEqual(summary["planned"], 0)

    def test_apply_with_nothing_planned_is_noop(self):
        summary = self.run_cli("--apply")
        self.assertEqual(summary, {"generated": 0, "written": 0, "locked": 0, "skipped": 0, "errors": 0, "planned": 0})

    # --- 상태·잠금·로그 ---

    def test_status_prints_locked_and_planned(self):
        st = self.state()
        st.locked["A"] = "내가 쓴 제목"
        st.planned["B"] = {"title": "계획된 제목", "seen_title": "untitled snippet", "content_hash": "h"}
        st.pending.append("C")
        st.save()
        out = StringIO()
        with mock.patch("sys.stdout", out):
            cli.main([
                "--library", str(self.lib),
                "--state-dir", str(self.state_dir),
                "--config", str(self.config),
                "--status",
            ])
        self.assertIn("내가 쓴 제목", out.getvalue())
        self.assertIn("planned: 1", out.getvalue())
        self.assertIn("계획된 제목", out.getvalue())
        self.assertIn("pending: C", out.getvalue())

    def test_corrupt_state_does_not_crash(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "state.json").write_text("{not json", "utf-8")
        summary = self.run_cli()
        self.assertIsInstance(summary, dict)
        self.assertIn("error", self.log())

    def test_busy_when_lock_held(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.state_dir.mkdir(parents=True)
        fd = os.open(str(self.state_dir / "lock"), os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        summary = self.run_cli()
        self.assertTrue(summary["busy"])
        self.assertEqual(summary["generated"], 0)
        summary = self.run_cli("--apply")
        self.assertTrue(summary["busy"])

    def test_log_rotates_when_over_limit(self):
        with mock.patch("sla.cli.LOG_ROTATE_BYTES", 10):
            log = cli.Log(self.state_dir / "log")
            log.write("AAAAAAAA", "plan", "one")
            log.write("BBBBBBBB", "plan", "two")
        self.assertTrue((self.state_dir / "log.1").exists())

    def test_state_save_error_still_prints_summary(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        with mock.patch("sla.cli.State.save", side_effect=OSError("disk")):
            summary = self.run_cli()
        self.assertEqual(summary["generated"], 1)
        self.assertEqual(summary["errors"], 1)
        self.assertIn("state save:", self.log())


if __name__ == "__main__":
    unittest.main()
