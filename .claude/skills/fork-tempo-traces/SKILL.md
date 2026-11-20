---
name: fork-tempo-traces
description: Read-only analysis of multi-agent traces in Tempo (namespace zuno-monitoring). Use when asked to count or inspect delegations, re-delegations per work item, delegate_task spans, MAS_MAX_DELEGATIONS_PER_ITEM refusals, A2A send_message per session, or any "look at the traces / Tempo / TraceQL" request on a zuno cluster.
---

# fork-tempo-traces

Read-only. Never write to Tempo or the cluster beyond the port-forward. Count first, conclude after: state the numbers
(spans, work items, sessions, time window) before any diagnosis.

## Access (port-forward, stopped by PID)

```bash
kubectl -n zuno-monitoring port-forward svc/tempo-tempo 3200:3200 >/dev/null 2>&1 &
echo $! > "$SCRATCH/tempo-pf.pid"        # $SCRATCH = the session scratchpad, not /tmp
curl -s localhost:3200/api/echo           # ready check, prints "echo"
# when done:
kill "$(cat "$SCRATCH/tempo-pf.pid")" && rm "$SCRATCH/tempo-pf.pid"
```

Never `pkill`/`killall` on a pattern: other sessions may hold their own port-forwards. If port 3200 is busy, use another
local port instead of killing what holds it. Check the service name and port with `kubectl -n zuno-monitoring get svc`
if the forward fails (they come from the cluster, not from this repo).

## API (Tempo HTTP API, see the Tempo documentation)

- Search: `GET /api/search?q=<TraceQL, URL-encoded>&limit=<n>&start=<unix s>&end=<unix s>`; use `curl -G --data-urlencode "q=..."`.
  Always pass `start`/`end` and a `limit` high enough, and say when the limit may have truncated the count.
- Trace by id: `GET /api/traces/<traceID>` (`/api/v2/traces/<id>` on recent Tempo). Large: pipe to `jq`/python, do not print.
- Discovery: `GET /api/search/tags` and `/api/search/tag/<name>/values` to see which attributes exist before querying.

## Typical TraceQL

```
{ name = "execute_tool iem.delegate_task" }
{ name = "execute_tool iem.delegate_task" && span.mas.delegation.work_item_id = "<id>" }
{ name = "execute_tool iem.delegate_task" && status = error }
{ name = "execute_tool iem.delegate_task" && span.mas.success = false }
```

Re-delegation per work item: fetch the `delegate_task` spans of the window, group by `mas.delegation.work_item_id`
(and `mas.delegation.target`), count per group. A group above 1 is a re-delegation; above `MAS_MAX_DELEGATIONS_PER_ITEM`
(default 3, 0 = unlimited) should not happen: the 4th call is refused.

## What the attributes are (read the code, do not guess)

- `multi-agent/adapters/outbound/otel/otel_tracing_service.py`: `_TOOL_SPAN_IDENTIFIERS` is an allow-list; only
  `iem.delegate_task` carries `mas.delegation.work_item_id` and `mas.delegation.target`. No other tool argument or
  request content reaches a span, so do not look for them.
- `trace_tool` names spans `execute_tool <tool name>`. A span ends in ERROR status with `mas.success=false` when the tool
  reports failure. A refusal by the per-item cap is such a failure (`multi-agent/lib/mas/elements/tools/builtin/delegation/delegate_task.py`,
  `MAS_MAX_DELEGATIONS_ENV`). Verify on a few spans before counting refusals as ERROR.
- Session spans are `mas.session` with attribute `session.id`; group by it for per-session counts.
- A2A `send_message` per session: baseline is 1 delegation = 2 `send_message` (counted in Tempo on 2026-11-14 over 19
  arkos traces: 2 for a simple delegation, 3 with a follow-up). These spans are not created by `otel_tracing_service.py`;
  they most likely come from the a2a SDK's own client instrumentation. Search by span name, not by an exact name:
  `{ name =~ ".*send_message.*" }`, count per trace. Fall back to the worker log only if no trace has such a span, and say so.

## Caveats to state in any report

- The `mas.called_tools` attribute of an `llm` span may show a raw tool name carrying a Harmony control token
  (`...<|channel|>commentary`). The execution restores the name (`multi-agent/lib/mas/elements/llms/common/tool_name_restorer.py`)
  but not this attribute. The warning log `llm.tool_name_control_token` marks those cases. Do not count them as unknown tools.
- Tempo retention and the search `limit` bound the sample; a count is a lower bound unless the window is fully covered.
- Traces of a session can arrive late: re-query before concluding on a recent session.
- Report: window, query, number of traces/spans, grouping key, then the counts, then (separately) the interpretation.
