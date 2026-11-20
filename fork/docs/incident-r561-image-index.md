# R-561: OCI image index and provenance (v0.1.73)

Status: **closed** 2026-11-20 in [ROADMAP](roadmap.md) (row R-561): the incident is fixed, v0.1.73 and v0.1.74 are delivered, and the indexes are kept.

## Symptom
The first cut of v0.1.73 (2026-11-19) failed at the step "Tag and sign the six images" of `release.yml`: the Quay tag was
`sha256:ebb1cd29…` (the amd64 image) instead of `sha256:88b834bc…` (the signed index). Nothing was published.

## Cause
The CI builds of that day are OCI image indexes (the amd64 image plus its build attestation); the builds of 0.1.72 and
before were plain manifests. `skopeo copy --preserve-digests` without `--all` copies only the amd64 image, so the tag got
another digest than the signed index.

The reason the builds became indexes was found on 2026-11-20 with the manual `diag-image-index` run 44767866225:
`ubuntu-latest` is now Ubuntu 26.04 (image 20261116.202.1) with Docker 29.4.2 (containerd image store) and buildx 0.39.0,
where a plain `docker build` + `docker push` attaches a BuildKit provenance attestation by default.

## Fix
Commit `6dbd294c5`: `release.yml` runs `skopeo copy --all --preserve-digests`. The tag v0.1.73 was deleted by an admin
(never released) and re-cut on `6dbd294c5` with the same canaried images; cosign verification 8/8.

## The diagnostic workflow
`.github/workflows/diag-image-index.yml` (manual, `workflow_dispatch`) prints the runner tooling, then builds a minimal
image three times into a registry local to the runner (nothing is pushed to Quay): default, `--provenance=false` and
`BUILDX_NO_DEFAULT_ATTESTATIONS=1`. For each it prints the media type of the manifest as `RESULT <tag> -> <mediaType>`.
Result of run 44767866225:

```
RESULT default -> application/vnd.oci.image.index.v1+json
RESULT noprov -> application/vnd.docker.distribution.manifest.v2+json
RESULT envflag -> application/vnd.docker.distribution.manifest.v2+json
```

`noprov` is `docker build --provenance=false`; `envflag` is `BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker build`.

## Decision (2026-11-20)
Keep the OCI indexes: the BuildKit provenance attestation stays, `release.yml` copies the whole index
(`skopeo copy --all`), and mirrors copy by digest with `oras cp -r`. `publish-images.yml` is not changed, so no image is
rebuilt and no canary is needed. v0.1.74 shipped indexes end to end and was verified (cosign 8/8).

See the R-561 row of [ROADMAP](roadmap.md) for the authoritative text.
