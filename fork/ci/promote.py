"""Plan the promotion of a release vX.Y.N to the OLM `stable` channel (fork/RELEASING.md, promote.yml).

Checks that vX.Y.N is a published release of line X.Y (a weekly or manual tag cut by the release bot, at least
--min-days old), that the line is in fork/calendar.yaml and its freeze has started, and that the maintainer confirmed
the full canary on demo333 (with --rehearsal, the age, freeze and canary checks only warn: a dry run of the
promotion on throwaway branches, fork/RELEASING.md). Then works out:
- skip_range: ">=<previous line>.0 <X.Y.N", so OLM upgrades a stable install straight to it;
- next_devel: "<next line>.0", the VERSION devel moves to;
- hotfix: the first patch of X.Y after every existing vX.Y.* tag, the VERSION release-X.Y starts with.

    promote.py --version 0.1.60 --canary [--rehearsal] [--date 2026-12-15] [--out plan.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

RELEASE = re.compile(r"(?:operator-)?v(\d+)\.(\d+)\.(\d+)")  # the transition tags count too
BOT = "unifai-release-bot[bot]"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def tag_info(version: str) -> dict | None:
    """Tagger, date and kind of the annotated tag vVERSION, or None."""
    out = git("for-each-ref", f"refs/tags/v{version}",
              "--format=%(objecttype)%00%(taggername)%00%(taggerdate:iso-strict)%00%(contents:subject)")
    if not out:
        return None
    kind_type, tagger, date, subject = out.split("\0")
    return {"type": kind_type, "tagger": tagger, "date": date, "kind": subject.removeprefix("kind: ").strip()}


def plan(version: str, calendar: dict, tag: dict | None, tags: list[str], today: dt.date, canary: bool,
         min_days: int = 7, rehearsal: bool = False) -> dict:
    errors = []
    soft = []  # the checks a rehearsal may run before their time: errors of a real promotion, warnings of a rehearsal
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        return {"errors": [f"{version} is not X.Y.Z"]}
    line = f"{m[1]}.{m[2]}"
    lines = calendar.get("lines", [])
    index = next((i for i, entry in enumerate(lines) if str(entry["line"]) == line), None)
    if index is None:
        return {"errors": [f"line {line} is not in fork/calendar.yaml"]}
    entry = lines[index]
    if tag is None:
        errors.append(f"v{version} does not exist")
    else:
        if tag["type"] != "tag" or tag["tagger"] != BOT:
            errors.append(f"v{version} is not an annotated tag of the release bot ({tag['tagger']})")
        if tag["kind"] not in ("weekly", "manual"):
            errors.append(f"v{version} is a {tag['kind'] or 'unknown'} release, not a weekly or manual one")
        else:
            age = (today - dt.datetime.fromisoformat(tag["date"]).date()).days
            if age < min_days:
                soft.append(f"v{version} is {age} day(s) old: it must run {min_days} days on alpha first")
    freeze = dt.date.fromisoformat(str(entry["freeze"]["from"]))
    if today < freeze:
        soft.append(f"line {line} is promoted after its freeze, which starts on {freeze}")
    if not canary:
        soft.append("the full canary (canary-e2e-full on demo333) is not confirmed green on this version")
    patches = sorted(int(t[3]) for t in (RELEASE.fullmatch(x) for x in tags) if t and f"{t[1]}.{t[2]}" == line)
    newer = [f"v{line}.{p}" for p in patches if p > int(m[3])]
    lower = f"{lines[index - 1]['line']}.0" if index > 0 else f"{line}.0"
    nxt = f"{lines[index + 1]['line']}.0" if index + 1 < len(lines) else None
    if nxt is None:
        errors.append(f"no line after {line} in fork/calendar.yaml: add the next one first")
    if not rehearsal:
        errors += soft
    return {
        "errors": errors,
        "warnings": soft if rehearsal else [],
        "version": version,
        "line": line,
        "skip_range": f">={lower} <{version}",
        "next_devel": nxt,
        "hotfix": f"{line}.{(patches[-1] if patches else int(m[3])) + 1}",
        "newer": newer,
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--version", required=True)
    p.add_argument("--canary", action="store_true", help="the maintainer ran canary-e2e-full green on this version")
    p.add_argument("--calendar", default="fork/calendar.yaml")
    p.add_argument("--date", help="YYYY-MM-DD, default today")
    p.add_argument("--min-days", type=int, default=7)
    p.add_argument("--rehearsal", action="store_true", help="age, freeze and canary checks only warn")
    p.add_argument("--out")
    a = p.parse_args(argv)
    import yaml

    with open(a.calendar) as f:
        calendar = yaml.safe_load(f)
    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    version = a.version.removeprefix("v")
    tags = git("tag", "-l", "v*", "operator-v*").split()
    result = plan(version, calendar, tag_info(version), tags, today, a.canary, a.min_days, a.rehearsal)
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(text)
    if result["errors"]:
        if os.environ.get("GITHUB_ACTIONS"):
            for e in result["errors"]:
                print(f"::error::{e}", file=sys.stderr)
        raise SystemExit(1)
    if os.environ.get("GITHUB_ACTIONS"):
        for w in result.get("warnings", []):
            print(f"::warning::rehearsal: {w}")
    if result.get("newer") and os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning::newer releases of line {result['line']} exist and stay on alpha only: "
              f"{', '.join(result['newer'])}")


if __name__ == "__main__":
    sys.exit(main())
