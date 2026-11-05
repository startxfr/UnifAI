package controller

import (
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/recorder"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

func TestParseRevocations(t *testing.T) {
	list, err := parseRevocations("- bundle: tekos\n  reason: incident\n  actor: bob\n- bundle: arkos\n")
	if err != nil || len(list) != 2 || list[0].Bundle != "tekos" || list[0].Actor != "bob" || list[1].Reason != "" {
		t.Fatalf("list %v err %v", list, err)
	}
	for _, empty := range []string{"", "  \n", "[]"} {
		if l, err := parseRevocations(empty); err != nil || len(l) != 0 {
			t.Errorf("%q is an empty list: %v %v", empty, l, err)
		}
	}
	for _, bad := range []string{"- bundle: tekos\n  oops: 1\n", "- reason: no bundle\n", "not: a list\n", "- [x]\n"} {
		if _, err := parseRevocations(bad); err == nil {
			t.Errorf("%q must be refused, an unreadable list blocks admissions", bad)
		}
	}
}

func TestActorDefaultsToUnknown(t *testing.T) {
	cr := &unifaiv1.UnifaiAgentBundle{}
	if actorOf(cr) != "unknown" || reasonOf(cr) != "" {
		t.Errorf("%q %q", actorOf(cr), reasonOf(cr))
	}
	cr.Annotations = map[string]string{AnnotationActor: " alice ", AnnotationReason: "why"}
	if actorOf(cr) != "alice" || reasonOf(cr) != "why" {
		t.Errorf("%q %q", actorOf(cr), reasonOf(cr))
	}
}

type fakeRecorder struct {
	recorder.EventRecorder
	events []string
}

func (f *fakeRecorder) Eventf(_ runtime.Object, _ runtime.Object, typ, reason, _ string, format string, args ...any) {
	f.events = append(f.events, typ+"/"+reason)
}

func TestAuditRecordsAdmissionChangesOnly(t *testing.T) {
	cr := &unifaiv1.UnifaiAgentBundle{}
	cr.Annotations = map[string]string{AnnotationActor: "alice", AnnotationReason: "r"}
	cr.Status.BundleDigest = "sha256:abc"
	set := func(typ, reason string, ok bool, msg string) {
		s := metav1.ConditionFalse
		if ok {
			s = metav1.ConditionTrue
		}
		meta.SetStatusCondition(&cr.Status.Conditions, metav1.Condition{Type: typ, Status: s, Reason: reason, Message: msg})
	}
	rec := &fakeRecorder{}
	step := func(valid string, ok bool) []string {
		before := append([]metav1.Condition(nil), cr.Status.Conditions...)
		set(ConditionVerified, "SignatureValid", true, "signed")
		set(ConditionValid, valid, ok, "msg")
		rec.events = nil
		audit(rec, cr, before)
		return rec.events
	}
	if got := step("Valid", true); strings.Join(got, ",") != corev1.EventTypeNormal+"/Admitted" {
		t.Errorf("first admission: %v", got)
	}
	if got := step("Valid", true); len(got) != 0 {
		t.Errorf("a resync in the same state is silent: %v", got)
	}
	if got := step("Deprecated", true); strings.Join(got, ",") != "Normal/StateChanged" {
		t.Errorf("deprecated: %v", got)
	}
	if got := step("Retired", true); strings.Join(got, ",") != "Warning/StateChanged" {
		t.Errorf("retired: %v", got)
	}
	if got := step(reasonRevoked, false); strings.Join(got, ",") != "Warning/Revoked" {
		t.Errorf("revoked: %v", got)
	}
	if got := step("SchemaInvalid", false); strings.Join(got, ",") != "Warning/Rejected" {
		t.Errorf("rejected: %v", got)
	}
	audit(nil, cr, nil) // no recorder: nothing, no panic
}
