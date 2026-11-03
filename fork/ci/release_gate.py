"""Decide whether the weekly release of the fork runs (fork/RELEASING.md, weekly-release.yml).

The weekly release is skipped when:
- `devel` has no change since the last vX.Y.Z (the bot's "release(fork): v…" post-release commit is not a change);
- the fork workflows of the `devel` head did not pass (failed, or still running after --wait seconds);
- a freeze of fork/calendar.yaml is active and a `feat` commit reached `devel` since the freeze started (only fixes
  are merged during a freeze: a human reverts the feature, the next weekly goes out).

Prints the reason, and writes `release=true|false` and `reason=…` to $GITHUB_OUTPUT when it is set.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
# Fork workflows whose result gates a release (path filters: a workflow with no run on the commit is not a failure).
GATING = (".github/workflows/fork-tests.yml", ".github/workflows/unifai-operator.yml",
          ".github/workflows/publish-images.yml", ".github/workflows/e2e-kind.yml")
FEAT = re.compile(r"^feat(\([^)]*\))?!?:")
RELEASE_COMMIT = re.compile(r"^release\(fork\): v")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def active_freeze(calendar: dict, day: dt.date):
    """The calendar line whose freeze contains `day` (inclusive), or None."""
    for line in calendar.get("lines", []):
        freeze = line.get("freeze") or {}
        start, end = freeze.get("from"), freeze.get("to")
        if start and end and dt.date.fromisoformat(str(start)) <= day <= dt.date.fromisoformat(str(end)):
            return line
    return None


def last_release(rev: str) -> str | None:
    tags = git("tag", "--merged", rev, "--sort=-v:refname", "-l", "v*").split()
    return next((t for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)), None)


def changes_since(tag: str | None, rev: str) -> list[str]:
    """Subjects of the commits a release would ship, without the bot's post-release commits."""
    subjects = git("log", "--format=%s", f"{tag}..{rev}" if tag else rev).splitlines()
    return [s for s in subjects if not RELEASE_COMMIT.match(s)]


def feat_since(start: dt.date, rev: str) -> list[str]:
    """`feat` commits that reached `rev` on its first-parent line since `start` 00:00 Paris (merge time)."""
    since = dt.datetime.combine(start, dt.time(), PARIS).isoformat()
    out = git("log", "--first-parent", f"--since={since}", "--format=%H", rev).split()
    feats = []
    for merged in out:
        # A merge brings its second parent's commits: look at all of them, not only the merge subject.
        parents = git("rev-list", "--parents", "-n", "1", merged).split()[1:]
        span = f"{parents[0]}..{merged}" if len(parents) > 1 else f"{merged}^!" if parents else merged
        feats += [s for s in git("log", "--format=%h %s", span).splitlines() if FEAT.match(s.split(" ", 1)[1])]
    return feats


def ci_state(runs: list[dict]) -> tuple[list[str], list[str]]:
    """(failed, pending) gating workflows, from the Actions runs of one commit (newest attempt of each wins)."""
    latest = {}
    for r in sorted(runs, key=lambda r: (r.get("run_attempt", 1), r.get("created_at", ""))):
        if r.get("path") in GATING and r.get("event") in ("push", "workflow_dispatch"):
            latest[r["path"]] = r
    failed = [f"{r['name']} ({r['conclusion']}) {r.get('html_url', '')}" for r in latest.values()
              if r["status"] == "completed" and r["conclusion"] not in ("success", "skipped", "neutral")]
    pending = [r["name"] for r in latest.values() if r["status"] != "completed"]
    return failed, pending


def fetch_runs(repo: str, sha: str, token: str) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/runs?head_sha={sha}&per_page=100", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["workflow_runs"]


def decide(rev: str, calendar: dict, today: dt.date, runs_of) -> tuple[bool, str]:
    tag = last_release(rev)
    changes = changes_since(tag, rev)
    if not changes:
        return False, f"nothing changed on devel since {tag}"
    line = active_freeze(calendar, today)
    if line:
        feats = feat_since(dt.date.fromisoformat(str(line["freeze"]["from"])), rev)
        if feats:
            return False, (f"freeze of line {line['line']} active and feat commits reached devel since "
                           f"{line['freeze']['from']}: {'; '.join(feats[:10])}. Revert them, or wait for the promotion")
    failed, pending = runs_of()
    if failed:
        return False, "CI of the devel head is not green: " + "; ".join(failed)
    if pending:
        return False, "CI of the devel head still running: " + ", ".join(pending)
    frozen = f", freeze of line {line['line']} (fixes only)" if line else ""
    return True, f"{len(changes)} change(s) since {tag or 'the start'}{frozen}"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--rev", default="HEAD")
    p.add_argument("--calendar", default="fork/calendar.yaml")
    p.add_argument("--date", help="YYYY-MM-DD, default today in Europe/Paris")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "startxfr/UnifAI"))
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for running CI before deciding")
    a = p.parse_args(argv)
    import yaml  # only the CLI needs it

    with open(a.calendar) as f:
        calendar = yaml.safe_load(f)
    today = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(PARIS).date()
    sha = git("rev-parse", a.rev)
    token = os.environ.get("GITHUB_TOKEN", "")

    def runs_of():
        deadline = time.monotonic() + a.wait
        while True:
            failed, pending = ci_state(fetch_runs(a.repo, sha, token))
            if failed or not pending or time.monotonic() >= deadline:
                return failed, pending
            print(f"waiting for {', '.join(pending)}", file=sys.stderr)
            time.sleep(60)

    ok, reason = decide(a.rev, calendar, today, runs_of)
    print(("release: " if ok else "no release: ") + reason)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"release={'true' if ok else 'false'}\nreason={reason.replace(chr(10), ' ')}\n")
    if not ok and os.environ.get("GITHUB_ACTIONS") and not reason.startswith("nothing changed"):
        print(f"::warning::weekly release skipped: {reason}")


if __name__ == "__main__":
    sys.exit(main())
