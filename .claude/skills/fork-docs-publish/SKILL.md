---
name: fork-docs-publish
description: Write and publish documentation pages under fork/docs/ of the UnifAI fork. Use when asked to document fork work (release incidents, CI, canary, RAG, delivered versions), to publish drafted pages, or to reorganise fork/*.md.
---

# Publishing fork documentation

Index and drafts: `fork/docs/README.md` once published; until then drafts live outside the repository.

## Writing a page
- English, concise. One topic per page; link to the file that is authoritative (a ROADMAP row, `fork/docs/releasing.md`, a workflow)
  instead of copying it.
- Every fact verified from the repository or a run: SHAs with `git cat-file -t`, runs with `gh run view <id> -R startxfr/UnifAI`,
  paths with `ls`. State what could not be verified or leave it out. Absolute dates.
- Ask the author session (unifai-coder, unifai-tester) to review facts; unifai-main is told before any change that touches
  `fork/docs/roadmap.md` (it writes release progress there; do not edit it).
- No secrets, no unpublished vulnerability details: the repository is public.

## Phase 1 rules (now)
- **New pages only** in `fork/docs/`, plus one line linking `fork/docs/README.md` in `fork/docs/fork-tooling.md`.
- **Do not move or rename** the flat pages (`README`, `RELEASING`, `ROADMAP`, `ROADMAP-ARCHIVE`, `POST-FREEZE-CHECKS`,
  `RAG-GIT-SOURCES`, `RERANKER-EVAL`) without the owner's go, and only after fixing every reference. Find them with
  `git ls-files -z | xargs -0 grep -nIE "<page>\.md"`: workflows (`.github/workflows/*`), `fork/ci/*.py`, `fork/hooks/guard-fork-only`,
  `fork/unifai-operator/Makefile`, `fork/calendar.yaml`, `rag/entrypoint.sh`, `MEMORY.md`.

## When to publish
- Only when unifai-main gives the signal, and after a green CI on `devel`.
- Not before the weekly tag exists (`git ls-remote --tags origin`) or unifai-main confirms the weekly release was skipped: the
  Friday cron often starts hours late (22:26Z on 2026-11-13), and a push to `devel` while it runs or while the head's CI is
  running or red makes it skip.
- Not during the 0.1 line freeze (2026-12-01 to 2026-12-14); if not done before, wait until 2026-12-15.

## Commit
One commit, explicit paths (`git add fork/docs/... fork/docs/fork-tooling.md`; the checkout is shared, never `git add -A`), message
`docs(fork): ...` with the Co-Authored-By line, push to `devel` only (never `main` or a release branch). Check
`git status` and `git log origin/devel..` first so only your SHA is pushed.
