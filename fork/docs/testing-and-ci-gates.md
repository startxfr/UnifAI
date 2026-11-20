# Tests and CI gates of the fork

| Suite | Where | What it covers | Role |
|---|---|---|---|
| fork-tests | `.github/workflows/fork-tests.yml` | no cluster: outbound guard (MCP/A2A clients against real local servers), fork-ci (`fork/ci/test_*.py`: signature and provenance scripts), unit tests of multi-agent, rag and identity minus the debt in `fork/ci/unit-test-debt.txt` (run by `fork/ci/run_unit_tests.py`) | gate of the weekly release (`fork/ci/release_gate.py`): a red run skips the release |
| e2e-kind | `.github/workflows/e2e-kind.yml`, `fork/unifai-operator/hack/kind/e2e.sh`, Go tests in `fork/unifai-operator/test/e2e/` | light e2e suite of the operator on a throwaway kind cluster, mock LLM, no registry or secret written | release gate (RELEASING phase 2), weekly included ("CI green + e2e on kind"): `release.yml` calls it on the six digests it is about to publish. With no input it tests the signed `devel` images of the commit. Also runs on a push to `devel` touching its paths, or by hand |
| Canary | `E2E_VERSION=devel-<sha> make canary-ci canary-e2e-full canary-delete` in `fork/unifai-operator`, on demo333 | real cluster | procedure rule ([RELEASING](../RELEASING.md)): required before a manual release and a promotion (promotion = `canary-e2e-full` green). The automatic weekly release has no canary; in a rehearsal the canary checks are only warnings |
| diag-image-index | `.github/workflows/diag-image-index.yml` (`workflow_dispatch`) | builds a tiny image three ways into a local registry; nothing is pushed to Quay | diagnostic of R-561, see [R-561](incident-r561-image-index.md) (ROADMAP status: Open) |

Limits of e2e-kind: Route CRD without a router, static RWX volumes, stand-in service CA, restore test skipped.

## Recent regression test
R-558: `multi-agent/tests/unit/providers/test_a2a_stream_status.py` (red before the fix, green after). R-559 and R-560 are
delivered in 0.1.73 with no dedicated test cited in the ROADMAP.
