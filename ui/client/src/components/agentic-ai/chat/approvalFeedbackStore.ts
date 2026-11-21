// Feedback state of the approval cards (Reject / Redirect input), kept per approval requestId outside the
// component: the chat may unmount and remount a card while it is pending, and the reason being typed must survive
// (R-565). Plain module store, no React import: ApprovalCard reads it with useSyncExternalStore.

export type ApprovalFeedbackMode = 'reject' | 'redirect';

export interface ApprovalFeedbackState {
  mode: ApprovalFeedbackMode | null;
  text: string;
}

// One shared empty snapshot: useSyncExternalStore needs the same reference while nothing changed.
const EMPTY: ApprovalFeedbackState = Object.freeze({ mode: null, text: '' });

const entries = new Map<string, ApprovalFeedbackState>();
const listeners = new Set<() => void>();

const emit = () => listeners.forEach((listener) => listener());

export function getApprovalFeedback(requestId: string): ApprovalFeedbackState {
  return entries.get(requestId) ?? EMPTY;
}

export function setApprovalFeedback(requestId: string, patch: Partial<ApprovalFeedbackState>): void {
  const next = { ...getApprovalFeedback(requestId), ...patch };
  if (next.mode === null && next.text === '') {
    // Back to empty: drop the entry, so the Map only holds cards with something to keep.
    if (!entries.delete(requestId)) return;
  } else {
    entries.set(requestId, next);
  }
  emit();
}

export function clearApprovalFeedback(requestId: string): void {
  if (entries.delete(requestId)) emit();
}

export function subscribeApprovalFeedback(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
