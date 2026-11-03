"""Self-test of fork/ci/release_gate.py. Run: python3 fork/ci/test_release_gate.py"""
import datetime as dt
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import release_gate as rg  # noqa: E402

CAL = {"lines": [{"line": "0.1", "freeze": {"from": dt.date(2026, 12, 1), "to": dt.date(2026, 12, 14)},
                  "promote": dt.date(2026, 12, 15)}]}
GREEN = lambda: ([], [])  # noqa: E731


def run(name, status="completed", conclusion="success", attempt=1, event="push"):
    return {"path": f".github/workflows/{name}.yml", "name": name, "status": status, "conclusion": conclusion,
            "run_attempt": attempt, "event": event, "created_at": "2026-11-06T10:00:00Z"}


class Freeze(unittest.TestCase):
    def test_bounds_are_inclusive(self):
        self.assertIsNone(rg.active_freeze(CAL, dt.date(2026, 11, 30)))
        self.assertEqual(rg.active_freeze(CAL, dt.date(2026, 12, 1))["line"], "0.1")
        self.assertEqual(rg.active_freeze(CAL, dt.date(2026, 12, 14))["line"], "0.1")
        self.assertIsNone(rg.active_freeze(CAL, dt.date(2026, 12, 15)))

    def test_the_real_calendar_parses(self):
        import yaml
        with open(pathlib.Path(__file__).resolve().parent.parent / "calendar.yaml") as f:
            cal = yaml.safe_load(f)
        self.assertEqual(rg.active_freeze(cal, dt.date(2027, 9, 10))["line"], "1.0")


class CiState(unittest.TestCase):
    def test_failure_pending_and_ignored_workflows(self):
        failed, pending = rg.ci_state([run("fork-tests", conclusion="failure"), run("e2e-kind", status="in_progress"),
                                       run("verify-agent-deps", status="queued"), run("unifai-operator")])
        self.assertEqual(len(failed), 1)
        self.assertEqual(pending, ["e2e-kind"])

    def test_a_green_rerun_wins(self):
        self.assertEqual(rg.ci_state([run("fork-tests", conclusion="failure"),
                                      run("fork-tests", attempt=2)]), ([], []))

    def test_pull_request_runs_do_not_count(self):
        self.assertEqual(rg.ci_state([run("fork-tests", conclusion="failure", event="pull_request")]), ([], []))


class Decide(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.git("init", "-q", "-b", "devel")
        self.commit("chore: start", "2026-11-01")
        self.git("tag", "-a", "v0.1.54", "-m", "kind: manual")

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def git(self, *args, date=None):
        env = dict(os.environ, GIT_AUTHOR_DATE=date or "2026-11-01T12:00:00", GIT_COMMITTER_DATE=date or
                   "2026-11-01T12:00:00")
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True,
                       env=env)

    def commit(self, subject, day):
        self.git("commit", "-q", "--allow-empty", "-m", subject, date=f"{day}T12:00:00+01:00")

    def test_only_the_post_release_commit_is_no_change(self):
        self.commit("release(fork): v0.1.54 published, next VERSION 0.1.55", "2026-11-02")
        ok, reason = rg.decide("HEAD", CAL, dt.date(2026, 11, 6), GREEN)
        self.assertFalse(ok)
        self.assertIn("nothing changed", reason)

    def test_a_fix_ships(self):
        self.commit("fix(rag): x", "2026-11-03")
        self.assertTrue(rg.decide("HEAD", CAL, dt.date(2026, 11, 6), GREEN)[0])

    def test_red_ci_blocks(self):
        self.commit("fix(rag): x", "2026-11-03")
        ok, reason = rg.decide("HEAD", CAL, dt.date(2026, 11, 6), lambda: (["fork-tests (failure)"], []))
        self.assertFalse(ok)
        self.assertIn("not green", reason)

    def test_a_feature_merged_during_the_freeze_blocks(self):
        self.commit("feat(ui): before the freeze", "2026-11-20")
        self.commit("fix(ui): in the freeze", "2026-12-02")
        self.assertTrue(rg.decide("HEAD", CAL, dt.date(2026, 12, 4), GREEN)[0])
        self.git("switch", "-q", "-c", "topic")
        self.commit("feat(rag)!: sneaked in", "2026-12-03")
        self.git("switch", "-q", "devel")
        self.git("merge", "-q", "--no-ff", "-m", "Merge topic", "topic", date="2026-12-03T13:00:00+01:00")
        ok, reason = rg.decide("HEAD", CAL, dt.date(2026, 12, 4), GREEN)
        self.assertFalse(ok)
        self.assertIn("sneaked in", reason)


if __name__ == "__main__":
    unittest.main()
