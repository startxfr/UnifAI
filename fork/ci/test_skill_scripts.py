"""Black-box tests of the four scripts of the fork skills under .claude/skills (no network, no real remote).

    check-staged.sh, push-own-sha.sh   (fork-commit-push)
    prepare-cut.sh                     (fork-cut-prep)
    verify-release.sh                  (fork-verify-release)

Each test copies the scripts and fork/ci/release_images.py into a throwaway git repository whose `origin` is a local
bare repository named like startxfr/UnifAI (push-own-sha.sh refuses any other), and puts fake gh, skopeo, cosign, opm,
make (and date) first in PATH. Run: python3 fork/ci/test_skill_scripts.py  (or pytest -q fork/ci)
"""
import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".claude" / "skills"
SCRIPTS = {
    "check-staged.sh": SKILLS / "fork-commit-push/scripts/check-staged.sh",
    "push-own-sha.sh": SKILLS / "fork-commit-push/scripts/push-own-sha.sh",
    "prepare-cut.sh": SKILLS / "fork-cut-prep/scripts/prepare-cut.sh",
    "verify-release.sh": SKILLS / "fork-verify-release/scripts/verify-release.sh",
}
IMAGES = ["operator", "rag", "multiagent", "backend", "identity", "ui"]
GH = "startxfr/UnifAI"
ISSUER = "https://token.actions.githubusercontent.com"

PUBLISH_IMAGES = """name: publish-images
on:
  push:
    branches: [devel, "release-*"]
    paths:
      - rag/**
      - multi-agent/**
      - backend/**
      - shared-resources/identity/**
      - ui/**
      - global_utils/**
      - .github/workflows/publish-images.yml
      - fork/ci/**
      - fork/unifai-operator/cmd/**
      - fork/unifai-operator/api/**
      - fork/unifai-operator/internal/**
      - fork/unifai-operator/go.mod
      - fork/unifai-operator/go.sum
      - fork/unifai-operator/Dockerfile
      - fork/unifai-operator/Makefile
  workflow_dispatch:
"""
FORK_ONLY = "Makefile\nMEMORY.md\nfork/\n.fork/\n.github/workflows/publish-images.yml\n"
OPERATOR_MAKEFILE = "VERSION ?= 0.1.74\nOPERATOR_BUILD_PATHS := cmd api internal go.mod go.sum Dockerfile Makefile\n"
RELEASE_GATE_STUB = """import datetime as dt
from zoneinfo import ZoneInfo
PARIS = ZoneInfo("Europe/Paris")
def active_freeze(calendar, day):
    for line in calendar["lines"]:
        if dt.date.fromisoformat(str(line["freeze"]["from"])) <= day <= dt.date.fromisoformat(str(line["freeze"]["to"])):
            return line
    return None
if __name__ == "__main__":
    print("gate stub: ok")
"""


def sh(cwd, *cmd, env=None, check=True):
    r = subprocess.run(list(cmd), cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise AssertionError(f"{cmd} failed: {r.stdout}{r.stderr}")
    return r


def write(path, text, mode=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


class Sandbox:
    """A work clone on devel, its bare origin (path contains startxfr/UnifAI), a stub bin dir, an env."""

    _template = None

    @classmethod
    def template(cls):
        if cls._template is None:
            base = pathlib.Path(tempfile.mkdtemp(prefix="skill-tests-template-"))
            env = cls.git_env(base)
            origin = base / "startxfr" / "UnifAI.git"
            work = base / "work"
            origin.parent.mkdir()
            sh(base, "git", "init", "-q", "--template=", "--bare", str(origin), env=env)
            sh(base, "git", "init", "-q", "--template=", str(work), env=env)
            sh(work, "git", "checkout", "-q", "-b", "devel", env=env)
            sh(work, "git", "remote", "add", "origin", str(origin), env=env)
            write(work / ".gitignore", "__pycache__/\nbin/\n")  # as the real repository: the scripts leave these
            write(work / "README.md", "readme\n")
            write(work / "Makefile", "all:\n")
            write(work / ".github/workflows/publish-images.yml", PUBLISH_IMAGES)
            write(work / "fork/fork-only-paths", FORK_ONLY)
            write(work / "fork/calendar.yaml", "lines: []\n")
            write(work / "fork/unifai-operator/Makefile", OPERATOR_MAKEFILE)
            write(work / "fork/unifai-operator/internal/a.go", "package internal\n")
            write(work / "multi-agent/a.py", "a = 1\n")
            (work / "fork/ci").mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / "fork/ci/release_images.py", work / "fork/ci/release_images.py")
            write(work / "fork/ci/release_gate.py", RELEASE_GATE_STUB)
            for name, src in SCRIPTS.items():
                dst = work / src.relative_to(ROOT)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dst)
            sh(work, "git", "add", "-A", env=env)
            sh(work, "git", "commit", "-q", "-m", "initial", env=env)
            sh(work, "git", "tag", "-a", "-m", "kind: manual", "v0.1.73", env=env)
            sh(work, "git", "push", "-q", "origin", "devel", "--tags", env=env)
            sh(work, "git", "branch", "-q", "--set-upstream-to=origin/devel", env=env)
            cls._template = base
        return cls._template

    @staticmethod
    def git_env(home):
        env = dict(os.environ)
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="Tester", GIT_AUTHOR_EMAIL="t@example.org",
                   GIT_COMMITTER_NAME="Tester", GIT_COMMITTER_EMAIL="t@example.org", GIT_TERMINAL_PROMPT="0")
        return env

    def __init__(self):
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="skill-tests-"))
        shutil.copytree(self.template(), self.base, symlinks=True, dirs_exist_ok=True)
        self.work, self.origin = self.base / "work", self.base / "startxfr" / "UnifAI.git"
        self.bin = self.base / "stubs" / "bin"
        self.bin.mkdir(parents=True)
        self.env = self.git_env(self.base)
        self.env["PATH"] = f"{self.bin}:{os.environ['PATH']}"
        self.env["STUB_DIR"] = str(self.base / "stubs")
        self.git("remote", "set-url", "origin", str(self.origin))

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def git(self, *args, check=True):
        return sh(self.work, "git", *args, env=self.env, check=check)

    def commit(self, path, text="x\n", msg="change"):
        write(self.work / path, text)
        self.git("add", path)
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def origin_rev(self, ref="refs/heads/devel"):
        return sh(self.origin, "git", "rev-parse", ref, env=self.env).stdout.strip()

    def other_session_pushes(self, path, msg="from another session"):
        """Another clone adds a commit on origin/devel."""
        other = self.base / "other"
        sh(self.base, "git", "clone", "-q", "-b", "devel", str(self.origin), str(other), env=self.env)
        write(other / path, "other\n")
        sh(other, "git", "add", path, env=self.env)
        sh(other, "git", "commit", "-q", "-m", msg, env=self.env)
        sh(other, "git", "push", "-q", "origin", "devel", env=self.env)
        shutil.rmtree(other)

    def stub(self, name, body):
        write(self.bin / name, "#!/usr/bin/env bash\n" + body, 0o755)

    def run(self, script, *args, cwd=None):
        path = self.work / SCRIPTS[script].relative_to(ROOT)
        r = subprocess.run(["bash", str(path), *args], cwd=cwd or self.work, env=self.env, capture_output=True,
                           text=True, timeout=120)
        return r.returncode, r.stdout + r.stderr


def tearDownModule():
    if Sandbox._template:
        shutil.rmtree(Sandbox._template, ignore_errors=True)


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)


# ---------------------------------------------------------------- check-staged.sh
class CheckStaged(SandboxTest):
    def check(self):
        return self.sb.run("check-staged.sh")

    def stage(self, path, text="y\n"):
        write(self.sb.work / path, text)
        self.sb.git("add", path)

    def test_refuses_outside_devel(self):
        self.sb.git("checkout", "-q", "-b", "other")
        self.stage("README.md")
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: on 'other'", out)

    def test_refuses_nothing_staged(self):
        rc, out = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: nothing staged", out)

    def test_application_code_rebuilds_the_five_images_not_the_operator(self):
        self.stage("multi-agent/a.py")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("M multi-agent/a.py   [rebuilds backend,identity,multiagent,rag,ui]", out)
        self.assertIn("WARNING rebuilds the five application images", out)
        self.assertNotIn("OPERATOR", out)

    def test_operator_code_rebuilds_the_operator_only(self):
        self.stage("fork/unifai-operator/internal/a.go")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("[rebuilds operator; fork-only]", out)
        self.assertIn("WARNING rebuilds the OPERATOR image", out)
        self.assertNotIn("five application images", out)

    def test_operator_makefile_and_go_mod_count_but_docs_and_tests_do_not(self):
        self.stage("fork/unifai-operator/Makefile", "VERSION ?= 0.1.75\n")
        self.assertIn("rebuilds operator", self.check()[1])
        self.sb.git("reset", "-q")
        self.stage("fork/unifai-operator/docs/x.md")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("rebuilds", out)
        self.assertNotIn("WARNING", out)

    def test_workflow_publish_images_rebuilds_everything(self):
        self.stage(".github/workflows/publish-images.yml", PUBLISH_IMAGES + "# c\n")
        rc, out = self.check()
        self.assertIn("rebuilds backend,identity,multiagent,operator,rag,ui", out)
        self.assertIn("WARNING rebuilds the OPERATOR image", out)
        self.assertIn("WARNING rebuilds the five application images", out)

    def test_fork_ci_only_starts_a_run_without_rebuild(self):
        self.stage("fork/ci/release_gate.py", RELEASE_GATE_STUB + "# c\n")
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("[starts publish-images; fork-only]", out)
        self.assertIn("NOTE starts a publish-images run that rebuilds nothing", out)
        self.assertNotIn("WARNING", out)

    def test_note_run_without_rebuild_is_absent_when_an_image_rebuilds(self):
        self.stage("fork/ci/x.py")
        self.stage("multi-agent/a.py")
        self.assertNotIn("rebuilds nothing", self.check()[1])

    def test_new_file_outside_fork_only_paths_is_a_question(self):
        self.stage("docs/new.md")
        self.stage("fork/new.md")
        rc, out = self.check()
        self.assertIn("QUESTION new file not covered by fork/fork-only-paths: docs/new.md", out)
        self.assertNotIn("fork/new.md --", out)  # the fork/ file is covered

    def test_modified_file_outside_fork_only_paths_is_not_a_question(self):
        self.stage("README.md")
        self.assertNotIn("QUESTION", self.check()[1])

    def test_other_sessions_work_is_reported_not_staged(self):
        self.stage("README.md")
        write(self.sb.work / "Makefile", "changed\n")      # tracked, unstaged
        write(self.sb.work / "untracked.txt", "u\n")      # untracked
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertIn("NOTE 2 unstaged or untracked path(s) left out", out)

    def test_staged_only_files_are_not_reported_as_left_out(self):
        self.stage("README.md")
        self.assertNotIn("left out", self.check()[1])

    def test_does_not_touch_the_index(self):
        self.stage("README.md")
        before = self.sb.git("diff", "--cached", "--name-status").stdout
        self.check()
        self.assertEqual(self.sb.git("diff", "--cached", "--name-status").stdout, before)


# ---------------------------------------------------------------- push-own-sha.sh
class PushOwnSha(SandboxTest):
    def setUp(self):
        super().setUp()
        self.sb.stub("gh", "exit 1\n")  # no network, no GitHub on Fridays

    def push(self, sha, n, *flags):
        return self.sb.run("push-own-sha.sh", sha, str(n), *flags)

    def test_usage_without_arguments(self):
        rc, out = self.sb.run("push-own-sha.sh")
        self.assertNotEqual(rc, 0)
        self.assertIn("usage", out)

    def test_refuses_an_origin_that_is_not_the_fork(self):
        self.sb.git("remote", "set-url", "origin", str(self.sb.base / "elsewhere.git"))
        sha = self.sb.commit("README.md")
        rc, out = self.push(sha, 1)
        self.assertEqual(rc, 1)
        self.assertIn("REFUSE: origin is not startxfr/UnifAI", out)

    def test_check_only_lists_the_commits_and_pushes_nothing(self):
        before = self.sb.origin_rev()
        sha = self.sb.commit("README.md", msg="docs: mine")
        rc, out = self.push(sha, 1)
        self.assertEqual(rc, 0, out)
        self.assertIn("Would send 1 commit(s) to devel:", out)
        self.assertIn("Tester: docs: mine", out)
        self.assertIn("check only: add --push", out)
        self.assertEqual(self.sb.origin_rev(), before)

    def test_refuses_when_other_commits_sit_under_mine(self):
        before = self.sb.origin_rev()
        self.sb.commit("a.txt", msg="other session's commit")
        sha = self.sb.commit("b.txt", msg="mine")
        for flags in ((), ("--push",)):
            rc, out = self.push(sha, 1, *flags)
            self.assertEqual(rc, 1, out)
            self.assertIn("REFUSE: 2 commit(s), you expected 1", out)
        self.assertEqual(self.sb.origin_rev(), before)

    def test_two_commits_expected_two(self):
        self.sb.commit("a.txt")
        sha = self.sb.commit("b.txt")
        rc, out = self.push(sha, 2)
        self.assertEqual(rc, 0, out)
        self.assertIn("Would send 2 commit(s)", out)

    def test_refuses_a_commit_that_does_not_build_on_origin_devel(self):
        sha = self.sb.commit("README.md")
        self.sb.other_session_pushes("elsewhere.txt")
        before = self.sb.origin_rev()
        rc, out = self.push(sha, 1, "--push")
        self.assertEqual(rc, 1, out)
        self.assertIn("does not build on origin/devel", out)
        self.assertEqual(self.sb.origin_rev(), before)

    def test_rebased_commit_is_accepted_after_the_other_push(self):
        self.sb.other_session_pushes("elsewhere.txt")
        self.sb.git("pull", "-q", "--rebase", "origin", "devel")
        sha = self.sb.commit("README.md")
        rc, out = self.push(sha, 1)
        self.assertEqual(rc, 0, out)

    def test_unknown_sha_is_refused(self):
        rc, out = self.push("0" * 40, 1)
        self.assertEqual(rc, 1)

    def test_push_sends_exactly_the_sha_to_devel_only(self):
        sha = self.sb.commit("README.md")
        self.sb.commit("later.txt", msg="a later local commit, not mine")
        rc, out = self.push(sha, 1, "--push")
        self.assertEqual(rc, 0, out)
        self.assertIn("pushed", out)
        self.assertEqual(self.sb.origin_rev(), sha)
        refs = sh(self.sb.origin, "git", "for-each-ref", "--format=%(refname)", env=self.sb.env).stdout.split()
        self.assertEqual([r for r in refs if not r.startswith("refs/tags/")], ["refs/heads/devel"])

    def test_current_branch_does_not_matter_target_is_always_devel(self):
        sha = self.sb.commit("README.md")
        self.sb.git("checkout", "-q", "-b", "main-like")
        rc, out = self.push(sha, 1, "--push")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.sb.origin_rev(), sha)

    def test_image_impact_warnings_on_the_whole_range(self):
        sha = self.sb.commit("multi-agent/a.py", "a = 2\n")
        self.assertIn("WARNING rebuilds the five application images", self.push(sha, 1)[1])
        self.sb.git("reset", "-q", "--hard", "origin/devel")
        sha = self.sb.commit("fork/unifai-operator/internal/a.go", "package internal // c\n")
        rc, out = self.push(sha, 1)
        self.assertIn("WARNING rebuilds the OPERATOR image", out)
        self.assertNotIn("five application images", out)

    def test_docs_only_range_has_no_image_warning(self):
        sha = self.sb.commit("fork/ROADMAP.md")
        self.assertNotIn("WARNING rebuilds", self.push(sha, 1)[1])

    def friday(self, last_cron):
        """date reports a Friday; gh reports the createdAt of the last scheduled weekly run (or nothing)."""
        self.sb.stub("date", 'case "$*" in "-u +%u") echo 5 ;; "-u +%F") echo 2026-11-20 ;; *) exec /bin/date "$@" ;; esac\n')
        self.sb.stub("gh", f"echo '{last_cron}'\n")

    def test_friday_before_the_weekly_cron_warns(self):
        self.friday("2026-11-13T17:05:00Z")
        sha = self.sb.commit("README.md")
        self.assertIn("WARNING Friday and the weekly cron has not run yet", self.push(sha, 1)[1])

    def test_friday_after_the_weekly_cron_does_not_warn(self):
        self.friday("2026-11-20T17:05:00Z")
        sha = self.sb.commit("README.md")
        rc, out = self.push(sha, 1)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Friday", out)


# ---------------------------------------------------------------- prepare-cut.sh
CI_IMAGE_REF = "quay.io/zuno/unifai-operator@sha256:" + "a" * 64


class PrepareCut(SandboxTest):
    def setUp(self):
        super().setUp()
        self.out = self.sb.base / "out" / "cut.sh"
        self.out.parent.mkdir()
        self.make_ok()

    def make_ok(self, e2e=True):
        e2e_line = "echo 'canary: E2E_VERSION=devel-abc1234 make canary-ci canary-e2e-full canary-delete'" if e2e else "true"
        self.sb.stub("make", f'''case "$*" in *ci-image*)
  mkdir -p "$PWD/bin" "{self.sb.work}/fork/unifai-operator/bin"
  echo "{CI_IMAGE_REF}" > "{self.sb.work}/fork/unifai-operator/bin/ci-image.ref"
  echo "devel-abc1234 signed, reports 0.1.74"
  {e2e_line} ;; esac
''')

    def prepare(self, out=None):
        return self.sb.run("prepare-cut.sh", str(out or self.out))

    def test_usage_without_argument(self):
        rc, out = self.sb.run("prepare-cut.sh")
        self.assertNotEqual(rc, 0)
        self.assertIn("usage", out)

    def test_refuses_an_out_file_inside_the_repository(self):
        for inside in (self.sb.work / "cut.sh", self.sb.work / "fork" / "x" / "cut.sh", "fork/../cut.sh"):
            rc, out = self.sb.run("prepare-cut.sh", str(inside))
            self.assertEqual(rc, 2, out)
            self.assertIn("outside the repository", out)
        self.assertEqual(self.sb.git("status", "--porcelain").stdout.strip(), "")

    def test_relative_out_file_inside_the_repository_is_refused(self):
        rc, out = self.sb.run("prepare-cut.sh", "cut.sh")  # cwd is the repository
        self.assertEqual(rc, 2, out)
        self.assertFalse((self.sb.work / "cut.sh").exists())

    def test_writes_an_owner_script_with_the_four_steps(self):
        rc, out = self.prepare()
        self.assertEqual(rc, 0, out)
        self.assertIn("VERSION 0.1.74, last release v0.1.73", out)
        self.assertIn("cut v0.1.74 from devel", out)
        text = self.out.read_text()
        self.assertTrue(os.access(self.out, os.X_OK))
        self.assertEqual(sh(".", "bash", "-n", str(self.out), check=False).returncode, 0)
        self.assertIn("OPERATOR=sha256:" + "a" * 64, text)
        self.assertIn("E2E_TAG=devel-abc1234", text)
        for step in ("1)", "2)", "3)", "4)"):
            self.assertIn("\n" + step, text)
        self.assertIn("kind     = manual", text)
        self.assertIn("operator = $OPERATOR", text)

    def test_the_owner_script_prints_its_usage_and_triggers_nothing(self):
        self.prepare()
        r = subprocess.run(["bash", str(self.out)], capture_output=True, text=True, env=self.sb.env)
        self.assertIn("usage:", r.stdout)
        r = subprocess.run(["bash", str(self.out), "4"], capture_output=True, text=True, env=self.sb.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Wait for unifai-main", r.stdout)

    def test_lists_the_commits_that_change_the_operator_since_the_last_release(self):
        self.sb.commit("fork/unifai-operator/internal/b.go", "package internal // b\n", "fix(operator): the change")
        self.sb.commit("README.md", "docs\n", "docs: not the operator")
        self.sb.git("push", "-q", "origin", "devel")
        rc, out = self.prepare()
        self.assertEqual(rc, 0, out)
        listed = out.split("commits since v0.1.73 that change the operator image:")[1].split("== make ci-image")[0]
        self.assertIn("fix(operator): the change", listed)
        self.assertNotIn("docs: not the operator", listed)

    def test_warns_when_the_local_head_is_not_origin_devel(self):
        self.sb.commit("fork/unifai-operator/internal/b.go", "package internal // local\n", "local only")
        rc, out = self.prepare()
        self.assertEqual(rc, 0, out)
        self.assertIn("WARNING the local checkout is at", out)
        self.assertIn("NOT origin/devel's", out)

    def test_no_warning_when_in_sync(self):
        rc, out = self.prepare()
        self.assertNotIn("WARNING the local checkout", out)

    def calendar(self, start, end):
        write(self.sb.work / "fork/calendar.yaml",
              f'lines:\n  - line: "0.1"\n    freeze: {{ from: {start}, to: {end} }}\n    promote: {end}\n')

    def test_active_freeze_is_a_warning(self):
        import datetime as dt
        today = dt.date.today()
        self.calendar(today - dt.timedelta(days=1), today + dt.timedelta(days=5))
        rc, out = self.prepare()
        self.assertEqual(rc, 0, out)
        self.assertIn("freeze ACTIVE for line 0.1", out)
        self.assertIn("WARNING freeze ACTIVE", out)

    def test_no_freeze_reports_the_next_one(self):
        import datetime as dt
        today = dt.date.today()
        self.calendar(today + dt.timedelta(days=30), today + dt.timedelta(days=44))
        rc, out = self.prepare()
        self.assertIn("no freeze today; next: line 0.1", out)
        self.assertNotIn("WARNING freeze", out)

    def test_ci_image_failure_is_fatal_and_writes_no_script(self):
        self.sb.stub("make", "echo 'no signed image for this commit'; exit 3\n")
        rc, out = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("make ci-image failed", out)
        self.assertFalse(self.out.exists())

    def test_missing_e2e_version_is_fatal(self):
        self.make_ok(e2e=False)
        rc, out = self.prepare()
        self.assertEqual(rc, 1)
        self.assertIn("no E2E_VERSION", out)
        self.assertFalse(self.out.exists())

    def test_leaves_the_repository_clean(self):
        self.prepare()
        self.assertEqual(self.sb.git("status", "--porcelain").stdout.strip(), "")


# ---------------------------------------------------------------- verify-release.sh
def sha(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


class VerifyRelease(SandboxTest):
    V, NEXT = "0.1.73", "0.1.74"

    def setUp(self):
        super().setUp()
        self.stubs = self.sb.base / "stubs"
        self.tag_commit = "c" * 40
        self.signer = f"https://github.com/{GH}/.github/workflows/release.yml@refs/tags/v{self.V}"
        self.manifests = {}
        self.build_release("manual", "alpha")
        self.install_stubs()
        self.write_post_release_commit()

    # -- fixtures
    def build_release(self, kind, channel):
        arts = {}
        for name in IMAGES:
            repo = f"quay.io/zuno/unifai-{name}"
            arts[f"image {name}"] = (repo, f"manifest of {name}")
        arts["bundle"] = ("quay.io/zuno/unifai-operator-bundle", "manifest of bundle")
        arts["catalog"] = ("quay.io/zuno/unifai-operator-catalog", "manifest of catalog")
        self.manifests = {repo: '{"mediaType":"application/vnd.oci.image.index.v1+json","id":"%s"}' % text
                          for repo, text in arts.values()}
        ref = {k: f"{repo}@{sha(self.manifests[repo])}" for k, (repo, _) in arts.items()}
        self.release = {
            "version": self.V, "commit": self.tag_commit, "signer": self.signer, "issuer": ISSUER,
            "kind": kind, "channel": channel,
            "images": {n: {"ref": ref[f"image {n}"], "tag": f"devel-{n}"} for n in IMAGES},
            "bundle": ref["bundle"], "catalog": ref["catalog"],
        }
        self.op = self.release["images"]["operator"]["ref"]
        self.op_digest = self.op.partition("@")[2]
        self.render = [
            {"schema": "olm.package", "name": "unifai-operator"},
            {"schema": "olm.channel", "name": "alpha", "package": "unifai-operator", "entries": [
                {"name": "unifai-operator.v0.1.72"},
                {"name": f"unifai-operator.v{self.V}", "replaces": "unifai-operator.v0.1.72"}]},
            {"schema": "olm.channel", "name": "stable", "package": "unifai-operator", "entries": [
                {"name": "unifai-operator.v0.1.60", "skipRange": ">=0.1.0 <0.1.60"}]},
        ]
        self.runs = [{"databaseId": 7, "headSha": self.tag_commit, "status": "completed", "conclusion": "success",
                      "createdAt": "2026-11-19T20:00:00Z", "url": "https://github.example/run/7"}]
        self.rel_view = {"isDraft": False, "isPrerelease": False, "publishedAt": "2026-11-19T21:00:00Z"}

    def install_stubs(self):
        s = self.stubs
        write(s / "tagobj", "TAGOBJ")
        write(s / "tagc", self.tag_commit)
        write(s / "runs.json", json.dumps(self.runs))
        write(s / "rel.json", json.dumps(self.rel_view))
        write(s / "release.json", json.dumps(self.release))
        write(s / "render.json", "\n".join(json.dumps(d) for d in self.render))  # a stream, not a list
        for repo, text in self.manifests.items():
            write(s / "manifests" / repo.replace("/", "_"), text)
        self.sb.stub("gh", f'''S="$STUB_DIR"
if [ "$1" = api ]; then
  case "$2" in
    repos/{GH}/git/ref/tags/v*) [ -f "$S/tagobj" ] && echo "tag $(cat "$S/tagobj")" || {{ echo '{{"message":"Not Found"}}'; exit 1; }} ;;
    repos/{GH}/git/tags/*) cat "$S/tagc" ;;
    *) exit 1 ;;
  esac; exit $?
fi
[ "$1" = -R ] && shift 2
case "$1 $2" in
  "run list") cat "$S/runs.json" ;;
  "release view") [ -f "$S/rel.json" ] && cat "$S/rel.json" || exit 1 ;;
  "release download") [ -f "$S/release.json" ] || exit 1
     while [ $# -gt 0 ]; do [ "$1" = -D ] && d="$2"; shift; done; cp "$S/release.json" "$d/release.json" ;;
  *) exit 1 ;;
esac
''')
        self.sb.stub("skopeo", '''ref="${@: -1}"; ref="${ref#docker://}"; repo="${ref%:*}"
f="$STUB_DIR/manifests/${repo//\\//_}"; [ -f "$f" ] && cat "$f" || exit 1
''')
        self.sb.stub("cosign", 'echo "$*" >> "$STUB_DIR/cosign.log"\n'
                               'grep -qxF "${@: -1}" "$STUB_DIR/cosign.fail" 2>/dev/null && exit 1; exit 0\n')
        self.sb.stub("opm", '[ -f "$STUB_DIR/render.json" ] && cat "$STUB_DIR/render.json" || { echo "render failed" >&2; exit 1; }\n')

    def update(self, name, data):
        write(self.stubs / name, data if isinstance(data, str) else json.dumps(data))

    def write_post_release_commit(self, branch="devel", **override):
        files = {
            "fork/unifai-operator/Makefile": f"VERSION ?= {self.NEXT}\n",
            "fork/unifai-operator/config/manager/kustomization.yaml":
                f"images:\n  - name: controller\n    digest: {self.op_digest}\n",
            "fork/unifai-operator/bundle/manifests/unifai-operator.clusterserviceversion.yaml":
                f"metadata:\n  name: unifai-operator.v{self.V}\n  annotations:\n    containerImage: {self.op}\n",
            "fork/unifai-operator/catalog/unifai-operator/catalog.yaml": self.catalog_yaml(),
        }
        files.update(override)
        for path, text in files.items():
            write(self.sb.work / path, text)
        self.sb.git("add", "-A")
        self.sb.git("commit", "-q", "-m", f"release(fork): v{self.V} published, next VERSION {self.NEXT}")
        self.sb.git("push", "-q", "origin", branch)

    def drop_post_release_commit(self):
        self.sb.git("reset", "-q", "--hard", "HEAD~1")
        self.sb.git("push", "-q", "-f", "origin", "devel")  # throwaway origin: forced on purpose

    def catalog_yaml(self, alpha=None, bundle_image=None, related=None):
        alpha = alpha if alpha is not None else self.render[1]["entries"]
        docs = [
            {"schema": "olm.bundle", "name": f"unifai-operator.v{self.V}",
             "image": bundle_image or f"quay.io/zuno/unifai-operator-bundle:v{self.V}",
             "relatedImages": [{"image": related or self.op}]},
            {"schema": "olm.channel", "name": "alpha", "entries": alpha},
        ]
        return "".join("---\n" + json.dumps(d) + "\n" for d in docs)  # JSON is YAML

    def verify(self, digest=None, version=None):
        return self.sb.run("verify-release.sh", version or self.V, digest or self.op_digest)

    # -- tests. A run of the script costs about a second (it starts dozens of processes) and its checks are independent
    # of each other, so the failing cases are grouped: one run with several defects, one FAIL line asserted per defect.
    def update_render(self):
        self.update("render.json", "\n".join(json.dumps(d) for d in self.render))

    def assertFails(self, out, *lines):
        for line in lines:
            self.assertIn("FAIL " + line, out)

    def test_usage_errors_exit_2(self):
        for args in ((), ("0.1", self.op_digest), (self.V, "sha256:abc"), (self.V, self.op_digest[:20]),
                     (self.V, "sha256:" + "A" * 64)):
            rc, out = self.sb.run("verify-release.sh", *args)
            self.assertEqual(rc, 2, (args, out))
            self.assertIn("usage:", out)

    def test_unknown_tag_is_not_published(self):
        (self.stubs / "tagobj").unlink()
        rc, out = self.verify(version="9.9.9")
        self.assertEqual(rc, 1)
        self.assertIn("tag v9.9.9 not found", out)
        self.assertIn("is NOT published", out)

    def test_missing_release_json_fails(self):
        (self.stubs / "release.json").unlink()
        rc, out = self.verify()
        self.assertEqual(rc, 1)
        self.assertIn("release.json not attached", out)

    def test_a_published_release_is_verified(self):
        # a failed run older than the green re-run on the same commit (R-561) must not count
        self.runs.insert(0, {**self.runs[0], "databaseId": 6, "conclusion": "failure", "createdAt": "2026-11-19T10:00:00Z"})
        self.update("runs.json", self.runs)
        rc, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertIn(f"RESULT: v{self.V} verified", out)
        self.assertIn("OK   cosign 8/8", out)
        self.assertIn("OK   skipRange only on stable", out)  # the fixture has one on stable, none on alpha
        self.assertIn("(index)", out)  # the OCI indexes of R-561 are compared by their own raw digest
        self.assertNotIn("FAIL", out)
        self.assertIn(f"operator   {self.op}", out)  # the message for zuno-demo carries the digests
        calls = (self.stubs / "cosign.log").read_text().splitlines()
        self.assertEqual(len(calls), 8)
        for call in calls:
            self.assertIn(f"--certificate-identity {self.signer}", call)
            self.assertIn(f"--certificate-oidc-issuer {ISSUER}", call)
        self.assertEqual(self.sb.git("status", "--porcelain").stdout.strip(), "")  # writes nothing in the repository

    def test_release_run_registry_and_signature_defects(self):
        self.runs[0]["conclusion"] = "failure"
        self.update("runs.json", self.runs)
        self.update("rel.json", {**self.rel_view, "isPrerelease": True})
        self.update("manifests/quay.io_zuno_unifai-rag", "a different manifest")
        (self.stubs / "manifests" / "quay.io_zuno_unifai-ui").unlink()
        self.update("cosign.fail", self.release["images"]["backend"]["ref"] + "\n")
        rc, out = self.verify(digest="sha256:" + "b" * 64)  # not the canaried operator
        self.assertEqual(rc, 1)
        self.assertFails(out, "release.yml run 7", "image-rag: quay.io/zuno/unifai-rag:v0.1.73 is sha256:",
                         "cosign image-backend", "cosign 7/8 (8/8 expected)", "operator")
        self.assertIn("image-ui: quay.io/zuno/unifai-ui:v0.1.73 not readable", out)
        self.assertIn("GitHub release v0.1.73 missing, draft or pre-release", out)
        self.assertIn("NOT verified", out)
        self.assertNotIn("message for zuno-demo", out)

    def test_release_json_defects(self):
        r = json.loads(json.dumps(self.release))
        r.update(version="0.1.99", commit="e" * 40, issuer="https://evil.example",
                 signer="https://github.com/other/repo/.github/workflows/release.yml@refs/tags/v0.1.73")
        r["images"].pop("ui")
        r["images"]["rag"]["ref"] = "docker.io/library/rag@sha256:" + "1" * 64
        self.update("release.json", r)
        rc, out = self.verify()
        self.assertEqual(rc, 1)
        self.assertFails(out, "version 0.1.99", "commit " + "e" * 40, "issuer https://evil.example", "signer https://github.com/other",
                         "6 images:", "7 artefacts, all quay.io/zuno/")

    def test_no_run_on_the_tag_commit_and_post_release_commit_content_defects(self):
        self.runs[0]["headSha"] = "d" * 40
        self.update("runs.json", self.runs)
        self.drop_post_release_commit()
        cat = "fork/unifai-operator/catalog/unifai-operator/catalog.yaml"
        csv = "fork/unifai-operator/bundle/manifests/unifai-operator.clusterserviceversion.yaml"
        self.write_post_release_commit(**{
            "fork/unifai-operator/Makefile": "VERSION ?= 0.1.73\n",
            "fork/unifai-operator/config/manager/kustomization.yaml":
                "images:\n  - name: controller\n    digest: sha256:" + "9" * 64 + "\n",
            csv: "metadata:\n  name: unifai-operator.v0.1.70\n  annotations:\n    containerImage: quay.io/zuno/x@sha256:" + "8" * 64 + "\n",
            cat: self.catalog_yaml(bundle_image="quay.io/zuno/other:v1", related="quay.io/zuno/unifai-operator@sha256:" + "7" * 64,
                                   alpha=[{"name": f"unifai-operator.v{self.V}"},
                                          {"name": "unifai-operator.v0.1.72", "replaces": f"unifai-operator.v{self.V}"}]),
        })
        rc, out = self.verify()
        self.assertEqual(rc, 1)
        self.assertFails(out, "no release.yml run on the tag commit", "Makefile VERSION 0.1.73 (next 0.1.74)",
                         "config/manager/kustomization.yaml digest", "CSV unifai-operator.v0.1.70", "CSV containerImage",
                         f"catalog.yaml: bundle v{self.V}", f"catalog.yaml: bundle v{self.V} relatedImages",
                         f"catalog.yaml: alpha head v{self.V}")

    def test_rendered_catalog_defects(self):
        # alpha: a skipRange, a second head and no v0.1.73; stable: a skips; the repository catalog says otherwise
        self.render[1]["entries"] = [{"name": "unifai-operator.v0.1.72", "skipRange": ">=0.1.0 <0.1.72"},
                                     {"name": "unifai-operator.v0.1.50"}]
        self.render[2]["entries"][0]["skips"] = ["unifai-operator.v0.1.59"]
        self.update_render()
        rc, out = self.verify()
        self.assertEqual(rc, 1)
        self.assertFails(out, f"v{self.V} in channel alpha", "alpha: only name/replaces", "alpha: one replaces chain",
                         "no skips in any channel", "skipRange only on stable", "alpha of the published catalog")

    def test_a_hotfix_is_read_on_its_release_branch_and_in_the_stable_channel(self):
        # the post-release commit of a hotfix lives on release-X.Y (the catalog goes to devel, not checked here)
        self.drop_post_release_commit()  # none on devel: only the branch has it
        self.sb.git("checkout", "-q", "-b", "release-0.1")
        self.write_post_release_commit(branch="release-0.1")
        self.release.update(kind="hotfix", channel="stable")
        self.update("release.json", self.release)
        self.render[2]["entries"].append({"name": f"unifai-operator.v{self.V}", "replaces": "unifai-operator.v0.1.60"})
        self.update_render()
        rc, out = self.verify()
        self.assertEqual(rc, 0, out)
        self.assertIn(f"v{self.V} in channel stable", out)
        self.assertIn("hotfix: the catalog is committed to devel", out)

    def test_post_release_commit_and_opm_render_are_required(self):
        self.drop_post_release_commit()
        (self.stubs / "render.json").unlink()
        rc, out = self.verify()
        self.assertEqual(rc, 1)
        self.assertFails(out, f"no 'release(fork): v{self.V} published, next VERSION {self.NEXT}' on origin/devel", "opm render")



if __name__ == "__main__":
    unittest.main()
