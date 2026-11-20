---
name: fork-promote-rehearsal
description: Dry run (rehearsal) of the promotion of a release line to the OLM stable channel, and its read-only verification (R-526). Use for "promote rehearsal", "essai à blanc", "rehearsal-r526", release-0.1-rehearsal, v0.X.Y-rc.1 checks, opm render of the test catalog, cosign check of an rc, or the line promotion of 2026-12-15.
---

# fork-promote-rehearsal

Source of truth: `fork/docs/releasing.md` (section Rehearsal), `.github/workflows/promote.yml`, `fork/ci/promote.py`,
`fork/calendar.yaml`, and the plan note `/home/cl/.local/share/unifai-main-keep/rehearsal-r526-2.md` (outside the repo,
read it, it may be newer than this skill). The result goes in the R-526 row of `fork/docs/roadmap.md`.

## Hard rules

- Claude NEVER dispatches `promote` (nor `cut-release`, nor approves `quay-release`). The owner does. No canary, no cluster.
- Claude's part is read-only, after the owner's runs. Nothing is committed back to `devel` by the rehearsal.
- Do not dispatch between the cut of the version rehearsed and its verification (concurrency group `release`).
- Rehearsal branches `promote-rehearsal-X.Y` and `release-X.Y-rehearsal` are deleted by a GitHub admin, not by Claude.
- Calendar (`fork/calendar.yaml`, check it again): line 0.1 freeze 2026-12-01 to 2026-12-14, real promotion 2026-12-15.
  A rehearsal belongs before the freeze.

## 1. Local pre-check (allowed, read-only)

```bash
python3 fork/ci/promote.py --version X.Y.Z --rehearsal --out "$SCRATCH/plan.json"
```

Expect 0 errors; with `--rehearsal` the age, freeze and canary checks only warn (3 warnings expected before the freeze).
Note the plan: `skip_range`, `next_devel`, `hotfix` (the first free patch of the line, e.g. 0.1.73 gives 0.1.74).
The tag must be an annotated tag of the release bot with kind weekly or manual, and the version must already carry the
rehearsal workflows (v0.1.59 and later).

## 2. What the owner does

1. Actions, promote, Run workflow on `devel`: `version` = X.Y.Z, tick `rehearsal` (`canary` optional); approve `quay-release`.
2. When publish-images is green on `release-X.Y-rehearsal`: Actions, cut-release on that branch, `kind` = `rc`.
   The tag `vX.Y.(Z+1)-rc.1` has kind `rc-hotfix`; release.yml publishes to `quay.io/zuno/test-unifai-*` on `stable`,
   as a pre-release.
3. An admin deletes the two rehearsal branches afterwards.

## 3. What Claude checks afterwards (read-only)

Let N = Z+1 (the hotfix version). Tooling: `opm`, `cosign`, `skopeo`, `gh` (read commands only).

- Catalog: `opm render` of the test catalog image; take its name and digest from `release.json` of the pre-release. On channel
  `stable`, `vX.Y.N` replaces `vX.Y.Z`, and the entry of the previous version carries the expected `skipRange`
  (e.g. `>=0.1.0 <0.1.73`).
- Signatures: `cosign verify` of the 8 artifacts against identity
  `https://github.com/startxfr/UnifAI/.github/workflows/release.yml@refs/tags/vX.Y.N-rc.1` (list from `release.json`).
- `release.json` of the GitHub pre-release matches the digests.
- Nothing committed back: `git fetch origin devel && git log origin/devel` shows no promotion commit.
- Never print or write a registry credential.

## 4. Report

Write the outcome (date, versions, cosign x/8, opm result, hotfix, anything surprising) in the R-526 row of
`fork/docs/roadmap.md`, in the same terse style, as an explicit-path commit only when the owner asks.
