// R-568, first test of the UI (vitest + jsdom + testing-library): the Reject / Redirect input of an approval card and the
// reason typed in it survive a remount of the card (R-565, 0.1.75), per requestId.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ApprovalCard } from './ApprovalCard';
import { clearApprovalFeedback } from './approvalFeedbackStore';
import type { ApprovalEntry } from './types';

const REQUEST_IDS = ['req-a', 'req-b'];
const REASON_PLACEHOLDER = 'Reason for rejection...';

const approval = (requestId: string, status: ApprovalEntry['status'] = 'pending'): ApprovalEntry => ({
  requestId,
  toolName: 'echo',
  toolArgs: { text: 'hi' },
  toolDescription: 'Echo the text back',
  accessMode: 'write',
  originNodeUid: 'node-1',
  originNodeName: 'Agent One',
  status,
});

const card = (requestId: string, onDecision = vi.fn().mockResolvedValue(undefined), status: ApprovalEntry['status'] = 'pending') => (
  <ApprovalCard approval={approval(requestId, status)} sessionId="s1" onDecision={onDecision} />
);

afterEach(() => {
  cleanup();
  REQUEST_IDS.forEach(clearApprovalFeedback); // the store is module state: nothing leaks from a test to the next
});

describe('ApprovalCard keeps its Reject input by requestId', () => {
  it('shows the open input and the reason again after a remount, and the second Reject sends them', async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const first = render(card('req-a', onDecision));
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByPlaceholderText(REASON_PLACEHOLDER), 'trop risqué');
    first.unmount();

    render(card('req-a', onDecision));
    const field = screen.getByPlaceholderText(REASON_PLACEHOLDER) as HTMLTextAreaElement;
    expect(field.value).toBe('trop risqué');
    await user.click(screen.getByRole('button', { name: 'Reject' })); // the second Reject, the one that submits
    expect(onDecision).toHaveBeenCalledTimes(1);
    expect(onDecision).toHaveBeenCalledWith('req-a', 'reject', 'trop risqué');
  });

  it('starts again from the initial state after Cancel and a remount', async () => {
    const user = userEvent.setup();
    const first = render(card('req-a'));
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByPlaceholderText(REASON_PLACEHOLDER), 'à effacer');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    first.unmount();

    render(card('req-a'));
    expect(screen.queryByPlaceholderText(REASON_PLACEHOLDER)).toBeNull();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    expect((screen.getByPlaceholderText(REASON_PLACEHOLDER) as HTMLTextAreaElement).value).toBe('');
  });

  it('starts again from the initial state after a decision that went through', async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const first = render(card('req-a', onDecision));
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByPlaceholderText(REASON_PLACEHOLDER), 'non');
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    expect(onDecision).toHaveBeenCalledWith('req-a', 'reject', 'non');
    first.unmount();

    render(card('req-a', onDecision)); // still pending for the UI: no state is kept for a decided request
    expect(screen.queryByPlaceholderText(REASON_PLACEHOLDER)).toBeNull();
  });

  it('keeps the texts of two requests apart', async () => {
    const user = userEvent.setup();
    const a = render(card('req-a'));
    await user.click(within(a.container).getByRole('button', { name: 'Reject' }));
    await user.type(within(a.container).getByPlaceholderText(REASON_PLACEHOLDER), 'texte A');
    a.unmount();

    const b = render(card('req-b'));
    expect(within(b.container).queryByPlaceholderText(REASON_PLACEHOLDER)).toBeNull(); // B starts clean
    await user.click(within(b.container).getByRole('button', { name: 'Reject' }));
    await user.type(within(b.container).getByPlaceholderText(REASON_PLACEHOLDER), 'texte B');
    b.unmount();

    const again = render(card('req-a'));
    expect((within(again.container).getByPlaceholderText(REASON_PLACEHOLDER) as HTMLTextAreaElement).value).toBe('texte A');
    again.unmount();
    const bAgain = render(card('req-b'));
    expect((within(bAgain.container).getByPlaceholderText(REASON_PLACEHOLDER) as HTMLTextAreaElement).value).toBe('texte B');
  });

  it('forgets the input once the request is no longer pending', async () => {
    const user = userEvent.setup();
    const first = render(card('req-a'));
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByPlaceholderText(REASON_PLACEHOLDER), 'résolu ailleurs');
    first.rerender(card('req-a', undefined, 'rejected')); // timed out or answered from another tab
    expect(screen.getByText('Rejected')).toBeTruthy();
    first.unmount();

    render(card('req-a'));
    expect(screen.queryByPlaceholderText(REASON_PLACEHOLDER)).toBeNull();
  });

  it('keeps the reason and the buttons after a decision that fails, without an unhandled rejection', async () => {
    const user = userEvent.setup();
    const onDecision = vi.fn().mockRejectedValue(new Error('submit failed'));
    render(card('req-a', onDecision));
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByPlaceholderText(REASON_PLACEHOLDER), 'à réessayer');
    await user.click(screen.getByRole('button', { name: 'Reject' })); // fails: vitest fails the run on an unhandled rejection
    expect(onDecision).toHaveBeenCalledWith('req-a', 'reject', 'à réessayer');
    expect((screen.getByPlaceholderText(REASON_PLACEHOLDER) as HTMLTextAreaElement).value).toBe('à réessayer');
    expect((screen.getByRole('button', { name: 'Reject' }) as HTMLButtonElement).disabled).toBe(false); // retry possible
  });
});
