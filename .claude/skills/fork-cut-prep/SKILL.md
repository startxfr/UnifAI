---
name: fork-cut-prep
description: Prepare a manual cut of the startxfr/UnifAI fork for the owner, without triggering it - devel head, canaried operator digest, canary command, cut-release inputs, Friday weekly cron and gate, freeze. Use when asked to "prepare the cut", "prepare 0.1.N", "owner actions", "can we release today", "will the weekly go out".
---

# Preparing a cut for the owner

Authoritative: [fork/docs/releasing.md](../../../fork/docs/releasing.md) ("Cutting a release", "Weekly automation"),
[cut-release.yml](../../../.github/workflows/cut-release.yml), [weekly-release.yml](../../../.github/workflows/weekly-release.yml),
[fork/ci/release_gate.py](../../../fork/ci/release_gate.py), [fork/calendar.yaml](../../../fork/calendar.yaml),
the canary targets of [fork/unifai-operator/Makefile](../../../fork/unifai-operator/Makefile).

## Rule
**Claude never triggers cut-release, weekly-release, promote or a canary itself**, and touches no cluster, unless the
owner explicitly asks for that very action. Claude prepares; the owner runs.

## Run
```
.claude/skills/fork-cut-prep/scripts/prepare-cut.sh <scratchpad>/owner-cut-X.Y.Z.sh
```
It fetches `origin/devel`, runs `make ci-image` (Go from `/home/cl/sdk/go1.26.4/bin`), the gate and the calendar, prints
warnings, and writes the owner script (outside the repository). Read its output before handing the script over.

## What to know (and tell the owner)
- **Operator digest.** `make ci-image` prints `devel-<sha> quay.io/zuno/unifai-operator@sha256:… (signed, operator
  VERSION)` and `E2E_VERSION=devel-<sha>` (the five application images). It resolves the **local** head: in this shared
  checkout compare it with `origin/devel`.
- **What rebuilds images** (any change, **a comment included**; source of truth: `COMPONENTS` in
  [fork/ci/release_images.py](../../../fork/ci/release_images.py), which publish-images uses through `--missing`):
  - `.github/workflows/publish-images.yml`: all six images;
  - `fork/unifai-operator/{cmd,api,internal,go.mod,go.sum,Dockerfile,Makefile}` (Makefile `OPERATOR_BUILD_PATHS`): the
    operator, so a new digest and **the canary must be redone**; the bot's post-release `VERSION` bump is one of them;
  - `rag/`, `multi-agent/`, `backend/`, `shared-resources/identity/`, `ui/`, `global_utils/`: the five application
    images together (new `E2E_VERSION`);
  - `fork/ci/**` is in the workflow's `paths:` so it **starts a publish-images run** (which the Friday gate waits for),
    but it is not image content: nothing is rebuilt, the canaried digest stays valid.
- **Canary** (owner, demo333, 45 to 60 min): `E2E_VERSION=devel-<sha> make canary-ci canary-e2e-full canary-delete` in
  `fork/unifai-operator`, then `git checkout fork/unifai-operator/config/canary/kustomization.yaml` (the canary rewrites
  it). Monitoring of the canary: flag `CANARY_MONITORING`, see fork/docs/releasing.md.
- **Cut** (owner, GitHub UI): cut-release on `devel`, `kind` = `manual` (also `weekly`, `rc`; `hotfix` on
  `release-X.Y`), `operator` = the canaried digest. The cut fails if `devel` resolves another operator. A manual
  release waits for the owner's approval of the `quay-release` environment; a weekly has none (`quay-weekly`).
- **Weekly cron**: Friday 17:00 UTC (`0 17 * * 5`), often delayed by hours (2026-11-13: 22:26Z). The gate skips when
  nothing changed since the last `vX.Y.Z` (the bot's `release(fork): v…` commit does not count, a doc or CI commit
  does), when a gating fork workflow of the head failed or still runs after 45 min, or during a freeze when a `feat`
  reached `devel`. **The weekly cuts without canary**: a code change pushed on Friday ships untested by the canary
  unless the manual cut goes first. Local check: `python3 fork/ci/release_gate.py --rev origin/devel`.
- **Freeze**: `fork/calendar.yaml` (next: line 0.1, 2026-12-01 to 12-14, promotion 2026-12-15): fixes only.
- After the release: the `fork-verify-release` skill, with the full canaried digest.
