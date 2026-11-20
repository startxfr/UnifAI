#!/usr/bin/env bash
# Push one's own commit(s) to devel from the shared startxfr/UnifAI checkout, and nothing else.
#
#   push-own-sha.sh <sha> <n>          # check only: prints what `git push origin <sha>:devel` would send
#   push-own-sha.sh <sha> <n> --push   # push, after the same checks (3 attempts: SSH is flaky)
#
# <n> is the number of commits you expect to send (origin/devel..<sha>): a mismatch means other sessions' unpushed
# commits sit under yours, and the script refuses. The target is always devel: never main, stable, release-* or upstream.
set -uo pipefail
SHA="${1:?usage: $0 <sha> <expected commit count> [--push]}"; N="${2:?expected commit count}"; DO="${3:-}"
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO" || exit 2
case "$(git remote get-url origin)" in *startxfr/UnifAI*) ;; *) echo "REFUSE: origin is not startxfr/UnifAI" >&2; exit 1 ;; esac

for i in 1 2 3; do git fetch -q origin devel && break; echo "fetch failed (attempt $i), retrying" >&2; sleep $((i * 5)); done
SHA="$(git rev-parse --verify "$SHA^{commit}")" || exit 1
if ! git merge-base --is-ancestor origin/devel "$SHA"; then
  echo "REFUSE: $SHA does not build on origin/devel ($(git rev-parse --short=9 origin/devel)): rebase your own commit onto it"
  exit 1
fi
mapfile -t LIST < <(git log --reverse --format='%h %an: %s' "origin/devel..$SHA")
echo "Would send ${#LIST[@]} commit(s) to devel:"; printf '  %s\n' "${LIST[@]}"
if [ "${#LIST[@]}" != "$N" ]; then
  echo "REFUSE: ${#LIST[@]} commit(s), you expected $N: other sessions' commits are under yours; push only what is yours"
  exit 1
fi

# Same image impact as check-staged.sh, on the whole range.
python3 -I - "$REPO" "$SHA" <<'PY'
import subprocess, sys
repo, sha = sys.argv[1:3]; sys.path.insert(0, f"{repo}/fork/ci")
from release_images import COMPONENTS
files = subprocess.run(["git", "diff", "--name-only", f"origin/devel...{sha}"], capture_output=True, text=True,
                       cwd=repo).stdout.split()
under = lambda f, p: f == p or f.startswith(p + "/")
hit = sorted({c for f in files for c, ps in COMPONENTS.items() if any(under(f, p) for p in ps)})
if "operator" in hit:
    print("WARNING rebuilds the OPERATOR image: new digest; a manual cut needs a canary on it (fork-cut-prep)")
if set(hit) - {"operator"}:
    print("WARNING rebuilds the five application images")
PY
# Friday before the weekly cron ran: a push restarts the CI of the head the gate looks at.
if [ "$(date -u +%u)" = 5 ]; then
  ran="$(gh -R startxfr/UnifAI run list --workflow weekly-release.yml --event schedule --limit 1 --json createdAt \
    --jq '.[0].createdAt' 2> /dev/null)"
  if [[ "$ran" != "$(date -u +%F)"* ]]; then
    echo "WARNING Friday and the weekly cron has not run yet (17:00 UTC, often hours late): this push restarts the CI the"
    echo "        gate waits for (45 min max, then it skips) and, if it gates green, ships these commits without canary"
  fi
fi

if [ "$DO" != --push ]; then echo "check only: add --push to send $(git rev-parse --short=9 "$SHA"):devel"; exit 0; fi
for i in 1 2 3; do
  git push origin "$SHA:refs/heads/devel" && { echo "pushed $(git rev-parse --short=9 "$SHA") to devel"; exit 0; }
  echo "push failed (attempt $i)" >&2; sleep $((i * 10))
  git fetch -q origin devel
  git merge-base --is-ancestor origin/devel "$SHA" || { echo "REFUSE: origin/devel moved meanwhile, rebase first" >&2; exit 1; }
done
exit 1
