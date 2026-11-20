---
name: fork-docs-publish
description: Write and publish documentation pages under fork/docs/ of the UnifAI fork. Use when asked to document fork work (release incidents, CI, canary, RAG, delivered versions), to publish drafted pages, or to reorganise fork/*.md.
---

# Publishing fork documentation

Index and drafts: `fork/docs/README.md`.

## Writing a page
- English, concise. One topic per page; link to the file that is authoritative (a ROADMAP row, `fork/docs/releasing.md`, a workflow)
  instead of copying it.
- Every fact verified from the repository or a run: SHAs with `git cat-file -t`, runs with `gh run view <id> -R startxfr/UnifAI`,
  paths with `ls`. State what could not be verified or leave it out. Absolute dates.
- Ask the author session (unifai-coder, unifai-tester) to review facts; unifai-main is told before any change that touches
  `fork/docs/roadmap.md` (it writes release progress there; do not edit it).
- No secrets, no unpublished vulnerability details: the repository is public.

## Layout (since the move of 2026-11-20)
All pages live in `fork/docs/`, indexed by `fork/docs/README.md`: architecture, install, ci-and-testing, releasing, features,
roadmap and roadmap-archive, rag-git-sources, reranker-eval, post-freeze-checks, canary-monitoring, per-version and incident pages.
`fork/README.md` is only a pointer. Add new pages there and link them from the index.

- **Moving or renaming a page** needs the owner's go and the fix of every reference first: find them with
  `git grep -nE "<page>\.md"` (workflows, `fork/ci/*.py`, `fork/hooks/guard-fork-only`, `fork/unifai-operator/Makefile`,
  `fork/calendar.yaml`, `rag/entrypoint.sh`, `MEMORY.md`, `.claude/skills`). Do the pure move (`git mv`) in its own commit,
  the content split in another, so git keeps the renames. Run `python -m pytest -q fork/ci` after.
- Editing `fork/docs/roadmap.md` content: tell unifai-main first (see the fork-roadmap-entry skill).

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
