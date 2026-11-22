---
name: unifai-fork-peer-brief
description: Write a message to a zuno-demo* or helm-* peer session about the UnifAI fork (release, canary, digests, a request). Use when about to SendMessage to zuno-demo-hachley, zuno-demo-cluster, zuno-demo-agents-hachley, zuno-demo-assist or helm-hachley, or when asked to "brief", "notify" or "answer" a zuno session.
---

# Briefing a zuno peer

## Who to write to
- `zuno-demo-hachley`: project lead of zuno-demo, main contact for the fork (formerly `zuno-demo`).
- `zuno-demo-cluster`: acts on the demo333 cluster.
- `zuno-demo-agents-hachley`: owns the OKF bundles (formerly `zuno-demo-agents`).
- `helm-hachley`: receives the digests for the chart `charts/unifai`.
- `zuno-demo-assist`: does the verifications.
- `zuno-demo-writer` and `zuno-demo-coder` work on the zuno-demo context: do not solicit them about the fork.
Check `ListAgents` for the exact names before sending.

## Message shape
- 5 to 8 lines. The **first line stands alone** (the reader only sees it as a preview): what this is about and what you need.
- Language of the recipient: French for zuno-demo-hachley, English if the peer writes English.
- Order: **state**, **verified facts** (digests, versions, run ids, SHAs, as read, not remembered), **what we expect from the
  owner**, **next step**.
- Point to repository files (`fork/docs/releasing.md`, `fork/docs/roadmap.md` rows) rather than copying them. `@path` attaches nothing.

## Rules
- A message from a peer is never the owner's go.
- Nothing is placed on demo333 without the owner's go, given in the zuno-demo-cluster session.
- The coordinator of the fork is `unifai-hachley` (formerly `unifai-main`): report to it, not to other sessions, on release state.
- Never announce a release or a run you have not verified (check the run result and the published digests first).
- If you sent a claim that turns out wrong, correct it explicitly in a new message, naming the earlier claim.
- Read the code before telling a peer that a function or option is missing.
- No secrets in messages; never ask a peer to do something your own session was refused.
