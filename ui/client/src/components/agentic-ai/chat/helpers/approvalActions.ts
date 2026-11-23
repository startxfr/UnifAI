// The approval actions of the chat (decide a HITL request, save an auto-rule), apart from ChatInterface so they can
// be tested with their dependencies injected (R-568 follow-up). No React here: ChatInterface wraps them in useCallback.
//
// decideApproval REJECTS after a failure (one toast first): ApprovalCard keeps the reason being typed only when the
// decision did not go through. applyAutoRule always RESOLVES: the card's auto-rule click has no catch.
import type { SubmitApprovalParams, SubmitApprovalRuleParams } from '@/api/sessions';
import type { ApprovalDecision, AutoRuleAction } from '../types';

export interface ApprovalToast {
  title: string;
  description?: string;
  variant?: 'destructive';
}

export interface ApprovalActionDeps {
  submitApproval: (params: SubmitApprovalParams) => Promise<unknown>;
  submitApprovalRule: (params: SubmitApprovalRuleParams) => Promise<unknown>;
  toast: (toast: ApprovalToast) => unknown;
}

export interface DecideApprovalParams {
  runId: string | null | undefined;
  requestId: string;
  decision: ApprovalDecision;
  feedback?: string;
  modifiedArgs?: Record<string, any>;
}

export interface AutoRuleParams {
  runId: string | null | undefined;
  requestId: string;
  nodeUid: string | null;
  toolName: string | null;
  action: AutoRuleAction;
}

export type DecideFn = (requestId: string, decision: ApprovalDecision, feedback?: string) => Promise<void>;

const APPROVAL_FAILED: ApprovalToast = {
  title: 'Approval failed',
  description: 'Could not submit your decision. Please try again.',
  variant: 'destructive',
};

const RULE_SAVE_FAILED: ApprovalToast = {
  title: 'Rule save failed',
  description: 'Could not save the rule. The request was not resolved.',
  variant: 'destructive',
};

/**
 * Submit a human decision. On failure (no run, or the request failed): one "Approval failed" toast, then the promise
 * rejects with the error. Once submitted, `onSubmitted` applies it to the UI (optimistic status); if that throws, the
 * decision has gone all the same: logged only, the promise resolves (a rejection would let the card send it twice).
 */
export async function decideApproval(
  deps: ApprovalActionDeps,
  { runId, requestId, decision, feedback, modifiedArgs }: DecideApprovalParams,
  onSubmitted?: () => void,
): Promise<void> {
  try {
    if (!runId) throw new Error('No run to submit the approval to');
    await deps.submitApproval({ sessionId: runId, requestId, decision, feedback, modifiedArgs });
  } catch (err) {
    console.error('Error submitting approval:', err);
    deps.toast(APPROVAL_FAILED);
    throw err;
  }
  try {
    onSubmitted?.();
  } catch (err) {
    console.error('Approval submitted, but the chat could not show it:', err);
  }
}

/**
 * Save an auto-approve / auto-reject rule, then resolve the current request with it. Always resolves, with at most one
 * toast: "Rule save failed" when the rule was not saved; nothing more when the rule was saved but the decision failed
 * (`decide` already said "Approval failed"); the "rule saved" toast when both went through.
 */
export async function applyAutoRule(
  deps: ApprovalActionDeps,
  { runId, requestId, nodeUid, toolName, action }: AutoRuleParams,
  decide: DecideFn,
): Promise<void> {
  if (!runId) return;

  try {
    await deps.submitApprovalRule({ sessionId: runId, nodeUid, toolName, action });
  } catch (err) {
    console.error('Failed to save auto-rule:', err);
    deps.toast(RULE_SAVE_FAILED);
    return;
  }

  const approve = action === 'auto_approve';
  try {
    await decide(requestId, approve ? 'approve' : 'reject', approve ? undefined : 'auto-reject rule applied');
  } catch {
    return; // the rule is saved; decide reported the failed decision
  }

  deps.toast({
    title: approve ? 'Auto-approve rule saved' : 'Auto-reject rule saved',
    description: 'Future matching requests will be resolved automatically.',
  });
}
