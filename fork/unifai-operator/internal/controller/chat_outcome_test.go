package controller

import "testing"

func TestChatOutcomeIdentityError(t *testing.T) {
	bad := `{"messages":[{"content":"no identity binding for session s1 not submitted by a signed-in user"}]}`
	if p, m := chatOutcome(PhaseCompleted, "COMPLETED", bad); p != PhaseFailed || m == "session COMPLETED" {
		t.Fatalf("identity error must fail the chat, got %s %q", p, m)
	}
	if p, m := chatOutcome(PhaseCompleted, "COMPLETED", `{"messages":[{"content":"hello"}]}`); p != PhaseCompleted || m != "session COMPLETED" {
		t.Fatalf("normal chat unchanged, got %s %q", p, m)
	}
	if p, _ := chatOutcome(PhaseFailed, "ERROR", bad); p != PhaseFailed {
		t.Fatalf("failed stays failed, got %s", p)
	}
}
