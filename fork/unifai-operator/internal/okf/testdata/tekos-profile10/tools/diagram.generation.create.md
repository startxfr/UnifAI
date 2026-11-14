---
okf_version: "0.2"
type: tool
title: Diagram generation
resource: https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/tools/diagram.generation.create.md
stale_after: "2027-05-15T00:00:00Z"
zuno:
  profile: "1.0"
  capability: diagram.generation.create
  used_by_tasks:
    - answer-technical-question
  usage_notes: >-
    Takes Mermaid source and an optional alternative text; returns the
    rendered SVG diagram. answer-technical-question uses it when a question
    calls for an architecture, sequence or relationship diagram.
  known_limitations:
    - "Diagrams only: Tekos declares no image generation (image.generation.create)."
    - "Data classification C1 (min_classification); no external_model_policy restriction."
    - "Allowed groups: consultant, adv, sales, board, cdp."
    - "Access: read. It creates content locally and changes no external system."
---

# Diagram generation

Renders a Mermaid diagram to SVG (zuno-demo ADR-0516). `generate_diagram`
is its legacy tool name. The rendering does not send the diagram source to
an external service.

This note grants nothing: the task's `allowed_tools` and
`policies/tools/tool-policy.yaml` decide.
