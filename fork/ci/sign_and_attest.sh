#!/usr/bin/env bash
# Fork-only (fork/fork-only-paths; the whole fork/ directory is). Gives an image digest the proofs
# zuno-demo's platform/supply-chain/verify_unifai_images.py (ADR-0586) requires, under the identity of
# the workflow that runs this script:
#   1. a keyless signature of the digest,
#   2. a SLSA provenance attestation (fork/ci/slsa_provenance.py),
#   3. a signed SBOM artifact tagged sha256-<image digest>.sbom in the same repository. The SBOM is tens
#      of MB, far over what the public Rekor log accepts as an attestation, so it is a separate OCI
#      artifact that is signed (a signature entry is a few hundred bytes).
#
#   sign_and_attest.sh <repo@sha256:...> <component> [<sbom file>]
#
# With an SBOM file, the artifact is published and signed. Without one, the SBOM artifact already in
# the repository (published by publish-images.yml for the operator image) is signed AGAIN, by this
# workflow's identity: a release that only re-tags a digest built on devel must carry the release
# identity, because a production cluster does not accept the development one.
set -euo pipefail

ref="${1:?image reference repo@sha256:...}"
component="${2:?component name for the provenance}"
sbom="${3:-}"
[[ "$ref" =~ ^[^@]+@sha256:[0-9a-f]{64}$ ]] || { echo "not pinned by digest: $ref" >&2; exit 2; }
repo="${ref%@*}"
digest="${ref#*@}"
tag="${digest/:/-}.sbom"
work="$(mktemp -d)"
here="$(cd "$(dirname "$0")" && pwd)"

# Rekor is a public service: retry, with cosign's own output kept.
retry() {
  local n
  for n in 1 2 3 4 5; do
    "$@" && return 0
    echo "attempt $n failed: $1 $2 ..." >&2
    sleep $((n * 20))
  done
  return 1
}

retry cosign sign --yes "$ref"

python3 "$here/slsa_provenance.py" --component "$component" --out "$work/provenance.json"
retry cosign attest --yes --verbose --type slsaprovenance1 --predicate "$work/provenance.json" "$ref"

if [[ -n "$sbom" ]]; then
  ls -l "$sbom"
  sbom_ref="$(cosign upload blob -f "$sbom" --ct application/spdx+json "$repo:$tag" | tail -n 1)"
  [[ "$sbom_ref" == "$repo"@sha256:* ]] || { echo "unexpected upload output: $sbom_ref" >&2; exit 1; }
else
  sbom_digest="$(skopeo inspect --no-tags --format '{{.Digest}}' "docker://$repo:$tag")" ||
    { echo "no SBOM artifact $repo:$tag to sign" >&2; exit 1; }
  sbom_ref="$repo@$sbom_digest"
fi
retry cosign sign --yes "$sbom_ref"
echo "$component: $ref signed, provenance attested, SBOM artifact $sbom_ref signed"
