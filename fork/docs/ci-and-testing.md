# CI and testing

## Signed images (CI)

`.github/workflows/publish-images.yml` builds the five application images with the Makefile's Dockerfiles, pushes them to
`quay.io/zuno/unifai-<component>` and signs each digest keyless with the workflow's GitHub OIDC identity, with a SLSA provenance
(`fork/ci/slsa_provenance.py`) attached as an attestation. The SPDX SBOM (tens of MB, far over what the public Rekor log
accepts) is pushed as its own OCI artifact tagged `sha256-<image digest>.sbom` and signed with the same identity. zuno-demo
verifies all of it before deploying
(zuno-demo ADR-0586, WP-176).

- A push to `devel` that touches an image's code publishes `devel-<sha>` and `devel` (environment `quay-devel`, no approval,
  restricted to the `devel` branch). Releases are not built: `release.yml` (tag `vX.Y.Z` cut by `cut-release.yml`, see
  [RELEASING.md](releasing.md)) tags those signed digests `vX.Y.Z` and signs them with its own identity.
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
- A release `vX.Y.Z` (`cut-release.yml` then `release.yml`, [RELEASING.md](releasing.md)) adds what a production cluster
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


## Tests and CI gates

| Suite | Where | What it covers | Role |
|---|---|---|---|
| fork-tests | `.github/workflows/fork-tests.yml` | no cluster: outbound guard (MCP/A2A clients against real local servers), fork-ci (`fork/ci/test_*.py`: signature and provenance scripts), unit tests of multi-agent, rag and identity minus the debt in `fork/ci/unit-test-debt.txt` (run by `fork/ci/run_unit_tests.py`) | gate of the weekly release (`fork/ci/release_gate.py`): a red run skips the release |
| e2e-kind | `.github/workflows/e2e-kind.yml`, `fork/unifai-operator/hack/kind/e2e.sh`, Go tests in `fork/unifai-operator/test/e2e/` | light e2e suite of the operator on a throwaway kind cluster, mock LLM, no registry or secret written | release gate (RELEASING phase 2), weekly included ("CI green + e2e on kind"): `release.yml` calls it on the six digests it is about to publish. With no input it tests the signed `devel` images of the commit. Also runs on a push to `devel` touching its paths, or by hand |
| Canary | `E2E_VERSION=devel-<sha> make canary-ci canary-e2e-full canary-delete` in `fork/unifai-operator`, on demo333 | real cluster | procedure rule ([RELEASING](releasing.md)): required before a manual release and a promotion (promotion = `canary-e2e-full` green). The automatic weekly release has no canary; in a rehearsal the canary checks are only warnings |
| diag-image-index | `.github/workflows/diag-image-index.yml` (`workflow_dispatch`) | builds a tiny image three ways into a local registry; nothing is pushed to Quay | diagnostic of R-561, see [R-561](incident-r561-image-index.md) (ROADMAP status: Open) |

Limits of e2e-kind: Route CRD without a router, static RWX volumes, stand-in service CA, restore test skipped.

### Recent regression test
R-558: `multi-agent/tests/unit/providers/test_a2a_stream_status.py` (red before the fix, green after). R-559 and R-560 are
delivered in 0.1.73 with no dedicated test cited in the ROADMAP.
