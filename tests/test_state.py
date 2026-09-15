import shutil
import tempfile
import unittest
from pathlib import Path

from sla.state import State, decide


class StateFileTest(unittest.TestCase):
    def test_missing_file_is_empty_state(self):
        st = State.load(Path(tempfile.mkdtemp()) / "state.json")
        self.assertEqual(st.last_run, 0.0)
        self.assertEqual(st.snippets, {})
        self.assertEqual(st.locked, {})
        self.assertEqual(st.force, [])
        self.assertEqual(st.pending, [])
        self.assertIsNone(st.load_error)

    def test_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "sub" / "state.json"
        st = State.load(path)
        st.last_run = 12.5
        st.snippets["A"] = {"auto_title": "t", "content_hash": "h"}
        st.locked["B"] = "mine"
        st.force.append("C")
        st.pending.append("D")
        st.planned["E"] = {"title": "t", "seen_title": "untitled snippet", "content_hash": "h"}
        st.save()
        again = State.load(path)
        self.assertEqual(again.last_run, 12.5)
        self.assertEqual(again.snippets, {"A": {"auto_title": "t", "content_hash": "h"}})
        self.assertEqual(again.locked, {"B": "mine"})
        self.assertEqual(again.force, ["C"])
        self.assertEqual(again.pending, ["D"])
        self.assertEqual(again.planned, {"E": {"title": "t", "seen_title": "untitled snippet", "content_hash": "h"}})
        self.assertIsNone(again.load_error)


class DecideTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.st = State.load(d / "state.json")
        self.st.snippets["A"] = {"auto_title": "auto", "content_hash": "h1"}

    def test_untitled_generates(self):
        self.assertEqual(decide(self.st, "X", "untitled snippet", "h", True), "generate")

    def test_same_auto_title_same_hash_skips(self):
        self.assertEqual(decide(self.st, "A", "auto", "h1", True), "skip")

    def test_same_auto_title_new_hash_regenerates(self):
        self.assertEqual(decide(self.st, "A", "auto", "h2", True), "regenerate")

    def test_changed_title_with_record_locks(self):
        self.assertEqual(decide(self.st, "A", "user wrote this", "h1", True), "lock")

    def test_user_title_without_record_skips(self):
        self.assertEqual(decide(self.st, "X", "user wrote this", "h", True), "skip")

    def test_empty_content_never_generates(self):
        self.assertEqual(decide(self.st, "X", "untitled snippet", "h", False), "skip")
        self.assertEqual(decide(self.st, "A", "auto", "h2", False), "skip")

    def test_force_generates_over_user_title(self):
        self.st.force.append("X")
        self.assertEqual(decide(self.st, "X", "user wrote this", "h", True), "generate")


if __name__ == "__main__":
    unittest.main()
