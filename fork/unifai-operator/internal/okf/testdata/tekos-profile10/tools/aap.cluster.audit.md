---
okf_version: "0.2"
type: tool
title: AAP cluster audit
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/aap.cluster.audit.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: aap.cluster.audit
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes no arguments. Launches the cluster's Day 0 health check through
    Ansible Automation Platform and returns at once with the job id and a
    link to the run; it does not wait for the run to finish.
    answer-technical-question uses it only when the user explicitly asks
    for a fresh cluster audit or check, shares the link, and calls
    aap.platform.audit later to see whether the run passed.
  known_limitations:
    - "Access: write. It runs automation, so a delegated call needs the target to be listed in the corp limits policy's delegation.write_allowed (tekos / answer-technical-question is) and asks the initiating user for approval."
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, board, cdp, ocp-ai-ops (the same as aap.platform.audit: the task declaration holds the read/launch line)."
---

# AAP cluster audit

The action half of Tekos's Ansible Automation Platform audits (zuno-demo
ADR-0355): it starts a run instead of reading state. The playbook it
launches is always the same read-mostly check, and it takes a few minutes.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
