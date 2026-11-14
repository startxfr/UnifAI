---
okf_version: "0.2"
type: tool
title: Git repository read
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/git.repository.read.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: git.repository.read
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes a provider (GitHub or GitLab), an owner, a repository and
    optionally a path and a ref; returns the file's content, or the
    directory's listing (the root when the path is empty).
    answer-technical-question uses it when a question is about what a
    public repository contains, such as a manifest, a playbook or a README.
  known_limitations:
    - "Public repositories only, on either provider: a private repository is refused."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, board, cdp."
    - "Access: read."
---

# Git repository read

Reads public GitHub or GitLab repositories, so Tekos can answer from real
code and configuration. Tekos declares no private-repository capability
(`git.repository.private.*`) and no repository write.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
