---
okf_version: "0.2"
type: tool
title: AAP platform audit
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/aap.platform.audit.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: aap.platform.audit
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Returns a summary of the Ansible Automation Platform's own state: the
    health of its components and instances, the last Git sync of the
    project, and the recent runs of the cluster health-check job template,
    each with a link to the run (and the last output lines of the most
    recent one). answer-technical-question uses it for "is the cluster
    healthy?" and after aap.cluster.audit, to see whether that run passed.
    Share the run link, and the output lines when the run failed.
  known_limitations:
    - "Data classification C2 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, board, cdp, ocp-ai-ops."
    - "Access: read. It changes nothing."
---

# AAP platform audit

The read-only half of Tekos's Ansible Automation Platform audits (zuno-demo
ADR-0355): a quick status summary. To start a fresh health check, the task
uses `aap.cluster.audit`.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
