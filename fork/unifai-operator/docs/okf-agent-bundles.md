# OKF agent bundles

A `UnifaiAgentBundle` deploys one agent bundle: Markdown documents with YAML frontmatter in the Zuno OKF profile,
which [zuno-demo-agents](https://github.com/startxfr/zuno-demo-agents/tree/main/docs) specifies on top of upstream
[Open Knowledge Format 0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md). This page
covers what the operator does with a bundle. How to write, check, sign and publish a bundle, and every `spec` field of
the resource, are documented in zuno-demo-agents.

## Versions this operator reads

| Operator | Profile 1.0: `okf_version: "0.2"` and `zuno.profile: "1.0"` | Legacy: `okf_version: v0.2` or `v0.3` |
|---|---|---|
| 0.1.70 and earlier | refused | read |
| every 0.1 release from 0.1.71 | read | read |
| a later line (0.2, not before the promotion of 2026-12-15; to be decided with zuno-demo WP-268) | read | may be refused |

A reader accepts only the profile versions whose schemas it embeds. A new profile version (1.1) therefore needs an
operator release. `status.okfVersion` shows `okf_version` as written, so `0.2` for a profile bundle and `v0.2` for a
legacy one. The `Valid` condition names the profile, for example `OKF 0.2, profile 1.0, 4 tasks, shape ...`.

## Pull, verify, validate, map

Each step must pass before the next one runs. A failed step emits nothing and leaves alone what the last good version
emitted.

1. **Pull.** `spec.source.oci.reference` must be pinned by digest (`registry/repo@sha256:...`); a tag is refused. The
   operator pulls the manifest and its single gzipped tar layer (16 MiB per layer, 32 MiB unpacked), refusing links and
   paths that escape the bundle. It accepts two artifact types: `application/vnd.zuno.okf.bundle.v2` (keyless,
   zuno-demo-agents) and `application/vnd.zuno.okf.bundle.v1` (signature in a manifest annotation).
2. **Verify**, before any byte of the bundle is parsed (`Verified`). `spec.verify.keyless` checks the cosign
   signature of the manifest digest, stored next to the artifact as `sha256-<hex>.sig`. The check is offline: the
   Fulcio chain, the Rekor signed entry timestamp and the SCT are checked against the Sigstore `trusted_root.json` in
   `trustedRootRef`, then the certificate issuer and subject against `issuer` and `subjectRegExp`.
   `spec.verify.publicKeyRef` checks a `cosign sign-blob` signature of the bundle content digest with a PEM key.
3. **Validate** (`Valid`). Every `.md` file whose frontmatter has a `type` that an embedded schema describes is
   checked against the schema of that type and of its own version. A bundle that mixes versions is therefore read
   document by document. The version comes from this table (zuno-demo ADR-0615 clause 5):

   | `okf_version` | `zuno.profile` | Result |
   |---|---|---|
   | `"v0.2"` or `"v0.3"` | absent | the legacy schema of that version |
   | `"v0.2"` or `"v0.3"` | present | refused: `zuno.profile is only valid with okf_version "0.2"` |
   | `"0.2"` | `"1.0"` | the profile 1.0 schema of that type |
   | `"0.2"` | absent or another value | refused: `unsupported zuno.profile <value>` |
   | anything else, including the unquoted YAML number `0.2` | - | refused: `unsupported okf_version <value>` |

   The operator does not read files without frontmatter (README notes), files without a `type`, or files whose type
   no embedded schema describes. The root `index.md` of a profile bundle falls in this group: its only key is
   `okf_version`. The schemas are closed, so an unknown key is refused (ADR-0615 clause 8). They are embedded in the
   binary, under `internal/okf/schema/`. The profile files are copies of zuno-demo-agents `platform/okf/schema/`,
   synchronized by `hack/sync-okf-schemas.sh <agents-ref>`, which records the agents commit and each file's sha256 in
   `schema/SOURCE`. `schema_sync_test.go` fails when an embedded file differs from `SOURCE`. The legacy files are
   frozen, and `SOURCE` lists their known differences from the agents repository.
4. **Check the ceilings** (`WithinCeilings`). The declared tools, knowledge domains, classification, delegation
   targets, `max_steps` and `max_tokens_per_turn` must fit `spec.ceilings`. A bundle can narrow what the resource
   allows, never widen it.
5. **Emit** (`Emitted`). For each task, the operator emits an LLM, an agent (or the three stages of
   `plan_draft_write`), an optional MCP provider and a workflow. It also emits one `router_direct` condition, plus a
   team when `spec.groupTeam` is set.

## Field mapping

Profile 1.0 and legacy documents map the same way. The exception is the maintainer, which moved from
`provenance.maintainer` to `zuno.maintainer`. `<Ns>` is `spec.contractNamespace`, and both `Unifai` and `Zuno` are
sent while it is unset.

| Document | Field | Becomes |
|---|---|---|
| agent | `okf_version`, `zuno.profile` | the schema dispatch above, `status.okfVersion` and the `Valid` message |
| agent | `title` | `status.display.title`, and the description of the workflows |
| agent | `description` | `status.display.description`, and the system message of a task that has no prompt |
| agent | `zuno.maintainer`, or `provenance.maintainer` in a legacy document | `status.display.maintainer` |
| agent | `zuno.name` | `status.agent`, `status.display.agent`, and the `X-<Ns>-Agent` header |
| agent | `zuno.status` | `active` is served. `placeholder` is not served unless `spec.servePlaceholder` is set. `deprecated` is served with condition reason `Deprecated`. `retired` is withdrawn, which needs the reason annotation. All four go to `status.display.state` |
| agent | `zuno.graph_shape` | `retrieve_reason_respond` gives one agent per task. `plan_draft_write` gives three chained agents, with the tools only on the draft stage. A missing or other shape is refused |
| agent | `zuno.tasks`, `zuno.primary_task` | one set of objects per task. The primary task (by default the first one) owns the workflow named after the resource and `status.primaryTask` |
| agent | `zuno.model.preferred_classification` | each task's level: raised by `spec.classificationOverrides` and by delegation targets, never lowered. It goes to `X-<Ns>-Data-Classification` and `status.display.classification` |
| agent | `zuno.access.groups` | the members of the `spec.groupTeam` team. Also listed in `status.unmapped` (the gateways enforce it) |
| agent | `zuno.ui` | `status.display.displayName`, `tileDescription`, `icon` and `color`. Also listed in `status.unmapped` |
| agent | `zuno.delegation.targets` | A2A nodes towards `spec.delegation`, behind an orchestrator |
| agent, task | `zuno.limits.max_steps` | the agents' `max_rounds` (the task value wins) |
| agent, task | `zuno.limits.max_tokens` (task alias `zuno.max_tokens`) | the LLM's `max_tokens` and the `X-<Ns>-Max-Tokens` header |
| agent, task | `zuno.limits.max_tokens_per_turn` | the agents' `max_tokens_per_turn`, or `spec.ceilings.maxTokensPerTurn` when no value is declared |
| agent | `zuno.limits.memory.history` (alias `zuno.memory.history`) | the agents' history window |
| task | `title`, body | `status.display.tasks[].title`, and the system message when the task has no prompt |
| task | `zuno.allowed_tools` | the agent's providers: a per-task MCP provider from `spec.mcp` plus `spec.providers`. Also listed in `status.unmapped` (mcp-gateway filters the tools) |
| task | `zuno.allowed_knowledge` | the agent's retriever, `spec.retriever` |
| task | `zuno.skills` | each `skills/<name>.md` body (`skills/corp/<name>.md` for `corp/<name>`) is appended to the system message, in order. The skill's tools and knowledge count as the task's |
| prompt | `prompts/<task>.md` body | the task's system message |
| tool, rag, policy | - | validated only |

### `status.unmapped`

These fields are listed in `status.unmapped` rather than dropped: `zuno.access.groups`, `zuno.rag.top_k`, `zuno.ui`,
the `plan_draft_write` shape (as an explanation), and `zuno.models` and `zuno.guardrails` (the platform enforces
both). Per task: `allowed_tools`, `prompt_examples` and `models`. `zuno.limits` (agent or task) is listed when it
holds anything other than `max_steps`, `max_tokens`, `max_tokens_per_turn` and `memory.history`, such as
`max_concurrent_requests`.

### Not read

- **Envelope fields**, in profile 1.0 (`resource`, `sources`, `generated`, `verified`, `status`, `stale_after`, `tags`)
  and in legacy documents (`provenance.repository`, `verification`, `freshness`, free-text `sources`). They are advisory
  metadata and never grant anything. `zuno.status` governs the lifecycle. The schema does not check that it agrees with
  the top-level `status`, so that agreement is left to the zuno-demo-agents CI.
- **Task fields** `zuno.live_read_tool`, `zuno.quota_class`, `zuno.project_required`, and the multi-stage prompt slots
  of `zuno.prompts` (`prompts/<task>--<slot>.md`).
- **`zuno.model.notes`** and the root `index.md`.
