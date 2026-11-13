# Fork tooling

Fork-only files (never part of an upstream PR): `Makefile`, `fork.mk` (local, git-ignored), `fork.mk.example`, `fork/`.

- `make help` lists every target. `make init` sets up the `upstream` remote and **disables pushes** to `origin`/`upstream`
  (`git config --unset remote.origin.pushurl` when you want to publish).
- Branches: `main` mirrors `upstream/main` (ff-only); `devel` = `main` + fork delta; features start from `main`
  (`make feature-start`), are merged into `devel` to test (`make feature-to-devel`) and can then go upstream (`make contrib-*`).
- Deployment: `make overlay` copies `helm/` to `.fork/helm/` and deep-merges `fork/values/<file>.yaml` over `helm/values/<file>.yaml`
  (placeholders in braces are read from `fork.mk`); image repositories/tags come from `fork/images.yaml`. Upstream files stay untouched.
- Known gaps: `helmfile` is not validated here (not installed when written); `make helm-lint` reports upstream chart issues
  (`multiagent/be` template without extension, `rabbitmq` missing `common` dependency).

## Guard rails for main
`main` mirrors upstream, so fork-only paths (`fork/fork-only-paths`) must never reach it. `make init` installs
`fork/hooks/guard-fork-only` as pre-commit and pre-merge-commit hook: it refuses these paths on every branch except
`devel`, `stable` and `release-*` (the release branches, see [RELEASING.md](RELEASING.md)).

## Signed images (CI)

`.github/workflows/publish-images.yml` builds the five application images with the Makefile's Dockerfiles, pushes them to
`quay.io/zuno/unifai-<component>` and signs each digest keyless with the workflow's GitHub OIDC identity, with a SLSA provenance
(`fork/ci/slsa_provenance.py`) attached as an attestation. The SPDX SBOM (tens of MB, far over what the public Rekor log
accepts) is pushed as its own OCI artifact tagged `sha256-<image digest>.sbom` and signed with the same identity. zuno-demo
verifies all of it before deploying
(zuno-demo ADR-0586, WP-176).

- A push to `devel` that touches an image's code publishes `devel-<sha>` and `devel` (environment `quay-devel`, no approval,
  restricted to the `devel` branch). Releases are not built: `release.yml` (tag `vX.Y.Z` cut by `cut-release.yml`, see
  [RELEASING.md](RELEASING.md)) tags those signed digests `vX.Y.Z` and signs them with its own identity.
- A push builds only the images whose code has no `devel-<sha>` image yet (`fork/ci/release_images.py --missing`):
  the five application images together, the operator image when its code or Makefile changed, everything when
  `publish-images.yml` itself changed. Comparing with the images rather than with the previous push also builds a
  change whose own run was cancelled or replaced in the queue. A manual run builds everything, or the `components`
  input (e.g. `rag,operator`).
- `.github/workflows/fork-tests.yml` runs, without a cluster, the guarded MCP and A2A clients against real local
  servers (`multi-agent/tests/integration/external_servers`), the outbound guard unit tests, the `fork/ci` tests and
  the unit tests of multi-agent, rag and identity (`fork/ci/run_unit_tests.py`). Those skip only the tests that
  already fail on upstream main, listed in `fork/ci/unit-test-debt.txt`; any other failure is red, and a red
  fork-tests skips the weekly release.
- Both environments hold `QUAY_USERNAME` and `QUAY_TOKEN` of a quay robot with write access to `unifai-*`.
- The identity zuno accepts is the workflow path and ref: do not rename the workflow file or change its triggers without changing
  zuno-demo's `platform/supply-chain/image-identities.yaml`.
- The operator image (`quay.io/zuno/unifai-operator:<branch>-<sha>`) is built by the same workflow, when the
  operator's code or Makefile changed; the canary deploys it by digest. The quay robot needs write access to
  `unifai-operator` too.
- A release `vX.Y.Z` (`cut-release.yml` then `release.yml`, [RELEASING.md](RELEASING.md)) adds what a production cluster
  verifies, with `fork/ci/sign_and_attest.sh` (keyless, `id-token: write`): its own signature, provenance and
  SBOM-artifact signature on the six digests built on `devel` (the `devel` identity is accepted only by clusters that opt
  in), and the signature, provenance and SBOM artifact of the bundle and the catalog it builds. `release.json` on the
  GitHub release lists every digest, the catalog to pin as `catalogImage` in zuno-demo
  (`gitops/charts/unifai/values.yaml`) included.
- `make images-devel` stays for local development and quick test images, pushed as `local-<sha>` only (the Makefile refuses a
  `devel*` tag). Those images are **unsigned**: a cluster that verifies
  its UnifAI images refuses them, so pin only digests taken from a CI run's summary.
- Do not push `devel` or `devel-<sha>` by hand: those tags belong to this workflow, and a hand push would replace a signed
  digest with an unsigned one (or the reverse). Use another prefix for local images.
- The UI image bakes the self-signed nginx key and certificate that `make ui-certs` generates into a public image. That is the
  existing behaviour and signing does not change it: the signature attests who built the image, not that it holds no secret.
  Generating the pair when the container starts is the real fix (upstream code, later).
