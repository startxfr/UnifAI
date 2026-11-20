---
name: fork-roadmap-entry
description: Add or update an R-xxx row in fork/ROADMAP.md (or its archive). Use when recording a new fork backlog item, a delivery ("delivered 0.1.x"), a proof, an "Open:" follow-up, or when asked to "update the roadmap", "add an R-number", "archive a delivered item".
---

# Add or update a ROADMAP row

Source of truth: `fork/ROADMAP.md` (active backlog) and `fork/ROADMAP-ARCHIVE.md` (delivered and closed rows). Read the header and
"Working rules" of ROADMAP.md first; do not copy them here.

## Before touching the file
1. **Tell unifai-main first** (SendMessage). It writes release progress in ROADMAP.md; wait for its answer before editing.
2. The checkout is shared: edit with explicit paths only, never `git add -A`, and commit only when unifai-main or the owner asks
   (Conventional Commits, `docs(fork): ...`). Fork-only paths go on `devel` only.

## Format
- Table `| Id | Item | Status | Owner |` under "## 5. UnifAI features". One row per item, on one line.
- **Id**: next free `R-nnn`: take the highest number found in both ROADMAP.md and ROADMAP-ARCHIVE.md and add one
  (`grep -ohE "^\| R-[0-9]+" fork/ROADMAP*.md | sort -t- -k2 -n | tail -1`). Never reuse an id.
- **Item**: what was observed (who reported it, absolute date, evidence), cause, fix with the commit SHA, runs that prove it
  (workflow run ids), and "Open: ..." for what remains. Absolute dates only (2026-11-19, never "yesterday").
- **Status**: `todo`, `doing`, `done`, `blocked`, or for a delivery `**delivered 0.1.73** (2026-11-19)`; a deferred item says who
  decided and when.
- **Owner**: the session or person (e.g. `unifai-main`, `operator`).
- No secrets, no unpublished vulnerability details: the repository is public.
- Verify every fact (SHA exists: `git cat-file -t <sha>`; run id and result read from the run) before writing it.

## Archiving
A delivered or closed item moves, with its full text unchanged, to the matching section of `fork/ROADMAP-ARCHIVE.md`, and its
short line (`| Id | Item (short) |`) is added to "Archived items (index)" in ROADMAP.md. A session that records a new proof for an archived id
edits the row in the archive. A reopened item moves back to ROADMAP.md. Archive only on unifai-main's go: recent deliveries
(e.g. R-558..R-561) stay in the active table until it says otherwise.
