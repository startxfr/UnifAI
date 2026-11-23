// R-568 follow-up: the two HITL handlers of ChatInterface, extracted as pure functions (helpers/approvalActions.ts).
//
// Contract pinned here:
//  - decideApproval REJECTS when the decision was not sent (no run id, submit failed), after exactly one "Approval
//    failed" toast. ApprovalCard.handleDecision relies on that rejection to keep the reason and stay retryable; a
//    handler that resolves after a failure made the card clear the reason (R-568 ineffective). It RESOLVES when the
//    decision was sent but the optimistic UI update threw (a retry would send it twice): logged only.
//  - applyAutoRule always RESOLVES (ApprovalCard.handleAutoRuleClick has no catch) and never shows two toasts, nor
//    "Rule save failed" when the rule itself was saved.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { decideApproval, applyAutoRule } from "./approvalActions";

type Toast = { title: string; description?: string; variant?: string };

function makeDeps() {
  const toasts: Toast[] = [];
  const toast = vi.fn((t: Toast) => {
    toasts.push(t);
  });
  const submitApproval = vi.fn(async (_p: any) => ({ ok: true }));
  const submitApprovalRule = vi.fn(async (_p: any) => ({ ok: true }));
  return { deps: { submitApproval, submitApprovalRule, toast }, toasts, submitApproval, submitApprovalRule };
}

const titles = (toasts: Toast[]) => toasts.map((t) => t.title);

beforeEach(() => {
  // The handlers log the failure with console.error; keep the test output readable.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("decideApproval", () => {
  it("sends the decision with the run id as session id, then calls onSubmitted once, without any toast", async () => {
    const { deps, toasts, submitApproval } = makeDeps();
    const order: string[] = [];
    submitApproval.mockImplementation(async () => {
      order.push("submit");
      return { ok: true };
    });
    const onSubmitted = vi.fn(() => {
      order.push("submitted");
    });

    await decideApproval(
      deps,
      { runId: "run-1", requestId: "req-1", decision: "modify", feedback: "plus prudent", modifiedArgs: { path: "/tmp" } },
      onSubmitted,
    );

    expect(submitApproval).toHaveBeenCalledTimes(1);
    expect(submitApproval).toHaveBeenCalledWith({
      sessionId: "run-1",
      requestId: "req-1",
      decision: "modify",
      feedback: "plus prudent",
      modifiedArgs: { path: "/tmp" },
    });
    expect(onSubmitted).toHaveBeenCalledTimes(1);
    expect(order).toEqual(["submit", "submitted"]);
    expect(toasts).toEqual([]);
  });

  it("works without onSubmitted", async () => {
    const { deps, toasts, submitApproval } = makeDeps();
    await expect(decideApproval(deps, { runId: "run-1", requestId: "req-1", decision: "approve" })).resolves.toBeUndefined();
    expect(submitApproval).toHaveBeenCalledTimes(1);
    expect(toasts).toEqual([]);
  });

  it("rejects with the SAME error after exactly one destructive 'Approval failed' toast when the submit fails", async () => {
    const { deps, toasts, submitApproval } = makeDeps();
    const boom = new Error("502 bad gateway");
    submitApproval.mockRejectedValue(boom);
    const onSubmitted = vi.fn();

    await expect(
      decideApproval(deps, { runId: "run-1", requestId: "req-1", decision: "reject", feedback: "trop risqué" }, onSubmitted),
    ).rejects.toBe(boom);

    expect(titles(toasts)).toEqual(["Approval failed"]);
    expect(toasts[0].variant).toBe("destructive");
    // Nothing is shown as decided when the decision never left.
    expect(onSubmitted).not.toHaveBeenCalled();
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["an empty string", ""],
  ])("with %s as run id: rejects, one 'Approval failed' toast, nothing sent, no optimistic update", async (_label, runId) => {
    const { deps, toasts, submitApproval } = makeDeps();
    const onSubmitted = vi.fn();

    await expect(decideApproval(deps, { runId, requestId: "req-1", decision: "approve" }, onSubmitted)).rejects.toBeDefined();

    expect(submitApproval).not.toHaveBeenCalled();
    expect(onSubmitted).not.toHaveBeenCalled();
    expect(titles(toasts)).toEqual(["Approval failed"]);
    expect(toasts[0].variant).toBe("destructive");
  });

  it("a failing optimistic update does not undo the decision: resolves, no toast, sent once, only logged", async () => {
    // The decision already left. Rejecting would make the card keep the reason and a retry would send it twice.
    const { deps, toasts, submitApproval } = makeDeps();
    const onSubmitted = vi.fn(() => {
      throw new Error("flush exploded");
    });
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});

    await expect(
      decideApproval(deps, { runId: "run-1", requestId: "req-1", decision: "approve" }, onSubmitted),
    ).resolves.toBeUndefined();

    expect(submitApproval).toHaveBeenCalledTimes(1);
    expect(onSubmitted).toHaveBeenCalledTimes(1);
    expect(toasts).toEqual([]);
    expect(logged).toHaveBeenCalled();
  });

  it("a failure does not poison the next attempt: the retry sends and resolves with no toast", async () => {
    const { deps, toasts, submitApproval } = makeDeps();
    submitApproval.mockRejectedValueOnce(new Error("timeout"));
    const onSubmitted = vi.fn();
    const args = { runId: "run-1", requestId: "req-1", decision: "reject" as const, feedback: "trop risqué" };

    await expect(decideApproval(deps, args, onSubmitted)).rejects.toThrow("timeout");
    await expect(decideApproval(deps, args, onSubmitted)).resolves.toBeUndefined();

    expect(submitApproval).toHaveBeenCalledTimes(2);
    expect(submitApproval).toHaveBeenLastCalledWith(expect.objectContaining({ requestId: "req-1", feedback: "trop risqué" }));
    expect(onSubmitted).toHaveBeenCalledTimes(1);
    expect(titles(toasts)).toEqual(["Approval failed"]);
  });
});

describe("applyAutoRule", () => {
  // The way ChatInterface wires it: the decision goes through decideApproval, which toasts and rejects on failure.
  function wire(...args: [runId?: string | null]) {
    // An explicit undefined must stay undefined (a default parameter would turn it into "run-1").
    const runId = args.length === 0 ? "run-1" : args[0];
    const ctx = makeDeps();
    const onSubmitted = vi.fn();
    const decide = vi.fn((requestId: string, decision: any, feedback?: string) =>
      decideApproval(ctx.deps, { runId, requestId, decision, feedback }, onSubmitted),
    );
    const run = (action: "auto_approve" | "auto_reject") =>
      applyAutoRule(ctx.deps, { runId, requestId: "req-1", nodeUid: "node-7", toolName: "write_file", action }, decide);
    return { ...ctx, decide, onSubmitted, run };
  }

  it("auto_approve, everything succeeds: saves the rule, approves without feedback, one 'Auto-approve rule saved' toast", async () => {
    const { run, decide, submitApprovalRule, submitApproval, toasts } = wire();

    await expect(run("auto_approve")).resolves.toBeUndefined();

    expect(submitApprovalRule).toHaveBeenCalledTimes(1);
    expect(submitApprovalRule).toHaveBeenCalledWith({
      sessionId: "run-1",
      nodeUid: "node-7",
      toolName: "write_file",
      action: "auto_approve",
    });
    expect(decide).toHaveBeenCalledTimes(1);
    expect(decide).toHaveBeenCalledWith("req-1", "approve", undefined);
    expect(submitApproval).toHaveBeenCalledTimes(1);
    expect(titles(toasts)).toEqual(["Auto-approve rule saved"]);
    expect(toasts[0].variant).toBeUndefined();
  });

  it("auto_reject, everything succeeds: rejects with the standard feedback, one 'Auto-reject rule saved' toast", async () => {
    const { run, decide, submitApprovalRule, toasts } = wire();

    await expect(run("auto_reject")).resolves.toBeUndefined();

    expect(submitApprovalRule).toHaveBeenCalledWith(expect.objectContaining({ action: "auto_reject" }));
    expect(decide).toHaveBeenCalledWith("req-1", "reject", "auto-reject rule applied");
    expect(titles(toasts)).toEqual(["Auto-reject rule saved"]);
  });

  it("the rule cannot be saved: resolves, one destructive 'Rule save failed' toast, no decision attempted", async () => {
    const { run, decide, submitApprovalRule, submitApproval, toasts } = wire();
    submitApprovalRule.mockRejectedValue(new Error("403"));

    await expect(run("auto_approve")).resolves.toBeUndefined();

    expect(titles(toasts)).toEqual(["Rule save failed"]);
    expect(toasts[0].variant).toBe("destructive");
    expect(decide).not.toHaveBeenCalled();
    expect(submitApproval).not.toHaveBeenCalled();
  });

  it.each(["auto_approve", "auto_reject"] as const)(
    "%s: rule saved but the decision fails: resolves with ONE toast, 'Approval failed', never 'Rule save failed' nor 'rule saved'",
    async (action) => {
      const { run, decide, submitApproval, submitApprovalRule, toasts } = wire();
      submitApproval.mockRejectedValue(new Error("502"));

      await expect(run(action)).resolves.toBeUndefined();

      expect(submitApprovalRule).toHaveBeenCalledTimes(1);
      expect(decide).toHaveBeenCalledTimes(1);
      expect(titles(toasts)).toEqual(["Approval failed"]);
      expect(toasts[0].variant).toBe("destructive");
    },
  );

  it("a decide that rejects without toasting itself is not reported as a rule failure either", async () => {
    // applyAutoRule must not add its own toast for a decision failure: the decision path already reports it.
    const { deps, toasts, submitApprovalRule } = makeDeps();
    const decide = vi.fn(async () => {
      throw new Error("whatever");
    });

    await expect(
      applyAutoRule(deps, { runId: "run-1", requestId: "req-1", nodeUid: null, toolName: "write_file", action: "auto_approve" }, decide),
    ).resolves.toBeUndefined();

    expect(submitApprovalRule).toHaveBeenCalledTimes(1);
    expect(toasts.map((t) => t.title)).not.toContain("Rule save failed");
    expect(toasts.map((t) => t.title)).not.toContain("Auto-approve rule saved");
  });

  it.each([null, undefined, ""])("with %j as run id: resolves, nothing is sent, nothing is shown", async (runId) => {
    const { run, decide, submitApprovalRule, submitApproval, toasts } = wire(runId);

    await expect(run("auto_approve")).resolves.toBeUndefined();

    expect(submitApprovalRule).not.toHaveBeenCalled();
    expect(decide).not.toHaveBeenCalled();
    expect(submitApproval).not.toHaveBeenCalled();
    expect(toasts).toEqual([]);
  });

  it("the rule can be applied to a null node and a null tool (rule scoped on the other axis)", async () => {
    const { deps, submitApprovalRule } = makeDeps();
    const decide = vi.fn(async () => {});

    await applyAutoRule(deps, { runId: "run-1", requestId: "req-1", nodeUid: null, toolName: "write_file", action: "auto_approve" }, decide);

    expect(submitApprovalRule).toHaveBeenCalledWith({ sessionId: "run-1", nodeUid: null, toolName: "write_file", action: "auto_approve" });
  });
});
