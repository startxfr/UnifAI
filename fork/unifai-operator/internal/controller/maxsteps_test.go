package controller

import (
	"strings"
	"testing"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/okf"
)

func TestCheckCeilingsBoundsMaxSteps(t *testing.T) {
	b := &okf.Bundle{Classification: okf.C2, MaxSteps: 20,
		Tasks: []okf.Task{{Name: "answer"}, {Name: "deep", MaxSteps: 60}}}
	cr := &unifaiv1.UnifaiAgentBundle{Spec: unifaiv1.UnifaiAgentBundleSpec{Ceilings: unifaiv1.BundleCeilings{MinClassification: "C1"}}}

	err := checkCeilings(cr, b)
	if err == nil || !strings.Contains(err.Error(), "task deep: max_steps 60 is above maxSteps 50") {
		t.Fatalf("default ceiling 50: %v", err)
	}
	cr.Spec.Ceilings.MaxSteps = 60
	if err := checkCeilings(cr, b); err != nil {
		t.Fatalf("within maxSteps 60: %v", err)
	}
	cr.Spec.Ceilings.MaxSteps = 10
	if err := checkCeilings(cr, b); err == nil || !strings.Contains(err.Error(), "task answer: max_steps 20") {
		t.Fatalf("agent-level steps above the ceiling: %v", err)
	}
}
