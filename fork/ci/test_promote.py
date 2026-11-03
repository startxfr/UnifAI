"""Self-test of fork/ci/promote.py. Run: python3 fork/ci/test_promote.py"""
import datetime as dt
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import promote  # noqa: E402

CAL = {"lines": [
    {"line": "0.1", "freeze": {"from": dt.date(2026, 12, 1), "to": dt.date(2026, 12, 14)}, "promote": "2026-12-15"},
    {"line": "0.2", "freeze": {"from": dt.date(2027, 3, 1), "to": dt.date(2027, 3, 14)}, "promote": "2027-03-15"},
    {"line": "0.3", "freeze": {"from": dt.date(2027, 6, 1), "to": dt.date(2027, 6, 14)}, "promote": "2027-06-15"},
]}
TAG = {"type": "tag", "tagger": promote.BOT, "date": "2026-12-04T18:00:00+01:00", "kind": "weekly"}
DAY = dt.date(2026, 12, 15)


class Plan(unittest.TestCase):
    def test_first_line(self):
        tags = ["operator-v0.1.53", "v0.1.59", "v0.1.60", "v0.1.61", "v0.1.53-rc.2"]
        got = promote.plan("0.1.60", CAL, TAG, tags, DAY, True)
        self.assertEqual(got["errors"], [])
        self.assertEqual(got["skip_range"], ">=0.1.0 <0.1.60")
        self.assertEqual(got["next_devel"], "0.2.0")
        self.assertEqual(got["hotfix"], "0.1.62")  # after the newer weekly 0.1.61, never reusing a number
        self.assertEqual(got["newer"], ["v0.1.61"])

    def test_next_line_skips_from_the_previous_one(self):
        tag = dict(TAG, date="2027-03-05T18:00:00+01:00")
        got = promote.plan("0.2.7", CAL, tag, ["v0.2.7"], dt.date(2027, 3, 15), True)
        self.assertEqual((got["errors"], got["skip_range"], got["next_devel"], got["hotfix"]),
                         ([], ">=0.1.0 <0.2.7", "0.3.0", "0.2.8"))

    def test_refusals(self):
        young = dict(TAG, date="2026-12-11T18:00:00+01:00")
        self.assertEqual(len(promote.plan("0.1.60", CAL, young, [], DAY, True)["errors"]), 1)
        self.assertEqual(len(promote.plan("0.1.60", CAL, TAG, [], DAY, False)["errors"]), 1)  # canary
        old = dict(TAG, date="2026-11-20T18:00:00+01:00")
        self.assertEqual(len(promote.plan("0.1.60", CAL, old, [], dt.date(2026, 11, 30), True)["errors"]), 1)
        self.assertEqual(len(promote.plan("0.1.60", CAL, None, [], DAY, True)["errors"]), 1)
        rc = dict(TAG, kind="rc")
        self.assertEqual(len(promote.plan("0.1.60", CAL, rc, [], DAY, True)["errors"]), 1)
        human = dict(TAG, tagger="someone")
        self.assertEqual(len(promote.plan("0.1.60", CAL, human, [], DAY, True)["errors"]), 1)
        self.assertIn("not in", promote.plan("0.9.1", CAL, TAG, [], DAY, True)["errors"][0])
        last = dict(TAG, date="2027-06-05T18:00:00+01:00")
        self.assertIn("no line after", promote.plan("0.3.2", CAL, last, [], dt.date(2027, 6, 15), True)["errors"][0])


if __name__ == "__main__":
    unittest.main()
