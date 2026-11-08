# Checks to run on demo333 once the freeze is lifted (0.1.66)

Owner of the commands: zuno-demo-05 (cluster). Reader of the raw outputs: b9 (writes the ROADMAP). Nothing here runs during a freeze;
each step says what to send back. Namespace placeholders: `<ns>` = the UnifAI stack namespace.

## 1. R-548, re-registration of a git source keeps its commit
Why: any spec change makes the operator send `PUT /api/pipelines/embed` again (`ragsource_controller.go`, `apply`/`trigger`, hash of the
instance). The first proof (`spec.resyncToken` 1 to 2, log "ref still at 41862c835a7b") already went through that path. What is left is the opposite case.

1. Create `r548-gitignore` (`type: git`, `url: https://github.com/github/gitignore`, `paths: [Global]`, `include: ['*.md']`, `visibility: private`). Wait Ready.
2. Edit `spec.git.include` to `['*.md', '*.gitignore']`. Expected: a full re-ingest at the same commit (log "ingested", pages greater than before), NOT "ref still at".
3. Set `spec.resyncToken` to a new value. Expected: log "ref still at <commit>, nothing to do".
4. Delete the source.

Send back: the status line of step 1 and 2 (`oc get unifairagsource r548-gitignore -o jsonpath='{.status.message}'`) and the rag-celery log lines of steps 2 and 3.

## 2. R-545, team delete answered 403
1. Create a UnifaiTeam `r545-probe` owned by the admin. In identity, make its creator someone other than the owner used by the operator (or use a team created by another user).
2. `oc delete unifaiteam r545-probe --wait=false`. Expected: the object stays `Deleting`, status message names the creator or an UnifAI admin, event `DeleteFailed`.
3. Delete the team in identity as the creator or an admin. Expected: the CR disappears within a reconcile.

Send back: `oc get unifaiteam r545-probe -o yaml` (status and events) after step 2, and the final `oc get` after step 3.

## 3. R-543, token ceiling of one turn
1. On a throwaway bundle (or the stack ceiling `spec.ceilings.maxTokensPerTurn: 2000`), set `zuno.limits.max_tokens_per_turn: 2000` on the agent.
2. Send one user turn that needs several model calls (a delegation or a long answer).
3. Expected: the answer ends with `Token ceiling reached for this turn (<used>/2000 tokens)`, exactly one `agent_error` event for the turn, the session stays usable.
4. Remove the ceiling and the bundle.

Send back: the final answer text, the session events of the turn, and the used/cap figures.

## 4. R-530, OCP 4.22 source then ranking
1. Apply `ocp-4-22-docs` from `fork/RAG-GIT-SOURCES.md` (first manifest). It took 9 min 36 s for 1859 pages on 0.1.65. Embedding load: only after 59 allows it.
2. When Ready, send a9 the source name `ocp-4-22-docs` and the finish time. a9 re-measures the ranking (baseline EN21 0.71 / 0.86 / 0.77).

Send back: the status line, pages count, duration.

## 5. RHACM (private), only with the user's explicit go
Apply `rhacm-2-17-docs` with `visibility: private` (see `fork/RAG-GIT-SOURCES.md`). 1056 documents, 4.4 MB. No sharing until the licence is clarified.
