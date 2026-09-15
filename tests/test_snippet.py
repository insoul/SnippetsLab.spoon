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
        root_uid = pl["$top"]["root"].data
        root = pl["$objects"][root_uid]
        title_uid = root[K + "SnippetTitle"].data
        # root 의 SnippetTitle UID 는 쓰기에서 바뀌므로 비교에서 뺀다
        skip = (title_uid, root_uid)
        return [o for i, o in enumerate(pl["$objects"]) if i not in skip], root[K + "SnippetDateModified"]

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
