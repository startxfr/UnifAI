package controller

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/okf"
	"github.com/startxfr/unifai-operator/internal/unifai"
)

func TestBundleMayDelegate(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = unifaiv1.AddToScheme(scheme)
	cr := &unifaiv1.UnifaiAgentBundle{ObjectMeta: metav1.ObjectMeta{Name: "tekos", Namespace: "ns", UID: "u1"},
		Spec:   unifaiv1.UnifaiAgentBundleSpec{Delegation: &unifaiv1.BundleDelegation{GatewayURL: "http://gw.zuno-ai-run.svc:8080/"}},
		Status: unifaiv1.UnifaiAgentBundleStatus{Verified: true}}
	c := fake.NewClientBuilder().WithScheme(scheme).WithObjects(cr).Build()
	owned := func() *unifaiv1.UnifaiWorkflow {
		return &unifaiv1.UnifaiWorkflow{ObjectMeta: metav1.ObjectMeta{Name: "tekos", Namespace: "ns", OwnerReferences: []metav1.OwnerReference{
			{Kind: "UnifaiAgentBundle", Name: "tekos", UID: "u1", Controller: ptr.To(true)}}}}
	}
	ctx := context.Background()
	if prefix, ok := bundleMayDelegate(ctx, c, owned()); !ok || prefix != "http://gw.zuno-ai-run.svc:8080/agents/" {
		t.Fatalf("owned by a delegating bundle: %q %v", prefix, ok)
	}
	forged := owned()
	forged.OwnerReferences[0].UID = otherName
	if _, ok := bundleMayDelegate(ctx, c, forged); ok {
		t.Error("an owner reference with another UID is accepted")
	}
	if _, ok := bundleMayDelegate(ctx, c, &unifaiv1.UnifaiWorkflow{ObjectMeta: metav1.ObjectMeta{Name: "free", Namespace: "ns"}}); ok {
		t.Error("a free-form workflow may delegate")
	}
	cr.Spec.Delegation = nil
	c = fake.NewClientBuilder().WithScheme(scheme).WithObjects(cr).Build()
	if _, ok := bundleMayDelegate(ctx, c, owned()); ok {
		t.Error("a bundle without spec.delegation may delegate")
	}
}

func TestA2ABaseURLs(t *testing.T) {
	bp := delegatingBlueprint("c", "orch", []string{"agent"}, 0, a2aNodes(&unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}, "tekos", "answer", 0,
		[]delegationTarget{{Agent: "arkos", Task: "draft"}, {Agent: "comage", Task: "check"}}))
	got := a2aBaseURLs(normalise(t, bp))
	if len(got) != 2 || got[0] != "http://gw:8080/agents/arkos" || got[1] != "http://gw:8080/agents/comage" {
		t.Fatalf("base urls %v", got)
	}
}

// normalise round-trips a value through JSON, as the controller sees a resolved blueprint.
func normalise(t *testing.T, v any) any {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestSourceAlreadyGone(t *testing.T) {
	gone := &unifai.APIError{Status: 500, Body: `{"status":"error","results":{"succeeded":[],"failed":[{"pipeline_id":"x","error":"Source not found"}]}}`}
	if !sourceAlreadyGone(gone) {
		t.Error("a stale source id is not taken as deleted")
	}
	for _, err := range []error{
		&unifai.APIError{Status: 500, Body: `{"results":{"succeeded":[],"failed":[{"error":"qdrant unreachable"}]}}`},
		&unifai.APIError{Status: 502, Body: `{"results":{"failed":[{"error":"Source not found"}]}}`},
		&unifai.APIError{Status: 500, Body: "Internal Server Error"},
	} {
		if sourceAlreadyGone(err) {
			t.Errorf("%v taken as deleted", err)
		}
	}
}

func TestChildrenBelongToTheInstanceOfTheirBundle(t *testing.T) {
	cr := &unifaiv1.UnifaiAgentBundle{ObjectMeta: metav1.ObjectMeta{Name: "tekos", Namespace: "ns",
		Labels: map[string]string{InstanceLabel: "canary"}}}
	got := childMeta(cr, "tekos-llm").Labels
	if got[InstanceLabel] != "canary" || got[unifaiv1.AgentBundleLabel] != "tekos" {
		t.Errorf("child labels %v", got)
	}
	cr.Labels = nil
	if _, ok := childMeta(cr, "tekos-llm").Labels[InstanceLabel]; ok {
		t.Error("a bundle of the default instance gets children with an instance label")
	}
}

const (
	stepOrchestrate = "orchestrate"
	stepAgent       = "agent"
	otherName       = "other"
	tekosNode       = "a2a-tekos"
)

func TestDelegatingBlueprintShapes(t *testing.T) {
	a2a := a2aNodes(&unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}, "arkos", "draft", 0, []delegationTarget{{Agent: "tekos", Task: "answer"}})
	stepsOf := func(bp map[string]any) map[string]map[string]any {
		out := map[string]map[string]any{}
		for _, s := range normalise(t, bp["plan"]).([]any) {
			m := s.(map[string]any)
			out[m["uid"].(string)] = m
		}
		return out
	}

	// retrieve_reason_respond: the single stage is coordinated by the orchestrator; it branches to its workers and to
	// the answer, and the workers return to it.
	one := stepsOf(delegatingBlueprint("c", "orch", []string{"t"}, 0, a2a))
	if one["ask"]["branches"].(map[string]any)[stepAgent] != stepOrchestrate {
		t.Errorf("the question must lead to the orchestrator: %v", one["ask"])
	}
	assertOrchestratorWiring(t, one, nil, []string{stepAgent, tekosNode}, "finish")
	if one["finish"]["after"] != nil {
		t.Errorf("the answer is reached by the orchestrator's branch, got after %v", one["finish"]["after"])
	}

	// plan_draft_write: plan -> orchestrator -> (draft | A2A) -> write -> answer.
	three := stepsOf(delegatingBlueprint("c", "orch", []string{"t-plan", "t-draft", "t-write"}, 1, a2a))
	if three["ask"]["branches"].(map[string]any)[stepAgent] != stepAgent || three[stepAgent]["after"] != nil {
		t.Errorf("the question must lead to the plan stage: %v", three["ask"])
	}
	assertOrchestratorWiring(t, three, []string{stepAgent}, []string{"agent-2", tekosNode}, "agent-3")
	if three["agent-3"]["after"] != nil {
		t.Errorf("the write stage is reached by the orchestrator's branch, got after %v", three["agent-3"]["after"])
	}
	if three["finish"]["after"] != "agent-3" {
		t.Errorf("finish after %v", three["finish"]["after"])
	}
}

// assertOrchestratorWiring checks the wiring the engine's validators expect of an orchestrator (R-525): it waits for the
// stage before it and for its workers (their return path: a worker replies only to a successor, 0.1.50 lost the A2A
// answer), delegates by BRANCH to every worker and to the next node, and no other step waits for a worker (a path from
// a worker to the output that avoids the orchestrator makes it undelegable, 0.1.49: "Node a2a-tekos is not adjacent").
func assertOrchestratorWiring(t *testing.T, steps map[string]map[string]any, before, workers []string, next string) {
	t.Helper()
	afterOf := func(uid string) []any {
		switch a := steps[uid]["after"].(type) {
		case string:
			return []any{a}
		case []any:
			return a
		}
		return nil
	}
	want := map[any]bool{}
	for _, u := range append(append([]string{}, before...), workers...) {
		want[u] = true
	}
	got := afterOf(stepOrchestrate)
	if len(got) != len(want) {
		t.Errorf("the orchestrator waits for %v, want the previous stages %v and the workers %v", got, before, workers)
	}
	for _, a := range got {
		if !want[a] {
			t.Errorf("the orchestrator waits for the unexpected step %v", a)
		}
	}
	branches, _ := steps[stepOrchestrate]["branches"].(map[string]any)
	for _, target := range append(append([]string{}, workers...), next) {
		if branches[target] != target {
			t.Errorf("the orchestrator does not branch to %s: %v", target, branches)
		}
	}
	if len(branches) != len(workers)+1 {
		t.Errorf("unexpected orchestrator branches: %v", branches)
	}
	if steps[stepOrchestrate]["exit_condition"] == nil {
		t.Error("the orchestrator needs its router_direct exit_condition")
	}
	for _, w := range workers {
		if steps[w]["after"] != nil {
			t.Errorf("worker %s is reached by the orchestrator's branch, got after %v", w, steps[w]["after"])
		}
	}
	for uid := range steps {
		if uid == stepOrchestrate {
			continue
		}
		for _, a := range afterOf(uid) {
			for _, w := range workers {
				if a == w {
					t.Errorf("step %s waits for the worker %s, which would make it undelegable", uid, w)
				}
			}
		}
	}
}

// The orchestrator calls delegate_task with a node uid of the blueprint: the prompt must give those uids, not the
// agent names or task keys (0.1.48: "Node tekos is not adjacent, or the uid is wrong").
func TestOrchestratorPromptNamesTheNodeUIDs(t *testing.T) {
	cr := &unifaiv1.UnifaiAgentBundle{Spec: unifaiv1.UnifaiAgentBundleSpec{Delegation: &unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}}}
	targets := []delegationTarget{{Agent: "tekos", Task: "answer-technical-question", Title: "Tekos", Description: "Technical consultant"}}
	cfg := orchestratorConfig(cr, &okf.Bundle{Name: "arkos"}, okf.Task{Name: "write-code"}, "arkos-write-code", stageUID(1), targets)
	msg, _ := cfg["system_message"].(string)
	for _, want := range []string{"dst_uid", "REMOTE work item", "`agent-2`", "`a2a-tekos` Tekos (tekos/answer-technical-question)"} {
		if !strings.Contains(msg, want) {
			t.Errorf("system message lacks %q:\n%s", want, msg)
		}
	}
	if targets[0].nodeUID() != tekosNode {
		t.Errorf("node uid %q", targets[0].nodeUID())
	}
}

func TestA2ANodeCarriesTheGenerationCeiling(t *testing.T) {
	headers := func(maxTokens int) map[string]any {
		nodes := a2aNodes(&unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}, "arkos", "draft", maxTokens, []delegationTarget{{Agent: "tekos", Task: "answer"}})
		return nodes[0]["config"].(map[string]any)["additional_headers"].(map[string]any)
	}
	if h := headers(2048); h[headerMaxTokens] != "2048" {
		t.Errorf("a declared ceiling follows the hop: %v", h)
	}
	if h := headers(0); h[headerMaxTokens] != nil {
		t.Errorf("no declared ceiling, no header (existing blueprints keep their hash): %v", h)
	}
}
