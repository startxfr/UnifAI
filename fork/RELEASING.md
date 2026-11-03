# Releasing the startxfr/UnifAI fork

The fork has its own release rhythm, independent of upstream and still answering zuno-demo's requests:

| Kind | Rhythm | Version | OLM channel | Gate | Approval |
|---|---|---|---|---|---|
| **Weekly** | every Friday 18:00 Europe/Paris, skipped when `devel` did not change | `0.X.Y` (next patch of the current line) | `alpha` | CI green + e2e on an ephemeral kind cluster | none (automatic) |
| **Manual** | any time, several per week if needed | `0.X.Y` | `alpha` | same as weekly | `quay-release` |
| **Minor** (promotion) | quarterly, see [calendar.yaml](calendar.yaml) | an existing `0.X.N`, promoted as is | `stable` | 2-week feature freeze, ≥ 1 week on demo333, full canary (`canary-e2e-full`) green | `quay-release` |
| **Hotfix** | when needed, on the promoted line only | `0.X.N+1` on `release-0.X` | `stable` | same as weekly | `quay-release` |
| **Major** | yearly, **1.0 on 2027-09-15** | a line `X.0` | as a minor | as a minor | `quay-release` |

## One product version

A tag `vX.Y.Z` versions **everything together**: the operator, its bundle and catalog, and the five application images
(rag, multiagent, backend, identity, ui). Images are **not rebuilt** for a release: the signed `devel-<sha>` digests of
the released commit are copied to `vX.Y.Z` and co-signed with the release identity. What was tested is what ships.

Each release publishes a GitHub release (notes generated from the conventional commits) and a `release.json` listing every
digest and the signing identity, which zuno-demo uses to pin.

## Promoted lines (no version collision)

A line `0.X` receives the weekly and manual releases of its quarter (`0.X.0`, `0.X.1`, …, channel `alpha`). On the promote
date, the last release that ran at least a week on demo333 (e.g. `0.2.12`) is **added to the `stable` channel as is**,
`release-0.2` is created at its tag, and `devel` moves to `0.3.0`. Hotfixes of the promoted line are cherry-picked from
`devel` onto `release-0.2` and published as `0.2.13`, `0.2.14` on `stable` only. Only the latest promoted line is
maintained.

The `stable` entry of a promoted release carries a `skipRange` (`>=0.(X-1).0 <0.X.N`) so a cluster on the previous
stable line upgrades in one step.

## Branches

```
upstream/main ──ff──► main (mirror, never carries fork paths)
                        │ weekly PR main→devel (a human merges it)
                        ▼
feature/* ──merge──► devel ──ff at each release──► stable   [tags v0.X.Y, channel alpha]
                        │
                        └─ promotion: existing tag v0.X.N ──► release-0.X   [hotfixes v0.X.N+1, channel stable]
```

- `main` mirrors `upstream/main` (fast-forward only). Upstream contributions start from it (`make feature-start`).
- `devel` is where we develop (`main` + fork delta). Upstream syncs land here through a PR from `main`.
- `stable` is fast-forwarded to the released `devel` commit at each release and carries the `v*` tags.
- `release-0.X` is created at promotion and carries the hotfix tags of that line.
- The fork-only paths ([fork-only-paths](fork-only-paths)) are allowed on `devel`, `stable` and `release-*`, refused on
  `main` and on contribution branches ([hooks/guard-fork-only](hooks/guard-fork-only)).

## Calendar

[calendar.yaml](calendar.yaml) holds the freeze and promote dates. During a freeze only fixes are merged into `devel`
(no `feat` commits); weekly releases continue with those fixes.

| Line | Weekly releases | Freeze | Promotion to stable |
|---|---|---|---|
| 0.1 | until December 2026 (0.1.52…) | 2026-12-01 → 12-14 | 2026-12-15 |
| 0.2 | December → March | 2027-03-01 → 03-14 | 2027-03-15 |
| 0.3 | March → June | 2027-06-01 → 06-14 | 2027-06-15 |
| 1.0 | June → September | 2027-09-01 → 09-14 | **2027-09-15 (1.0 GA)** |
| 1.1, 1.2, 1.3 then 2.0 | same rhythm | | 2028-09-15 |

## Roles

- **CI bot** (GitHub App): pushes `stable`, the `v*` tags and the post-release commit on `devel` (next `VERSION`,
  rendered catalog).
- **Maintainer**: approves `quay-release` (manual, minor, hotfix), runs the full canary on demo333 before a promotion,
  merges the weekly upstream PR.
- **zuno-demo**: consumes releases from `release.json`; pins and rolls when it decides (no CD from the fork). Its
  feature requests go to [ROADMAP.md](ROADMAP.md) with the target line.

## Cutting a release (phase 1)

`cut-release.yml` (Actions → cut-release → Run workflow, on `devel`) takes a `kind`:

- `rc`: rehearsal `vVERSION-rc.N` into `quay.io/zuno/test-unifai-*` (environment `quay-test`), GitHub pre-release, no
  commit back, `stable` untouched;
- `manual`: `vVERSION`, published after the `quay-release` approval;
- `weekly`: `vVERSION` without approval (environment `quay-weekly`), skipped when `devel` has no change since the last
  release.

It resolves the six signed images of the `devel` head ([ci/release_images.py](ci/release_images.py), also runnable
locally: `python3 fork/ci/release_images.py --version 0.1.52`), fast-forwards `stable` and pushes the annotated tag with
the release bot. The tag starts `release.yml`:

1. it checks the tag (bot, kind, version = Makefile `VERSION`, commit on `stable`), runs the e2e gate on kind on
   those images (`e2e-kind.yml`), and re-resolves them;
2. it tags the six digests `vX.Y.Z` and signs them with `release.yml@refs/tags/vX.Y.Z`;
3. it builds and signs the bundle and the catalog (`alpha` channel only);
4. it publishes the GitHub release with notes ([ci/release_notes.py](ci/release_notes.py)) and `release.json`;
5. the bot commits the release files and the next patch `VERSION` to `devel` (`release(fork): vX.Y.Z published…`).

Requirements before the first run: the settings of the GitHub bot, the environments `release-bot`, `quay-weekly`,
`quay-release`, `quay-test`, the rulesets, `devel` as default branch, the quay robot and test repositories.

**Transition (decided by zuno-demo, 2026-11-03):** demo333 subscribes to `stable` today. At the FIRST unified release,
zuno-demo (da) moves its Subscription to `alpha` (catalog still pinned by digest and signature-verified at each pin) and
makes `image-identities.yaml` accept the release identity too, in a separate commit with its user's go. Until then the
transition flow (`operator-vX.Y.Z`, `make release-files`, alpha and stable) stays the one that reaches demo333. da tests
its pin dry-run on the first `rc` rehearsal.

## Status of the automation

The target workflows (`release.yml`, `weekly-release.yml`, `upstream-sync.yml`, `promote.yml`) are being built in
phases; until they exist, releases follow the operator flow in
[unifai-operator/README.md](unifai-operator/README.md#build-and-release) (`operator-vX.Y.Z` tags).

| Phase | Content | Target |
|---|---|---|
| 0 | this document, calendar, guard hook for `stable`/`release-*`, `stable` branch, GitHub protections and environments | Nov 2026 |
| 1 (coded, inactive until the GitHub settings exist) | `cut-release.yml` + `release.yml`: six digests promoted, bundle/catalog in CI (`alpha` only), notes, `release.json`, bot commit; new signing identity agreed with zuno-demo before the first unified release | Nov 2026 |
| 2 (wired, first green run pending) | e2e on kind in CI (`e2e-kind.yml`, `unifai-operator/hack/kind/e2e.sh`: mock LLM, Route CRD without router, static RWX volumes, service-CA stand-in, restore test skipped), called by `release.yml` before anything is published | Nov–Dec 2026 |
| 3 | `upstream-sync.yml` (Thursday) and `weekly-release.yml` (Friday, skips when nothing changed or during a freeze) | Dec 2026 |
| 4 | `promote.yml` and hotfix releases on `release-0.X`; first promotion of the 0.1 line | 2026-12-15 |
| 5 (optional) | self-hosted runner in demo333 to automate the canary before a promotion; CD only if zuno-demo asks | 2027 |

The signing identity of the operator, bundle and catalog moves from `unifai-operator-release.yml@refs/tags/operator-v…`
to `release.yml@refs/tags/v…`: zuno-demo's `platform/supply-chain/image-identities.yaml` must accept it before the first
unified release (both are accepted during the transition).
