package controller

import (
	"context"
	"testing"
	"time"

	"github.com/startxfr/unifai-operator/internal/unifai"
)

func TestKindOfMapsACategoryBackToItsKind(t *testing.T) {
	for kind, category := range unifai.KindCategory {
		if got := kindOf(category); unifai.KindCategory[got] != category {
			t.Errorf("kindOf(%q) = %q, want a kind of that category (e.g. %q)", category, got, kind)
		}
	}
	if got := kindOf("no-such-category"); got != "no-such-category" {
		t.Errorf("an unknown category is returned as is: %q", got)
	}
}

func TestMetricsTokenWithoutNamespaceDoesNothing(t *testing.T) {
	m := &MetricsToken{}
	if !m.NeedLeaderElection() {
		t.Error("only the leader writes the Secret")
	}
	done := make(chan error, 1)
	go func() { done <- m.Start(context.Background()) }()
	select {
	case err := <-done:
		if err != nil {
			t.Errorf("Start without a namespace returns nil, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Start without a namespace must return at once")
	}
}
