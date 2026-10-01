import io
import json
import unittest

from sla import capture, titler


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(content):
    calls = []

    def opener(req, timeout=None):
        calls.append(json.loads(req.data.decode("utf-8")))
        body = {"choices": [{"message": {"content": content}}]}
        return FakeResponse(json.dumps(body).encode("utf-8"))

    opener.calls = calls
    return opener


CONFIG = dict(titler.DEFAULTS)


class DescribeTest(unittest.TestCase):
    def test_parses_json_title_and_language(self):
        op = opener_returning('{"title": "포트 목록 보기", "language": "bash"}')
        self.assertEqual(capture.describe("lsof -iTCP", CONFIG, op), ("포트 목록 보기", "bash", []))

    def test_json_inside_prose_and_think_block(self):
        op = opener_returning('<think>hmm</think>\nHere: {"title": "Hello", "language": null}')
        self.assertEqual(capture.describe("hi", CONFIG, op), ("Hello", None, []))

    def test_unknown_language_alias_is_dropped(self):
        op = opener_returning('{"title": "T", "language": "klingon"}')
        self.assertEqual(capture.describe("x", CONFIG, op), ("T", None, []))

    def test_language_alias_is_normalized(self):
        op = opener_returning('{"title": "T", "language": " Python3 "}')
        self.assertEqual(capture.describe("x", CONFIG, op), ("T", "python", []))

    def test_plain_text_answer_becomes_title(self):
        op = opener_returning('"Just a title."')
        self.assertEqual(capture.describe("x", CONFIG, op), ("Just a title", None, []))

    def test_title_is_cleaned_and_truncated(self):
        op = opener_returning(json.dumps({"title": "a" * 60, "language": "text"}))
        title, lang, tags = capture.describe("x", CONFIG, op)
        self.assertEqual(title, "a" * 40)
        self.assertEqual(lang, "text")
        self.assertEqual(tags, [])

    def test_empty_title_raises(self):
        op = opener_returning('{"title": "", "language": "bash"}')
        with self.assertRaises(titler.TitleError):
            capture.describe("x", CONFIG, op)

    def test_tags_are_returned_cleaned(self):
        op = opener_returning('{"title": "T", "language": "bash", "tags": [" Docker", "docker", "networking ", ""]}')
        self.assertEqual(capture.describe("x", CONFIG, op), ("T", "bash", ["docker", "networking"]))

    def test_tags_capped_and_excluded(self):
        op = opener_returning('{"title": "T", "language": "bash", "tags": ["bash", "shell", "docker", "k8s", "misc"]}')
        cfg = dict(CONFIG, max_tags=2, tag_exclude=["shell"])
        # 언어와 같은 태그(bash)와 제외 목록(shell)은 빠지고, 남은 것에서 앞의 둘만
        self.assertEqual(capture.describe("x", cfg, op)[2], ["docker", "k8s"])

    def test_tags_not_a_list_is_ignored(self):
        op = opener_returning('{"title": "T", "tags": "docker"}')
        self.assertEqual(capture.describe("x", CONFIG, op)[2], [])

    def test_sends_text_truncated_to_max_chars(self):
        op = opener_returning('{"title": "T"}')
        cfg = dict(CONFIG, max_chars=5)
        capture.describe("0123456789", cfg, op)
        self.assertEqual(op.calls[0]["messages"][1]["content"], "01234")


class FilterTagsTest(unittest.TestCase):
    def test_exclusion_is_case_insensitive_and_trimmed(self):
        self.assertEqual(capture.filter_tags(["Docker", "AWS", "todo"], ["aws ", "TODO"], None, 3), ["docker"])

    def test_language_and_its_lexer_name_are_dropped(self):
        self.assertEqual(capture.filter_tags(["python", "PythonLexer", "pandas"], [], "python", 3), ["pandas"])

    def test_dedupe_keeps_first_and_caps(self):
        self.assertEqual(capture.filter_tags(["a", "A", "b", "c", "d"], [], None, 3), ["a", "b", "c"])

    def test_zero_max_tags_disables(self):
        self.assertEqual(capture.filter_tags(["a"], [], None, 0), [])


class ExcludeFileTest(unittest.TestCase):
    def test_reads_lines_skipping_comments_and_blanks(self):
        import tempfile, os
        fd, path = tempfile.mkstemp()
        os.write(fd, "# 주석\n todo \n\nWIP\n".encode("utf-8")); os.close(fd)
        try:
            self.assertEqual(capture.load_exclude(path), ["todo", "WIP"])
        finally:
            os.unlink(path)

    def test_missing_file_is_empty(self):
        self.assertEqual(capture.load_exclude("/nonexistent/x.txt"), [])


def runner_with(results):
    """results: list of (returncode, stdout, stderr) returned in order; records argv/stdin."""
    calls = []

    def run(argv, stdin_text):
        calls.append((argv, stdin_text))
        return results[min(len(calls) - 1, len(results) - 1)]

    run.calls = calls
    return run


class CreateTest(unittest.TestCase):
    def test_builds_command_and_parses_uuid(self):
        run = runner_with([(0, '{"uuid":"ABC","title":"T","createdTags":[]}\n', "")])
        out = capture.create("body", "T", "bash", "/x/lab", run)
        self.assertEqual(out, {"uuid": "ABC", "title": "T", "language": "bash", "folder": None, "tags": []})
        argv, stdin_text = run.calls[0]
        self.assertEqual(argv, ["/x/lab", "create", "--launch", "--title", "T", "--language", "bash"])
        self.assertEqual(stdin_text, "body")

    def test_no_language_flag_when_none(self):
        run = runner_with([(0, '{"uuid":"ABC","title":"T"}', "")])
        capture.create("body", "T", None, "/x/lab", run)
        self.assertEqual(run.calls[0][0], ["/x/lab", "create", "--launch", "--title", "T"])

    def test_retries_without_language_when_lab_rejects_it(self):
        run = runner_with([
            (1, "", "error: Unknown language 'klingon'."),
            (0, '{"uuid":"ABC","title":"T"}', ""),
        ])
        out = capture.create("body", "T", "klingon", "/x/lab", run)
        self.assertEqual(out["uuid"], "ABC")
        self.assertIsNone(out["language"])
        self.assertEqual(run.calls[1][0], ["/x/lab", "create", "--launch", "--title", "T"])

    def test_other_errors_raise(self):
        run = runner_with([(1, "", "error: Write access is disabled.")])
        with self.assertRaises(capture.CaptureError) as cm:
            capture.create("body", "T", None, "/x/lab", run)
        self.assertIn("Write access", str(cm.exception))

    def test_unparseable_output_raises(self):
        run = runner_with([(0, "not json", "")])
        with self.assertRaises(capture.CaptureError):
            capture.create("body", "T", None, "/x/lab", run)

    def test_folder_flag_and_result(self):
        run = runner_with([(0, '{"uuid":"ABC","title":"T"}', "")])
        out = capture.create("body", "T", "bash", "/x/lab", run, folder="Clipboard")
        self.assertEqual(run.calls[0][0],
                         ["/x/lab", "create", "--launch", "--title", "T", "--language", "bash", "--folder", "Clipboard"])
        self.assertEqual(out["folder"], "Clipboard")

    def test_missing_folder_falls_back_to_root(self):
        run = runner_with([
            (1, "", "error: Folder 'Clipboard' does not exist."),
            (0, '{"uuid":"ABC","title":"T"}', ""),
        ])
        out = capture.create("body", "T", "bash", "/x/lab", run, folder="Clipboard")
        self.assertEqual(out["uuid"], "ABC")
        self.assertIsNone(out["folder"])
        self.assertEqual(out["language"], "bash")
        self.assertEqual(run.calls[1][0], ["/x/lab", "create", "--launch", "--title", "T", "--language", "bash"])

    def test_language_and_folder_both_rejected(self):
        run = runner_with([
            (1, "", "error: Unknown language 'klingon'."),
            (1, "", "error: Folder 'X' does not exist."),
            (0, '{"uuid":"ABC","title":"T"}', ""),
        ])
        out = capture.create("body", "T", "klingon", "/x/lab", run, folder="X")
        self.assertEqual((out["language"], out["folder"]), (None, None))
        self.assertEqual(run.calls[2][0], ["/x/lab", "create", "--launch", "--title", "T"])

    def test_tags_become_repeated_flags(self):
        run = runner_with([(0, '{"uuid":"ABC","title":"T","createdTags":["k8s"]}', "")])
        out = capture.create("body", "T", None, "/x/lab", run, folder=None, tags=["docker", "k8s"])
        self.assertEqual(run.calls[0][0], ["/x/lab", "create", "--launch", "--title", "T", "--tag", "docker", "--tag", "k8s"])
        self.assertEqual(out["tags"], ["docker", "k8s"])

    def test_no_folder_when_none(self):
        run = runner_with([(0, '{"uuid":"ABC","title":"T"}', "")])
        out = capture.create("body", "T", None, "/x/lab", run, folder=None)
        self.assertNotIn("--folder", run.calls[0][0])
        self.assertIsNone(out["folder"])


class MainTest(unittest.TestCase):
    def test_empty_input_is_an_error(self):
        out = io.StringIO()
        code = capture.main([], stdin=io.StringIO("  \n"), stdout=out)
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(out.getvalue()))

    def test_happy_path_prints_json(self):
        out = io.StringIO()
        op = opener_returning('{"title": "T", "language": "lua"}')
        run = runner_with([(0, '{"uuid":"U1","title":"T"}', "")])
        code = capture.main(["--lab", "/x/lab", "--folder", "Clipboard"], stdin=io.StringIO("print(1)"), stdout=out,
                            opener=op, runner=run, config=CONFIG)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()),
                         {"uuid": "U1", "title": "T", "language": "lua", "folder": "Clipboard", "tags": []})
        self.assertEqual(run.calls[0][0][-2:], ["--folder", "Clipboard"])

    def test_lm_failure_is_reported(self):
        out = io.StringIO()

        def bad_opener(req, timeout=None):
            raise OSError("connection refused")

        code = capture.main(["--lab", "/x/lab"], stdin=io.StringIO("x"), stdout=out,
                            opener=bad_opener, runner=runner_with([(0, "{}", "")]), config=CONFIG)
        self.assertEqual(code, 1)
        self.assertIn("LM Studio", json.loads(out.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
