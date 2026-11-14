#!/usr/bin/env bash
# Copies the frozen Zuno OKF profile schemas (platform/okf/schema/zuno-okf-profile-*.schema.json) of zuno-demo-agents
# into internal/okf/schema, where they are embedded in the operator, and writes internal/okf/schema/SOURCE: the agents
# commit and the sha256 of every embedded schema. internal/okf/schema_sync_test.go fails when an embedded schema differs
# from SOURCE (zuno-demo ADR-0615 clause 7).
#
#   hack/sync-okf-schemas.sh <dir>   a zuno-demo-agents checkout: the files committed at its HEAD
#   hack/sync-okf-schemas.sh <ref>   a tag, branch or commit of $AGENTS_REPO, a local clone or a git URL
#                                    (default https://github.com/startxfr/zuno-demo-agents.git)
#
# Files are read from the commit, never from a working tree, so SOURCE always names the commit that holds them. They
# are checked against the SHA256SUMS the agents repository commits next to them before anything is copied.
# The legacy v0.2 and v0.3 schemas are not synchronized: they are frozen until the operator stops reading legacy
# documents (WP-268), and the legacy section of SOURCE is kept as it is. Run from anywhere; then `go test ./internal/okf/`.
set -euo pipefail
cd "$(dirname "$0")/.."
src=${1:?usage: hack/sync-okf-schemas.sh <zuno-demo-agents-dir-or-git-ref>}
dst=internal/okf/schema
from=platform/okf/schema
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -d "$src" ]; then
  repo=$src
  ref=HEAD
else
  repo=${AGENTS_REPO:-https://github.com/startxfr/zuno-demo-agents.git}
  ref=$src
fi
label=$repo
if [ ! -d "$repo" ]; then
  git clone --quiet --bare --filter=blob:none "$repo" "$work/agents.git"
  repo=$work/agents.git
fi
commit=$(git -C "$repo" rev-parse --verify --quiet "$ref^{commit}") || {
  echo "error: $ref is not a commit of $label" >&2
  exit 1
}
describe=$(git -C "$repo" describe --tags --always "$commit")

mapfile -t files < <(git -C "$repo" ls-tree --name-only "$commit" "$from/" | sed -n 's|^.*/\(zuno-okf-profile-[^/]*\.schema\.json\)$|\1|p')
if [ "${#files[@]}" -eq 0 ]; then
  echo "error: no zuno-okf-profile-*.schema.json under $from at $commit" >&2
  exit 1
fi
mkdir "$work/schema"
for f in "${files[@]}"; do
  git -C "$repo" show "$commit:$from/$f" >"$work/schema/$f"
done
git -C "$repo" show "$commit:$from/SHA256SUMS" >"$work/SHA256SUMS" || {
  echo "error: $from/SHA256SUMS is missing at $commit" >&2
  exit 1
}
for f in "${files[@]}"; do
  if ! grep -qE "^[0-9a-f]{64}  $f\$" "$work/SHA256SUMS"; then
    echo "error: $f is not listed in $from/SHA256SUMS at $commit" >&2
    exit 1
  fi
done
(cd "$work/schema" && sha256sum --check --quiet --strict ../SHA256SUMS) || {
  echo "error: the profile schemas at $commit do not match its SHA256SUMS" >&2
  exit 1
}

# The legacy section is kept from the existing SOURCE; the first run writes it from the files embedded today.
if [ -f "$dst/SOURCE" ] && grep -q '^# Legacy schemas' "$dst/SOURCE"; then
  sed -n '/^# Legacy schemas/,$p' "$dst/SOURCE" >"$work/legacy"
else
  {
    cat <<'EOF'
# Legacy schemas (okf_version v0.2 and v0.3, no zuno.profile). Not synchronized: frozen as the operator embedded
# them before profile 1.0. The weekly operator release of 2026-11-27 refuses legacy documents and deletes them with
# this section (zuno-demo ADR-0615 clause 13, WP-268). Known differences from the same files in zuno-demo-agents,
# all intentional:
# - zuno-okf-v0.2.schema.json: zuno.status also accepts deprecated and retired. The operator serves both states
#   (zuno-demo ADR-0584); the agents repository keeps v0.2 at active and placeholder.
# - zuno-okf-v0.3.schema.json, zuno-okf-task-v0.3.schema.json: the description of zuno.limits.max_tokens_per_turn
#   is worded for this operator (R-543). The constraint itself is the same.
EOF
    (cd "$dst" && for f in zuno-okf-*.schema.json; do [[ $f == zuno-okf-profile-* ]] || sha256sum "$f"; done)
  } >"$work/legacy"
fi

rm -f "$dst"/zuno-okf-profile-*.schema.json
for f in "${files[@]}"; do
  install -m 0644 "$work/schema/$f" "$dst/$f"
done
{
  cat <<EOF
# Embedded OKF schemas of unifai-operator (internal/okf/schema). Written by hack/sync-okf-schemas.sh: do not edit
# the profile section by hand. internal/okf/schema_sync_test.go checks every line "<sha256>  <file>" below against
# the embedded file, and that every embedded schema is listed.
agents-repository: https://github.com/startxfr/zuno-demo-agents
agents-commit: $commit
agents-describe: $describe

# Profile schemas: copies of platform/okf/schema/ at agents-commit, checked against its SHA256SUMS. A profile is
# frozen (zuno-demo ADR-0615 clause 7): a change upstream is a new profile version, synchronized by this script.
EOF
  (cd "$dst" && sha256sum "${files[@]}")
  echo
  cat "$work/legacy"
} >"$dst/SOURCE"
echo "synchronized ${#files[@]} profile schemas from zuno-demo-agents $describe ($commit) into $dst"
