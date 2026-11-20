#!/usr/bin/env bash
# Review what is staged before a commit in the shared startxfr/UnifAI checkout. Read only.
#
#   check-staged.sh
#
# Refuses (exit 1) when the branch is not devel or nothing is staged. Prints: the staged files, the images each one
# rebuilds (fork/ci/release_images.py COMPONENTS, what publish-images builds), whether it starts a publish-images run,
# new files that fork/fork-only-paths does not cover, and the other sessions' changes left unstaged.
set -uo pipefail
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO" || exit 2

branch="$(git branch --show-current)"
if [ "$branch" != devel ]; then
  echo "REFUSE: on '$branch'. Commits go to devel only; main, stable, release-* need the owner's go (fork/docs/releasing.md)."
  exit 1
fi
if git diff --cached --quiet; then echo "REFUSE: nothing staged (git add <explicit paths>)"; exit 1; fi

python3 -I - "$REPO" <<'PY'
import fnmatch, subprocess, sys
repo = sys.argv[1]; sys.path.insert(0, f"{repo}/fork/ci")
from release_images import COMPONENTS  # the content paths publish-images builds from
def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True, cwd=repo).stdout
staged = [l.split("\t") for l in git("diff", "--cached", "--name-status", "--no-renames").splitlines()]
fork_only = [p.rstrip("/") for p in git("show", "devel:fork/fork-only-paths").split() if p]
# publish-images.yml `paths:` (a push touching them starts a run, even when it rebuilds nothing)
triggers = []
for l in git("show", "HEAD:.github/workflows/publish-images.yml").split("paths:", 1)[1].splitlines()[1:]:
    if not l.strip().startswith("- "):
        break
    triggers.append(l.strip()[2:])
under = lambda f, p: f == p or f.startswith(p + "/")
print("Staged:")
rebuild, trig, new_uncovered = set(), False, []
for st, f in staged:
    imgs = sorted(c for c, paths in COMPONENTS.items() if any(under(f, p) for p in paths))
    t = any(fnmatch.fnmatch(f, g) or (g.endswith("/**") and under(f, g[:-3])) for g in triggers)
    fo = any(under(f, p) for p in fork_only)
    rebuild |= set(imgs); trig |= t
    tags = (["rebuilds " + ",".join(imgs)] if imgs else []) + (["starts publish-images"] if t and not imgs else []) \
        + (["fork-only"] if fo else [])
    print(f"  {st} {f}" + (f"   [{'; '.join(tags)}]" if tags else ""))
    if st == "A" and not fo:
        new_uncovered.append(f)
if "operator" in rebuild:
    print("WARNING rebuilds the OPERATOR image (a comment counts): new digest, the canary must be redone before a manual cut")
if rebuild - {"operator"}:
    print("WARNING rebuilds the five application images: new E2E_VERSION for the canary")
if trig and not rebuild:
    print("NOTE starts a publish-images run that rebuilds nothing (fork/ci/** is not image content); the Friday gate waits for it")
for f in new_uncovered:
    print(f"QUESTION new file not covered by fork/fork-only-paths: {f} -- fork-only? then add its path there (same commit)")
others = [l for l in git("status", "--porcelain").splitlines() if l[1] != " " or l.startswith("??")]
if others:
    print(f"NOTE {len(others)} unstaged or untracked path(s) left out (other sessions' work?): never git add -A or .")
PY
