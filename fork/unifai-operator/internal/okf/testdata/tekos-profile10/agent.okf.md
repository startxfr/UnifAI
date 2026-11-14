---
okf_version: "0.2"
type: agent
title: Tekos
description: >-
  Technical consultant assistant. Answers technical questions grounded in
  official product documentation and internal Confluence content, with
  concise citations, and helps consultants locate relevant reference
  material across the RAG corpus and their own Drive.
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/agent.okf.md
sources:
- id: technical-docs
  resource: urn:zuno:knowledge:tech
  title: Official product documentation (OpenShift, Kubernetes, Keycloak, Ansible, Argo CD, Helm, Go), indexed as knowledge.tech
- id: confluence
  resource: urn:zuno:source:confluence
  title: Internal Confluence spaces, through the search_confluence tool
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  maintainer: Zuno Demo architecture team
  name: tekos
  status: active
  graph_shape: retrieve_reason_respond
  primary_task: answer-technical-question
  tasks:
    - answer-technical-question
    - find-relevant-docs
    - check-my-drive-docs
    - write-code
  rag:
    top_k: 5
  model:
    preferred_classification: C1
    notes: >-
      Public product documentation and general technical Q&A are C1 (SaaS
      model use allowed). Confluence content is C2, and its tool policy keeps
      it on local models even though this agent's ceiling is C1. The model
      catalog and each task's preference live in
      policies/models/model-catalog.yaml and
      policies/model-routing/model-routing-policy.yaml; the resolved chain is
      generated below in "Model routing".
  # The corp guardrails floor for C1 (policies/guardrails/guardrails-policy.yaml).
  # No `categories`: Tekos cares about every corp category, which is what the
  # absence means.
  guardrails:
    mode: observe
  # The conversation history Tekos carries: the last 6 turns within 6000
  # tokens, the same window as Arkos.
  limits:
    memory:
      history:
        enabled: true
        max_turns: 6
        token_budget: 6000
  access:
    # ADR-0040: agent entitlement group, orthogonal to the `consultant`
    # business role that governs tool/data permissions inside Tekos
    # (policies/tools/tool-policy.yaml).
    groups:
      - agent_tekos
      # Early access to Tekos for users outside agent_tekos (e.g. a pilot
      # cohort); the gateways grant access on any one of these groups.
      - agent_tekos_preview
  ui:
    displayName: Tekos
    tileDescription: Technical Q&A with citations, for consultants.
    color: "#0066CC"
    icon: code
---

# Tekos

Technical consultant assistant. Tekos answers technical questions about
OpenShift, Kubernetes and the surrounding Red Hat ecosystem from official
product documentation and internal Confluence content, with citations. It
also finds reference material for a topic, lists the consultant's own Drive
documents, and writes code.

The bundle follows the Zuno OKF profile 1.0
(`platform/okf/schema/zuno-okf-profile-1.0-agent.schema.json`). Each task of
`zuno.tasks` is declared in `tasks/<task>.md` and has its system prompt in
`prompts/<task>.md`; `answer-technical-question` is the primary task.

`zuno.graph_shape: retrieve_reason_respond` names the workflow of a turn:
retrieve from the task's knowledge domains, an optional live-read tool call,
reason, respond.

Tekos declares no agent-level `allowed_tools` or `allowed_knowledge`: its
ceiling is the union of its tasks' declarations (zuno-demo ADR-0203). That
union is 13 tools and two knowledge domains, `knowledge.tech` (from
`answer-technical-question` and `find-relevant-docs`) and
`knowledge.project` (from `answer-technical-question`).

<!-- BEGIN GENERATED AUTHORIZATION MATRIX (ADR-0503) - do not edit; regenerate with: python3 platform/okf/generate_authorization_matrix.py -->

## Authorization matrix

Generated per ADR-0503 from this bundle's frontmatter, `policies/tools/tool-policy.yaml`, `policies/knowledge/knowledge-policy.yaml`, `policies/models/model-catalog.yaml` and `policies/model-routing/model-routing-policy.yaml` — the enforced intersection (ADR-0011/ADR-0203) restated for review, never read at runtime. Entitlement (ADR-0040): `agent_tekos, agent_tekos_preview`; model classification ceiling (ADR-0021): `C1`; status: `active`.

| Task (FOR WHAT) | Resource (WHAT) | Kind | Capability / server | Min class | Business roles (WHO) | Ext-model context | Quota | Policy source |
|---|---|---|---|---|---|---|---|---|
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `search_confluence` (live-read) | tool | `confluence.page.search` @ confluence | C2 | consultant, board, cdp, lightspeed_readonly, ocp-ai-ops | blocked | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `search_confluence` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `web_search` | tool | `web.page.search` @ web-search | C1 | sales, consultant, adv, finance, board | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `web_search` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `git.repository.read` | tool | `git.repository.read` @ git-forge | C2 | consultant, board, cdp | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `git.repository.read` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `git.repository.list` | tool | `git.repository.list` @ git-forge | C2 | consultant, board, cdp | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `git.repository.list` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `diagram.generation.create` | tool | `diagram.generation.create` @ diagram-gen | C1 | consultant, adv, sales, board, cdp | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `generate_diagram` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `aap.platform.audit` | tool | `aap.platform.audit` @ aap | C2 | consultant, board, cdp, ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `aap.platform.audit` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `aap.cluster.audit` | tool | `aap.cluster.audit` @ aap | C2 | consultant, board, cdp, ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `aap.cluster.audit` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `k8s.resource.read` | tool | `k8s.resource.read` @ k8s | C2 | ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `k8s.resource.read` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `k8s.resource.list` | tool | `k8s.resource.list` @ k8s | C2 | ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `k8s.resource.list` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `k8s.events.read` | tool | `k8s.events.read` @ k8s | C2 | ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `k8s.events.read` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `k8s.logs.read` | tool | `k8s.logs.read` @ k8s | C2 | ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `k8s.logs.read` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `metrics.query` | tool | `metrics.query` @ k8s | C2 | ocp-ai-ops | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `metrics.query` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `knowledge.tech` | knowledge | — | — | consultant, board, cdp | — | `standard` (user 60 req/5m) | `knowledge/knowledge-policy.yaml` `knowledge.tech` |
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) | `knowledge.project` | knowledge | — | — | consultant, board, sales, adv, finance, cdp | — | `standard` (user 60 req/5m) | `knowledge/knowledge-policy.yaml` `knowledge.project` |
| `find-relevant-docs` (prompt: `prompts/find-relevant-docs.md`) | `search_confluence` | tool | `confluence.page.search` @ confluence | C2 | consultant, board, cdp, lightspeed_readonly, ocp-ai-ops | blocked | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `search_confluence` |
| `find-relevant-docs` (prompt: `prompts/find-relevant-docs.md`) | `list_drive_files` | tool | `drive.document.search` @ google-workspace | C1 | consultant, board, cdp, sales, adv, finance | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `list_drive_files` |
| `find-relevant-docs` (prompt: `prompts/find-relevant-docs.md`) | `knowledge.tech` | knowledge | — | — | consultant, board, cdp | — | `standard` (user 60 req/5m) | `knowledge/knowledge-policy.yaml` `knowledge.tech` |
| `check-my-drive-docs` (prompt: `prompts/check-my-drive-docs.md`) | `list_drive_files` | tool | `drive.document.search` @ google-workspace | C1 | consultant, board, cdp, sales, adv, finance | allowed | `standard` (user 60 req/5m) | `tools/tool-policy.yaml` `list_drive_files` |

### Model routing

Effective per-task model chain (ADR-0021/ADR-0303/ADR-0412), resolved from `policies/models/model-catalog.yaml`'s classification eligibility reordered by this `(agent, task)`'s `policies/model-routing/model-routing-policy.yaml` preference — the first entry is the reference model, the rest are fallback alternatives, in try order. The reference model is annotated with the model id it actually serves and that model's architectural role (`default`, `quality`, `reasoning`, `specialized`, `reasoning-external`, `code`, `general-external`); `model-catalog.yaml`'s `role` key is the authority for both, and every model reachable through the fallback chain is named in the **Available models** rollup below the table.

| Task | Classification ceiling | Reference model | Fallback chain | Adapter | Policy source |
|---|---|---|---|---|---|
| `answer-technical-question` (primary; prompt: `prompts/answer-technical-question.md`) (in a classified project) | `C1/C2/C3` | `local-gpt-oss-maas` → `gpt-oss-20b` (reasoning) | `local-gpt-oss`, `local-qwen35-maas`, `local-qwen35`, `local-wesh-maas`, `local-wesh`, `local-maas`, `local` | — | `policies/model-routing/model-routing-policy.yaml` |
| `find-relevant-docs` (prompt: `prompts/find-relevant-docs.md`) (in a classified project) | `C1/C2/C3` | `local-qwen35-maas` → `qwen3.5-9b` (default) | `local-qwen35`, `local-wesh-maas`, `local-wesh`, `local-maas`, `local`, `local-gpt-oss-maas`, `local-gpt-oss` | — | `policies/model-routing/model-routing-policy.yaml` |
| `check-my-drive-docs` (prompt: `prompts/check-my-drive-docs.md`) | `C1` | `local-qwen35-maas` → `qwen3.5-9b` (default) | `local-qwen35`, `local-wesh-maas`, `local-wesh`, `local-maas`, `local`, `local-gpt-oss-maas`, `local-gpt-oss`, `ovhcloud-gpt-oss-120b`, `openai`, `gemini`, `anthropic`, `mistral`, `mistral-codestral` | — | `policies/model-routing/model-routing-policy.yaml` |
| `write-code` (prompt: `prompts/write-code.md`) | `C1` | `mistral-codestral` → `codestral-latest` (code) | `local-wesh-maas`, `local-wesh`, `local-gpt-oss-maas`, `local-gpt-oss`, `local-maas`, `local`, `local-qwen35-maas`, `local-qwen35`, `openai`, `gemini`, `anthropic`, `mistral`, `ovhcloud-gpt-oss-120b` | — | `policies/model-routing/model-routing-policy.yaml` |

**Available models** (ADR-0419, generated): the union of every model reachable by any task or prompt slot above, at any classification, each with the model id it serves and that model's role - `local-maas` → `qwen3.6-27b-instruct` (quality), `local` → `qwen3.6-27b-instruct` (quality), `local-gpt-oss-maas` → `gpt-oss-20b` (reasoning), `local-gpt-oss` → `gpt-oss-20b` (reasoning), `local-wesh-maas` → `qwen3.5-9b-wesh` (specialized), `local-wesh` → `qwen3.5-9b-wesh` (specialized), `local-qwen35-maas` → `qwen3.5-9b` (default), `local-qwen35` → `qwen3.5-9b` (default), `openai` → `gpt-4o-mini` (general-external), `gemini` → `gemini-1.5-pro` (general-external), `anthropic` → `claude-3-5-sonnet-latest` (general-external), `mistral` → `mistral-large-latest` (general-external), `mistral-codestral` → `codestral-latest` (code), `ovhcloud-gpt-oss-120b` → `gpt-oss-120b` (reasoning-external).

<!-- END GENERATED AUTHORIZATION MATRIX -->
