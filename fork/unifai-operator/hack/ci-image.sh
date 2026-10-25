#!/usr/bin/env bash
# Resolves the operator image the CI (publish-images.yml) built and signed for the operator code of HEAD, checks its
# signature and VERSION, and writes its digest reference to bin/ci-image.ref (used by canary-ci and release-files).
#
# The CI tags only the head of each push to devel (devel-<sha>), so the image is not necessarily the one of the commit
# that changed the operator: this walks HEAD's first-parent history back to the newest commit that has an image and
# the same operator code as HEAD (no change under the build paths in between).
#
#   hack/ci-image.sh <image repo> <version> <signer identity> <oidc issuer> <build path>...
set -euo pipefail

repo="$1" version="$2" signer="$3" issuer="$4"
shift 4
paths=("$@")

if [ -n "$(git status --porcelain -- "${paths[@]}")" ]; then
  echo "uncommitted changes in ${paths[*]}: commit and push them, then wait for publish-images" >&2
  exit 1
fi
tags=" $(skopeo list-tags "docker://$repo" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)["Tags"]))') "

found=""
for c in $(git rev-list --first-parent -n 200 HEAD); do
  if ! git diff --quiet "$c" HEAD -- "${paths[@]}"; then
    break # older commits build other operator code
  fi
  sha="$(git rev-parse --short=9 "$c")"
  if [[ "$tags" == *" devel-$sha "* ]]; then
    found="$sha"
    break
  fi
done
if [ -z "$found" ]; then
  echo "no $repo:devel-<sha> for the operator code of HEAD: push it to devel and wait for publish-images" >&2
  exit 1
fi

digest="$(skopeo inspect --no-tags --format '{{.Digest}}' "docker://$repo:devel-$found")"
img="$repo@$digest"
if ! cosign verify --certificate-identity "$signer" --certificate-oidc-issuer "$issuer" "$img" > /dev/null 2>&1; then
  echo "$img (devel-$found): signature not verified for $signer" >&2
  exit 1
fi
built="$(skopeo inspect --no-tags --format '{{index .Labels "version"}}' "docker://$img")"
if [ "$built" != "$version" ]; then
  echo "$img (devel-$found) is operator $built, the Makefile says $version" >&2
  exit 1
fi
mkdir -p bin
echo "$img" > bin/ci-image.ref
echo "devel-$found $img (signed, operator $built)"
