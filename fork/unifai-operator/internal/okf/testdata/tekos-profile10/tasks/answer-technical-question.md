---
okf_version: "0.2"
type: task
title: Answer a technical question
description: Answer a technical question from the documentation corpus and Confluence, with citations.
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tasks/answer-technical-question.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  allowed_tools:
    - search_confluence
    - web_search
    - git.repository.read
    - git.repository.list
    # zuno-demo ADR-0516: diagram generation (Mermaid to SVG) for questions
    # that call for an architecture, sequence or relationship diagram. Tekos
    # never declares image.generation.create: illustrative images are not its
    # job.
    - diagram.generation.create
    # zuno-demo ADR-0355: AAP audits, for "is the cluster healthy right now?".
    # aap.cluster.audit is a write tool: it launches the cluster health check.
    # tool-policy.yaml gives both entries the same allowed_groups, so this
    # task declaration is what holds the read/launch line: re-read ADR-0355's
    # security considerations before declaring it in another task.
    - aap.platform.audit
    - aap.cluster.audit
    # zuno-demo ADR-0600: read-only Kubernetes reads of the zuno-* namespaces,
    # for "why does this pod not start?". tool-policy.yaml admits `ocp-ai-ops`
    # only, so this declaration reaches the operations persona alone; the
    # business personas keep Tekos without cluster reads.
    - k8s.resource.read
    - k8s.resource.list
    - k8s.events.read
    - k8s.logs.read
    - metrics.query
  live_read_tool: search_confluence
  allowed_knowledge:
    - knowledge.tech
    - knowledge.project
  # The model roles this task prefers, in order. They reorder this task's
  # candidates in policies/model-routing/model-routing-policy.yaml, never add
  # or remove one. The local reasoning model comes first for its much shorter
  # time to first token (zuno-demo stresstest 2026-10-31).
  models:
    preferred:
      - reasoning
      - reasoning-external
      - default
      - specialized
      - quality
  # Example prompts a user interface can offer for this task. Display only: choosing one does not select the task.
  prompt_examples:
    - "How do I configure Keycloak as the OIDC identity provider for an OpenShift cluster?"
    - "What is the difference between a Route and an Ingress on OpenShift?"
    - "How does Argo CD decide that an Application is out of sync?"
---

# Answer a technical question

Answer a free-form technical question from the indexed documentation corpus
(`knowledge.tech`: official Red Hat product documentation and internal
Confluence content) and the consultant's project memory
(`knowledge.project`). When the retrieved documents do not ground an
answer, the live-read tool `search_confluence` reads Confluence directly;
`web_search` is the last resort, within this bundle's
`policies/web-search-scope.md`.
Every answer cites its sources.

The other tools serve specific questions:

- `git.repository.read` and `git.repository.list` read public GitHub or
  GitLab repositories. Tekos declares no private-repository or repository
  write capability.
- `diagram.generation.create` renders a Mermaid diagram to SVG.
- `aap.platform.audit` summarizes the state of Ansible Automation Platform;
  `aap.cluster.audit` launches the cluster health check through it.
- `k8s.resource.read`, `k8s.resource.list`, `k8s.events.read`,
  `k8s.logs.read` and `metrics.query` read the zuno-* namespaces and their
  metrics, for the operations persona only.

This is the agent's primary task.
