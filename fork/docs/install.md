# Installing and deploying the fork

Fork-only files (never part of an upstream PR): `Makefile`, `fork.mk` (local, git-ignored), `fork.mk.example`, `fork/`.

- `make help` lists every target. `make init` sets up the `upstream` remote and **disables pushes** to `origin`/`upstream`
  (`git config --unset remote.origin.pushurl` when you want to publish).
- Branches: `main` mirrors `upstream/main` (ff-only); `devel` = `main` + fork delta; features start from `main`
  (`make feature-start`), are merged into `devel` to test (`make feature-to-devel`) and can then go upstream (`make contrib-*`).
- Deployment: `make overlay` copies `helm/` to `.fork/helm/` and deep-merges `fork/values/<file>.yaml` over `helm/values/<file>.yaml`
  (placeholders in braces are read from `fork.mk`); image repositories/tags come from `fork/images.yaml`. Upstream files stay untouched.
- Known gaps: `helmfile` is not validated here (not installed when written); `make helm-lint` reports upstream chart issues
  (`multiagent/be` template without extension, `rabbitmq` missing `common` dependency).

## Local images
See the `make images-devel` bullet of [CI and testing](ci-and-testing.md) for what `make images-devel` produces and why those images are unsigned.

For the layout of the branches and the guard rails, see [Architecture](architecture.md); for releases, [Releasing](releasing.md).
