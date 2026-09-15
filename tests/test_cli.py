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
        self.config = base / "config.json"
        self.calls = []

    def run_cli(self, *extra, generate=None):
        def gen(text):
            self.calls.append(text)
            return "생성된 제목"
        argv = [
            "--library", str(self.lib),
            "--state-dir", str(self.state_dir),
            "--config", str(self.config),
        ] + list(extra)
        out = StringIO()
        with mock.patch("sys.stdout", out):
            code = cli.main(argv, generate=generate or gen)
        self.assertEqual(code, 0)
        last = out.getvalue().strip().splitlines()[-1]
        try:
            return json.loads(last)
        except json.JSONDecodeError:
            return last

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
        st.last_run = time.time()
        st.save()
        self.run_cli("--unlock", "A")
        summary = self.run_cli()
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
            cli.main([
                "--library", str(self.lib),
                "--state-dir", str(self.state_dir),
                "--config", str(self.config),
                "--status",
            ])
        self.assertIn("내가 쓴 제목", out.getvalue())

    def test_failed_generation_retries_on_next_plain_run(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)

        def boom(text):
            raise cli.titler.TitleError("down")
        self.run_cli(generate=boom)
        summary = self.run_cli()
        self.assertEqual(summary["written"], 1)
        self.assertEqual(snippet.load(p).title, "생성된 제목")
        st = State.load(self.state_dir / "state.json")
        self.assertEqual(st.pending, [])

    def test_corrupt_state_does_not_crash(self):
        p = self.lib / "A.data"
        make_snippet(p, "A", "untitled snippet", ["hello"])
        old(p)
        self.state_dir.mkdir(parents=True)
        (self.state_dir / "state.json").write_text("{not json", "utf-8")
        summary = self.run_cli()
        self.assertIsInstance(summary, dict)
        self.assertIn("error", (self.state_dir / "log").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()
