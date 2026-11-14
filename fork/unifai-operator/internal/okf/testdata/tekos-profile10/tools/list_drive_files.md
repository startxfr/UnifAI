---
okf_version: "0.2"
type: tool
title: List Drive files
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/list_drive_files.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: list_drive_files
  used_by_tasks:
    - find-relevant-docs
    - check-my-drive-docs
  usage_notes: >-
    Lists the files of the caller's own Google Drive (optionally one
    folder), each with its name, type, last change and link.
    check-my-drive-docs keeps the files relevant to the requested project
    or topic; find-relevant-docs adds them to the material it lists for a
    topic.
  known_limitations:
    - "Runs with the caller's delegated identity (zuno-demo ADR-0014): it lists only files the user can already see."
    - "Returns file metadata, not file content."
    - "Data classification C1 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, board, cdp, sales, adv, finance."
    - "Access: read."
---

# List Drive files

Lists the consultant's own Google Drive files. `list_drive_files` is the
legacy name of the canonical capability `drive.document.search`. Tekos uses
it read-only, to point the consultant to their own material.

This note grants nothing: each task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
