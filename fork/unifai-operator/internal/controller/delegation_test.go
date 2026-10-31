package controller

import (
	"context"
	"encoding/json"
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
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
	forged.OwnerReferences[0].UID = "other"
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
	bp := delegatingBlueprint("c", "orch", "agent", a2aNodes(&unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}, "tekos", "answer",
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
