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
