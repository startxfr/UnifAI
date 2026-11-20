---
name: fork-verify-release
description: Verify a published release vX.Y.Z of the startxfr/UnifAI fork, read only, before announcing it to zuno-demo. Use after a cut-release / release.yml run, or when asked "is 0.1.N out", "verify the release", "check release.json", "cosign the release", "send the digests to zuno-demo".
---

# Verifying a fork release (read only)

How a release is made: [fork/docs/releasing.md](../../../fork/docs/releasing.md) ("Cutting a release"),
[.github/workflows/release.yml](../../../.github/workflows/release.yml) (release.json, post-release commit).

## Rule
**Never announce "published", "re-cut" or "re-run" without having seen the run and the tag through the GitHub API**
(`gh -R startxfr/UnifAI …`). A tag can carry a failed run and a green one (v0.1.73, R-561): judge the run on the tag's
commit. If the script says FAIL, report the FAIL lines, not a summary.

## Run
```
.claude/skills/fork-verify-release/scripts/verify-release.sh X.Y.Z sha256:<64 hex>
```
The second argument is the **full** digest of the operator the canary tested (from `make ci-image` / the cut's
`operator` input), never a short one. About 1.5 minutes. Needs `gh` logged in, `skopeo`, `cosign`, `opm`, python3 with
PyYAML. Writes nothing (temporary directory only, `git fetch` of origin).

## What it checks
1. Tag `vX.Y.Z` exists (API), the newest `release.yml` run on the tag's commit is `completed success`, the GitHub
   release is published (not draft, not pre-release), `release.json` is attached.
2. `release.json`: version, commit = tag commit, signer
   `https://github.com/startxfr/UnifAI/.github/workflows/release.yml@refs/tags/vX.Y.Z`, issuer, the six images, bundle
   and catalog (8 artefacts), operator = the canaried digest.
3. Each `quay.io/zuno/…:vX.Y.Z` tag resolves to the release.json digest, compared on the **raw manifest digest**: since
   2026-11-19 the CI images are OCI image indexes (R-561 in [fork/docs/roadmap.md](../../../fork/docs/roadmap.md)), so the digest
   that counts is the index's, not the amd64 image's.
4. `cosign verify` with the release identity passes on all 8.
5. The bot's post-release commit `release(fork): vX.Y.Z published, next VERSION X.Y.Z+1` on `origin/devel`
   (`release-X.Y` for a hotfix): next Makefile `VERSION`, manager kustomization and CSV on the released operator,
   rendered `catalog/` with the bundle and the alpha head.
6. `opm render` of the published catalog: `vX.Y.Z` in its channel, alpha is one `replaces` chain with no `skips` or
   `skipRange`; a `skipRange` may exist only on `stable` (written by promote, [fork/ci/promote.py](../../../fork/ci/promote.py));
   the published alpha channel equals the post-release commit's.

**Hotfix path never tested.** The `kind: hotfix` branches of the script (post-release commit on `release-X.Y`, `vX.Y.Z`
looked up in the `stable` channel, catalog not compared because it is committed to `devel`) were written from
release.yml but have never run against a real hotfix release (none exists yet; tested on v0.1.73, a manual release).
On the first hotfix, read every line of its output, and treat a FAIL there as a possible script bug before a release bug.

## After a green run
- The script prints a message (French, see the `fork-peer-brief` skill) with the operator, bundle, catalog and five
  application digests: send it to `zuno-demo`, with `zuno-demo-cluster` in copy (check `ListAgents` for the names).
- Write "delivered X.Y.Z" in the ROADMAP rows (`fork-roadmap-entry` skill).
- Nothing goes on demo333 without the owner's go in the zuno-demo-cluster session.
