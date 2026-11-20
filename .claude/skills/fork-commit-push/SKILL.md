---
name: fork-commit-push
description: Commit and push safely in the shared startxfr/UnifAI checkout (several Claude sessions work in it on devel). Use before any git add, git commit or git push in this repository, or when asked to "commit", "push", "land", "ship this to devel".
---

# Commit and push in the shared checkout

Several sessions share this checkout on `devel`: the index, the worktree and the unpushed commits may be theirs.
Branch model and fork-only paths: [fork/docs/releasing.md](../../../fork/docs/releasing.md) ("Branches").

## Commit
1. Only on `devel` (`git branch --show-current`).
2. `git add <explicit paths>` of your own files. **Never `git add -A`, `git add .` or `git commit -a`.**
3. Run `.claude/skills/fork-commit-push/scripts/check-staged.sh` (read only): it refuses off `devel`, lists what is
   staged with the images each file rebuilds, and asks about new files not covered by
   [fork/fork-only-paths](../../../fork/fork-only-paths). A new fork-only file (not meant for upstream) gets its path
   added to `fork/fork-only-paths` in the same commit. Fork-only paths are refused on `main` and contribution branches
   by [fork/hooks/guard-fork-only](../../../fork/hooks/guard-fork-only) (pre-commit and pre-merge-commit, installed by
   `make init`).
4. Conventional commit message (`fix(…)`, `feat(…)`, `docs(fork): …`): the release notes and the freeze gate read them.

## Push
```
.claude/skills/fork-commit-push/scripts/push-own-sha.sh <sha> <n>          # check: what would be sent
.claude/skills/fork-commit-push/scripts/push-own-sha.sh <sha> <n> --push   # git push origin <sha>:devel
```
It fetches, requires `<sha>` to build on `origin/devel`, and refuses unless `origin/devel..<sha>` holds exactly the
`<n>` commits you expect: other sessions' unpushed commits under yours are not yours to push (rebase yours onto
`origin/devel` alone, or ask their owner). SSH to GitHub is flaky: it retries 3 times.

## Never (without the owner's explicit go)
- `main`, `stable`, `release-*`: `stable` and the `v*` tags are pushed by the release bot only.
- Anything upstream (`redhat-community-ai-tools/UnifAI`): no push, PR, comment or merge.
- The branches `fix/helm-lint-errors` and `fix/multiagent-optional-corp-ca` (open upstream PRs).

## Warn before pushing
- **Image rebuilds**, a comment included (source of truth: `COMPONENTS` in
  [fork/ci/release_images.py](../../../fork/ci/release_images.py)): `.github/workflows/publish-images.yml` rebuilds all
  six images; `fork/unifai-operator/{cmd,api,internal,go.mod,go.sum,Dockerfile,Makefile}` (`OPERATOR_BUILD_PATHS`)
  rebuilds the operator, which needs a new canary before a manual cut (`fork-cut-prep` skill); `rag/`,
  `multi-agent/`, `backend/`, `shared-resources/identity/`, `ui/`, `global_utils/` rebuild the five application
  images. `fork/ci/**` starts a publish-images run but rebuilds nothing.
- **Friday before the weekly cron has run** (17:00 UTC, often hours late): a push restarts the CI the gate waits for
  (45 min, then it skips the release), and a green gate ships the head **without canary**. The script checks this.
- While a cut is being prepared or verified (a canaried digest is in flight), push nothing under the operator paths.
