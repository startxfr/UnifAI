# Architecture of the fork

The fork (`startxfr/UnifAI`) tracks upstream and carries its own delta. This page describes how it is organised; the procedures are in
[Install](install.md), [Releasing](releasing.md) and [CI and testing](ci-and-testing.md).

## Branches
`main` mirrors `upstream/main` (fast-forward only); `devel` = `main` + the fork delta; features start from `main`
(`make feature-start`), are merged into `devel` to test (`make feature-to-devel`) and can then go upstream (`make contrib-*`).
`stable` and `release-0.X` carry the releases; the full diagram is in [Releasing](releasing.md#branches).

## Guard rails for main
`main` mirrors upstream, so fork-only paths (`fork/fork-only-paths`) must never reach it. `make init` installs
`fork/hooks/guard-fork-only` as pre-commit and pre-merge-commit hook: it refuses these paths on every branch except
`devel`, `stable` and `release-*` (the release branches, see [RELEASING.md](releasing.md)).

## One product version
A tag `vX.Y.Z` versions the operator, its bundle and catalog and the five application images (rag, multiagent, backend, identity, ui)
together, by digest: see [Releasing](releasing.md#one-product-version).

## Components of the delta
- `fork/unifai-operator`: the operator, its bundle and catalog (own README).
- `fork/ci`: release, signing, e2e and evaluation scripts; `fork/hooks`: git hooks; `fork/values`, `fork/images.yaml`, `fork/render_values.py`: deployment overlay.
- `fork/calendar.yaml`: freeze and promotion dates; `fork/fork-only-paths`: paths that never reach `main`.
- Fork features and their backlog items: [Features](features.md), [Roadmap](roadmap.md).
