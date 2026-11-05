package controller

import (
	"context"
	"fmt"
	"strings"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/recorder"
	"sigs.k8s.io/yaml"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

// Agent lifecycle (zuno ADR-0584, WP-221): the states deprecated and retired of zuno.status, the revocation list and
// the audit events. A state change is a reviewed pull request on the bundle; the revocation list is the way to switch
// an agent off without a new release.
const (
	statusDeprecated = "deprecated"
	statusRetired    = "retired"

	// RevocationConfigMap is the platform-owned list, managed through GitOps in the bundles' namespace. The operator
	// reads it and never writes it. Its key "revoked" holds a YAML list of {bundle, reason, actor}. The operator only
	// watches the ConfigMaps labelled app.kubernetes.io/part-of=unifai (CacheByObject): label this one, or a change
	// takes effect at the next resync (10 minutes) instead of at once.
	RevocationConfigMap = "unifai-agent-revocations"
	revocationKey       = "revoked"

	// AnnotationActor and AnnotationReason are written by the promotion flow of the pull request that changed the
	// bundle (who approved it, why); the operator copies them into its Events and conditions.
	AnnotationActor  = "unifai.startx.fr/actor"
	AnnotationReason = "unifai.startx.fr/reason"
	unknownActor     = "unknown"

	reasonRevoked = "Revoked"
)

// revocation is one entry of the list.
type revocation struct {
	Bundle string `json:"bundle"`
	Reason string `json:"reason,omitempty"`
	Actor  string `json:"actor,omitempty"`
}

// parseRevocations reads the value of the key "revoked". An empty value is an empty list.
func parseRevocations(data string) ([]revocation, error) {
	var list []revocation
	if strings.TrimSpace(data) == "" {
		return nil, nil
	}
	if err := yaml.UnmarshalStrict([]byte(data), &list); err != nil {
		return nil, err
	}
	for i, e := range list {
		if strings.TrimSpace(e.Bundle) == "" {
			return nil, fmt.Errorf("entry %d has no bundle", i+1)
		}
	}
	return list, nil
}

// revocationOf is the entry that revokes the bundle, nil when it is not listed. A missing ConfigMap is an empty list;
// a list that cannot be read (API error, malformed) is an error: the caller must not admit anything on it (ADR-0584).
func (r *AgentBundleReconciler) revocationOf(ctx context.Context, cr *unifaiv1.UnifaiAgentBundle) (*revocation, error) {
	var cm corev1.ConfigMap
	if err := r.Get(ctx, types.NamespacedName{Namespace: cr.Namespace, Name: RevocationConfigMap}, &cm); err != nil {
		if apierrors.IsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("revocation list %s/%s: %w", cr.Namespace, RevocationConfigMap, err)
	}
	list, err := parseRevocations(cm.Data[revocationKey])
	if err != nil {
		return nil, fmt.Errorf("revocation list %s/%s key %q: %w", cr.Namespace, RevocationConfigMap, revocationKey, err)
	}
	for i := range list {
		if list[i].Bundle == cr.Name {
			return &list[i], nil
		}
	}
	return nil, nil
}

// actorOf and reasonOf read the annotations of the pull request flow; the actor is "unknown" when absent.
func actorOf(cr *unifaiv1.UnifaiAgentBundle) string {
	if a := strings.TrimSpace(cr.Annotations[AnnotationActor]); a != "" {
		return a
	}
	return unknownActor
}

func reasonOf(cr *unifaiv1.UnifaiAgentBundle) string {
	return strings.TrimSpace(cr.Annotations[AnnotationReason])
}

// admissionOf is the reason and status of a condition ("" when it is not set).
func admissionOf(conds []metav1.Condition, typ string) (reason string, ok bool) {
	c := meta.FindStatusCondition(conds, typ)
	if c == nil {
		return "", false
	}
	return c.Reason, c.Status == metav1.ConditionTrue
}

// audit records the Events of ADR-0584 clause 6 when the admission of the bundle changed: Admitted, StateChanged
// (deprecated, retired), Revoked, Rejected, each with the digest, the actor and the reason. It compares the Valid and
// Verified conditions before and after the reconcile, so a periodic resync in the same state stays silent.
// rec may be nil.
func audit(rec recorder.EventRecorder, cr *unifaiv1.UnifaiAgentBundle, before []metav1.Condition) {
	if rec == nil {
		return
	}
	now := cr.Status.Conditions
	validBefore, _ := admissionOf(before, ConditionValid)
	validNow, validOK := admissionOf(now, ConditionValid)
	verifiedBefore, _ := admissionOf(before, ConditionVerified)
	verifiedNow, verifiedOK := admissionOf(now, ConditionVerified)
	if validNow == validBefore && verifiedNow == verifiedBefore {
		return
	}
	detail := fmt.Sprintf("digest %s, actor %s", cr.Status.BundleDigest, actorOf(cr))
	if reason := reasonOf(cr); reason != "" {
		detail += ", reason: " + reason
	}
	c := meta.FindStatusCondition(now, ConditionValid)
	switch {
	case validNow == reasonRevoked:
		record(rec, cr, corev1.EventTypeWarning, reasonRevoked, c.Message)
	case validNow == "Deprecated" || validNow == "Retired":
		typ := corev1.EventTypeNormal
		if validNow == "Retired" {
			typ = corev1.EventTypeWarning
		}
		record(rec, cr, typ, "StateChanged", fmt.Sprintf("%s: %s (%s)", validNow, c.Message, detail))
	case !verifiedOK && verifiedNow != "":
		record(rec, cr, corev1.EventTypeWarning, "Rejected", fmt.Sprintf("bundle not verified (%s): %s", verifiedNow, detail))
	case c != nil && !validOK:
		record(rec, cr, corev1.EventTypeWarning, "Rejected", fmt.Sprintf("%s: %s (%s)", validNow, c.Message, detail))
	case validOK && validNow == "Valid":
		record(rec, cr, corev1.EventTypeNormal, "Admitted", fmt.Sprintf("%s (%s)", c.Message, detail))
	case validOK:
		record(rec, cr, corev1.EventTypeNormal, "StateChanged", fmt.Sprintf("%s: %s (%s)", validNow, c.Message, detail))
	}
}

// withReason is ", reason: <annotation>" when the pull request gave one.
func withReason(cr *unifaiv1.UnifaiAgentBundle) string {
	if r := reasonOf(cr); r != "" {
		return ", reason: " + r
	}
	return ""
}

// condFunc sets one condition of the reconcile in progress.
type condFunc func(typ string, ok bool, reason, msg string)

// checkRevocation withdraws a bundle the platform's revocation list names, whatever the bundle says: nothing it
// emitted stays. An unreadable list admits nothing new and leaves what is emitted as it is. A nil result means the
// bundle is not revoked and the reconcile goes on.
func (r *AgentBundleReconciler) checkRevocation(ctx context.Context, cr *unifaiv1.UnifaiAgentBundle, cond condFunc) error {
	st := &cr.Status
	revoked, err := r.revocationOf(ctx, cr)
	if err != nil {
		cond(ConditionValid, false, "RevocationListUnreadable", err.Error())
		return permanent("revocation list unreadable, nothing admitted: %v", err)
	}
	if revoked == nil {
		return nil
	}
	reason, actor := strings.TrimSpace(revoked.Reason), strings.TrimSpace(revoked.Actor)
	if reason == "" {
		reason = "no reason given in the revocation list" // a revocation always takes effect
	}
	if actor == "" {
		actor = unknownActor
	}
	msg := fmt.Sprintf("revoked by the platform: %s (actor %s)", reason, actor)
	if err := r.prune(ctx, cr, nil); err != nil {
		return err
	}
	st.Children, st.Tasks, st.Agent, st.PrimaryTask, st.Display = nil, nil, "", "", nil
	cond(ConditionValid, false, reasonRevoked, msg)
	cond(ConditionEmitted, false, reasonRevoked, msg)
	return &notServedError{msg: msg}
}

// retire handles zuno.status retired (ADR-0584 clause 3): no entry and no objects; a state change always has a reason.
func (r *AgentBundleReconciler) retire(ctx context.Context, cr *unifaiv1.UnifaiAgentBundle, cond condFunc) error {
	st := &cr.Status
	if reasonOf(cr) == "" {
		cond(ConditionValid, false, "MissingReason", "zuno.status is retired: set the annotation "+AnnotationReason+" (the pull request that retires the agent says why)")
		return permanent("retired agent without the annotation %s, nothing changed", AnnotationReason)
	}
	if err := r.prune(ctx, cr, nil); err != nil {
		return err
	}
	st.Children, st.Tasks, st.Agent, st.PrimaryTask, st.Display = nil, nil, "", "", nil
	cond(ConditionValid, true, "Retired", "zuno.status is retired: "+reasonOf(cr))
	cond(ConditionEmitted, false, "Retired", "retired agent: no entry, no objects")
	return &notServedError{msg: "retired: " + reasonOf(cr)}
}
