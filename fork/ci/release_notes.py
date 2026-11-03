#!/usr/bin/env python3
"""Release notes of a fork release (fork/RELEASING.md), from the conventional commits since the previous release.

    release_notes.py <version> [<to ref>] [--from <ref>] [--images images.json]

The previous release is the newest `v*` tag (pre-releases excluded), else the newest `operator-v*` tag, reachable from
<to ref> and other than <to ref> itself. Commits are grouped by type; `release` and `chore` commits are left out.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

GROUPS = [
    ("feat", "Features"),
    ("fix", "Fixes"),
    ("perf", "Performance"),
    ("security", "Security"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("ci", "CI"),
    ("build", "Build"),
    ("refactor", "Refactoring"),
]
SKIPPED = {"release", "chore", "style", "revert"}
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?!?: (?P<text>.+)$")
STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
OPERATOR_TAG = re.compile(r"^operator-v\d+\.\d+\.\d+$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def previous_release(to: str) -> str | None:
    head = git("rev-parse", f"{to}^{{commit}}")
    merged = git("tag", "--merged", to, "--sort=-v:refname").split()
    for pattern in (STABLE_TAG, OPERATOR_TAG):
        for t in merged:
            if pattern.match(t) and git("rev-parse", f"{t}^{{commit}}") != head:
                return t
    return None


def render(version: str, subjects: list[str], since: str | None, images: dict | None = None) -> str:
    grouped: dict[str, list[str]] = {k: [] for k, _ in GROUPS}
    other: list[str] = []
    for s in subjects:
        m = SUBJECT.match(s)
        if not m:
            other.append(s)
            continue
        kind = m["type"]
        if kind in SKIPPED:
            continue
        line = f"{m['text']} ({m['scope']})" if m["scope"] else m["text"]
        (grouped[kind] if kind in grouped else other).append(line)
    out = [f"# UnifAI {version}", ""]
    out.append(f"Changes since {since}." if since else "First release of this lifecycle.")
    for kind, title in GROUPS:
        if grouped[kind]:
            out += ["", f"## {title}", ""] + [f"- {x}" for x in grouped[kind]]
    if other:
        out += ["", "## Other", ""] + [f"- {x}" for x in other]
    if images:
        out += ["", "## Images", "", "| Component | Digest |", "|---|---|"]
        out += [f"| {c} | `{v['ref']}` |" for c, v in images.items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("version")
    p.add_argument("to", nargs="?", default="HEAD")
    p.add_argument("--from", dest="since")
    p.add_argument("--images", help="images.json of release_images.py (or release.json)")
    a = p.parse_args(argv)
    since = a.since or previous_release(a.to)
    rng = f"{since}..{a.to}" if since else a.to
    subjects = git("log", "--no-merges", "--format=%s", rng).splitlines()
    images = None
    if a.images:
        with open(a.images) as f:
            images = json.load(f).get("images")
    sys.stdout.write(render(a.version, subjects, since, images))


if __name__ == "__main__":
    main()
