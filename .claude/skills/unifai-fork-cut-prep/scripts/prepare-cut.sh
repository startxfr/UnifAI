#!/usr/bin/env bash
# Prepare a manual cut of the startxfr/UnifAI fork for the owner (fork/docs/releasing.md "Cutting a release").
#
#   prepare-cut.sh OUT_FILE
#
# Reads the devel head, resolves the CI operator image (`make ci-image`), the gate (fork/ci/release_gate.py) and the
# calendar, then writes OUT_FILE: a script of numbered steps the OWNER runs one by one. It triggers nothing, touches no
# cluster and pushes nothing. Its only writes: `git fetch`, fork/unifai-operator/bin/ci-image.ref (git-ignored), OUT_FILE.
set -uo pipefail

OUT="${1:?usage: $0 OUT_FILE (e.g. the scratchpad; never inside the repository)}"
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
OPDIR="$REPO/fork/unifai-operator"
GO_BIN=/home/cl/sdk/go1.26.4/bin
export PATH="$GO_BIN:$PATH"
cd "$REPO" || exit 2
case "$(realpath -m "$OUT")" in "$REPO"/*) echo "write OUT_FILE outside the repository" >&2; exit 2 ;; esac

warn=()
git fetch -q origin devel --tags || { echo "git fetch failed (SSH is flaky: retry)" >&2; exit 1; }
HEAD_SHA="$(git rev-parse HEAD)"; DEVEL="$(git rev-parse origin/devel)"
DEVEL_S="$(git rev-parse --short=9 "$DEVEL")"
echo "devel head (origin): $(git log -1 --format='%h %s' "$DEVEL")"
if [ "$HEAD_SHA" != "$DEVEL" ]; then
  warn+=("the local checkout is at $(git rev-parse --short=9 HEAD), not origin/devel $DEVEL_S: make ci-image resolves the LOCAL head")
fi

VERSION="$(sed -n 's/^VERSION ?= //p' "$OPDIR/Makefile")"
LAST="$(git tag --merged "$DEVEL" --sort=-v:refname -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1)"
read -r -a BUILD <<< "$(sed -n 's/^OPERATOR_BUILD_PATHS := //p' "$OPDIR/Makefile")"
BUILD_FULL=("${BUILD[@]/#/fork/unifai-operator/}")
OP_CHANGED="$(git log --format='%h %s' "$LAST..$DEVEL" -- "${BUILD_FULL[@]}")"
echo "VERSION $VERSION, last release $LAST"
echo "operator build paths (Makefile OPERATOR_BUILD_PATHS): ${BUILD[*]}"
echo "commits since $LAST that change the operator image:"; echo "${OP_CHANGED:-  none}" | sed 's/^/  /'
if [ -n "$(git diff --name-only "$DEVEL" HEAD -- "${BUILD_FULL[@]}")" ]; then
  warn+=("local head and origin/devel differ under the operator build paths: the digest below is NOT origin/devel's")
fi

echo "== make ci-image"
CI_OUT="$(make -s -C "$OPDIR" ci-image 2>&1)"; rc=$?
echo "$CI_OUT"
[ $rc -eq 0 ] || { echo "make ci-image failed: no cut to prepare (push, then wait for publish-images)" >&2; exit 1; }
OP_REF="$(cat "$OPDIR/bin/ci-image.ref")"; OPERATOR="${OP_REF#*@}"
OP_TAG="$(sed -n 's/^\(devel-[0-9a-f]*\) .*/\1/p' <<< "$CI_OUT" | head -n1)"
E2E_TAG="$(sed -n 's/.*E2E_VERSION=\(devel-[0-9a-f]*\).*/\1/p' <<< "$CI_OUT")"
[ -n "$E2E_TAG" ] || { echo "no E2E_VERSION in the make ci-image output" >&2; exit 1; }

echo "== gate and calendar (what the Friday cron would decide now)"
GATE="$(python3 fork/ci/release_gate.py --rev "$DEVEL" 2>&1)"; echo "$GATE"
FREEZE="$(python3 - <<'PY'
import datetime as dt, sys, yaml
sys.path.insert(0, "fork/ci")
from release_gate import active_freeze, PARIS
cal = yaml.safe_load(open("fork/calendar.yaml")) or {}; today = dt.datetime.now(PARIS).date()
line = active_freeze(cal, today)
# Empty calendar, or every freeze in the past (after the last line): no next freeze, not a crash.
future = [l for l in cal.get("lines") or [] if (l.get("freeze") or {}).get("from")
          and dt.date.fromisoformat(str(l["freeze"]["from"])) > today]
nxt = min(future, key=lambda l: str(l["freeze"]["from"]), default=None)
if line:
    print(f"freeze ACTIVE for line {line['line']} until {line['freeze']['to']}: fixes only, no feat")
elif nxt:
    print(f"no freeze today; next: line {nxt['line']} from {nxt['freeze']['from']} (promote {nxt.get('promote', '?')})")
else:
    print("no freeze today; no later freeze in fork/calendar.yaml")
PY
)"; echo "$FREEZE"
[[ "$FREEZE" == *ACTIVE* ]] && warn+=("$FREEZE")
NOW_UTC="$(date -u +'%a %H:%M')"
[ "$(date -u +%u)" = 5 ] && warn+=("today is Friday ($NOW_UTC UTC): the weekly cron (17:00 UTC, often hours late) cuts the devel head WITHOUT canary if the gate passes; cut manually before it, or accept the weekly")

{
cat <<EOF
#!/usr/bin/env bash
# Owner actions for the cut of v$VERSION of the UnifAI fork (prepared $(date -u +'%Y-%m-%d %H:%MZ') by prepare-cut.sh).
# Run the steps one at a time: \$0 1, \$0 2, ... Nothing here pushes or cuts unless you type it; [UI] = in GitHub.
# Reference: fork/docs/releasing.md ("Cutting a release"), .github/workflows/cut-release.yml.
set -uo pipefail
REPO=$REPO
OPERATOR=$OPERATOR   # $OP_TAG, operator $VERSION
E2E_TAG=$E2E_TAG     # tag of the five application images for the canary
DEVEL_AT_PREP=$DEVEL_S
export PATH=$GO_BIN:\$PATH

case "\${1:-help}" in
1) # BEFORE THE CANARY: right cluster (demo333), healthy, no leftover
  oc whoami --show-server
  oc get csv -n openshift-operators | grep unifai-operator     # expected: the current release, Succeeded
  oc get nodes                                                   # expected: all Ready
  oc get ns | grep -E 'unifai-e2e|unifai-operator-canary' || echo "OK: no leftover namespace"
  echo "Tell zuno-demo-cluster: no stress campaign, agent check or rehearsal for ~60 min."
  ;;
2) # CANARY (45 to 60 min), in the fork checkout, devel up to date
  # Shared checkout: no pull (it may carry other sessions' local commits); make ci-image resolves the local head.
  cd "\$REPO" && git fetch -q origin devel
  git log -1 --format='origin/devel: %h %s (at preparation: '"\$DEVEL_AT_PREP"')' origin/devel
  git log -1 --format='local head:   %h %s' HEAD
  cd fork/unifai-operator && make ci-image
  echo ">>> expected: \$OPERATOR and E2E_VERSION=\$E2E_TAG; if either differs, STOP and tell unifai-main."
  read -r -p "Start the canary? (yes/no) " r; [ "\$r" = yes ] || exit 0
  E2E_VERSION=\$E2E_TAG make canary-ci canary-e2e-full canary-delete   # CANARY_MONITORING=on by default (fork/docs/releasing.md)
  rc=\$?
  cd "\$REPO" && git checkout fork/unifai-operator/config/canary/kustomization.yaml   # the canary rewrites it
  [ \$rc -eq 0 ] && echo "CANARY GREEN" || echo "CANARY RED (code \$rc): tell unifai-main before 17:00 UTC Friday (weekly cron)"
  ;;
3) # CUT [UI], only if the canary is green
  cat <<EOT
GitHub, startxfr/UnifAI, Actions, cut-release, Run workflow, branch devel:
   kind     = manual
   operator = \$OPERATOR
Then approve the environment quay-release on the release.yml run of tag v$VERSION.
The cut fails if devel resolves another operator (a commit under the operator build paths landed since): tell unifai-main.
Then tell unifai-main "v$VERSION cut": it verifies (unifai-fork-verify-release) and sends the digests to zuno-demo.
EOT
  ;;
4) # AFTER THE RELEASE: nothing to run here
  echo "Wait for unifai-main's verified digests, then give your go in the zuno-demo-cluster session for the pin."
  ;;
*) sed -n '2,4p' "\$0"; echo "usage: \$0 {1|2|3|4}" ;;
esac
EOF
} > "$OUT"
chmod +x "$OUT"

echo
echo "== summary"
echo "cut v$VERSION from devel $DEVEL_S: operator $OPERATOR ($OP_TAG), E2E_VERSION=$E2E_TAG"
for w in "${warn[@]}"; do echo "WARNING $w"; done
echo "owner script: $OUT"
