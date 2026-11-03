package controller

import (
	"context"
	"testing"

	batchv1 "k8s.io/api/batch/v1"
	rbacv1 "k8s.io/api/rbac/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/utils/ptr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/stack"
)

const (
	stackNS      = "ns"
	phasePaused  = "Paused"
	condReady    = "Ready"
	phaseErrored = "Error"
)

// stackReconcilerFake is a StackReconciler on a fake client that knows the UnifaiStack kind and its status subresource.
func stackReconcilerFake(t *testing.T, objs ...client.Object) *StackReconciler {
	t.Helper()
	s := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	if err := unifaiv1.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	c := fake.NewClientBuilder().WithScheme(s).WithObjects(objs...).WithStatusSubresource(&unifaiv1.UnifaiStack{}).Build()
	return &StackReconciler{Client: c}
}

func newStack(name string) *unifaiv1.UnifaiStack {
	return &unifaiv1.UnifaiStack{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: stackNS, Generation: 3}}
}

func reconcileStack(t *testing.T, r *StackReconciler, name string) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{NamespacedName: types.NamespacedName{Namespace: stackNS, Name: name}})
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
	return res
}

func getStack(t *testing.T, r *StackReconciler, name string) *unifaiv1.UnifaiStack {
	t.Helper()
	st := &unifaiv1.UnifaiStack{}
	if err := r.Get(context.Background(), types.NamespacedName{Namespace: stackNS, Name: name}, st); err != nil {
		t.Fatal(err)
	}
	return st
}

func TestReconcileStackMissingIsIgnored(t *testing.T) {
	r := stackReconcilerFake(t)
	if res := reconcileStack(t, r, unifaiv1.StackName); res != (ctrl.Result{}) {
		t.Errorf("a deleted stack must not requeue: %+v", res)
	}
}

func TestReconcileStackWrongNameIsNotTouched(t *testing.T) {
	r := stackReconcilerFake(t, newStack(otherName))
	reconcileStack(t, r, otherName)
	st := getStack(t, r, otherName)
	if controllerutil.ContainsFinalizer(st, Finalizer) || st.Status.Phase != "" {
		t.Errorf("a stack not named %q must be left alone: finalizers %v, phase %q", unifaiv1.StackName, st.Finalizers, st.Status.Phase)
	}
}

func TestReconcilePausedStackKeepsFinalizerAndReportsPaused(t *testing.T) {
	st := newStack(unifaiv1.StackName)
	st.Spec.Paused = true
	r := stackReconcilerFake(t, st)
	if res := reconcileStack(t, r, unifaiv1.StackName); res != (ctrl.Result{}) {
		t.Errorf("a paused stack must not requeue: %+v", res)
	}
	got := getStack(t, r, unifaiv1.StackName)
	if !controllerutil.ContainsFinalizer(got, Finalizer) {
		t.Error("the finalizer is added before anything is deployed")
	}
	if got.Status.Phase != phasePaused || got.Status.ObservedGeneration != 3 {
		t.Errorf("status: phase %q generation %d", got.Status.Phase, got.Status.ObservedGeneration)
	}
	if c := meta.FindStatusCondition(got.Status.Conditions, condReady); c == nil || c.Status != metav1.ConditionFalse || c.Reason != phasePaused {
		t.Errorf("Ready condition: %+v", c)
	}
}

func TestReconcileDeletingStackWithoutFinalizerIsNoop(t *testing.T) {
	st := newStack(unifaiv1.StackName)
	st.Finalizers = []string{"other.example.com/keep"} // the fake client refuses a deleted object that has no finalizer
	r := stackReconcilerFake(t, st)
	if err := r.Delete(context.Background(), st); err != nil {
		t.Fatal(err)
	}
	if res := reconcileStack(t, r, unifaiv1.StackName); res != (ctrl.Result{}) {
		t.Errorf("not our finalizer: nothing to do, got %+v", res)
	}
	if got := getStack(t, r, unifaiv1.StackName); got.Status.Phase != "" {
		t.Errorf("the stack must not be touched, phase %q", got.Status.Phase)
	}
}

func TestSetStatusNetworkIsolationCondition(t *testing.T) {
	for _, tc := range []struct {
		name   string
		policy *bool
		want   metav1.ConditionStatus
		reason string
	}{
		{"default", nil, metav1.ConditionTrue, "NetworkPolicy"},
		{"disabled", ptr.To(false), metav1.ConditionFalse, "Disabled"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			st := newStack(unifaiv1.StackName)
			st.Spec.Exposure.NetworkPolicy = tc.policy
			r := stackReconcilerFake(t, st)
			if err := r.setStatus(context.Background(), st, condReady, "all good", metav1.ConditionTrue, condReady); err != nil {
				t.Fatal(err)
			}
			got := getStack(t, r, unifaiv1.StackName)
			c := meta.FindStatusCondition(got.Status.Conditions, "NetworkIsolated")
			if c == nil || c.Status != tc.want || c.Reason != tc.reason {
				t.Errorf("NetworkIsolated: %+v", c)
			}
			if rd := meta.FindStatusCondition(got.Status.Conditions, condReady); rd == nil || rd.Status != metav1.ConditionTrue {
				t.Errorf("Ready: %+v", rd)
			}
			if got.Status.OperatorVersion != OperatorVersion {
				t.Errorf("operator version %q", got.Status.OperatorVersion)
			}
		})
	}
}

func TestSetStatusTruncatesTheMessage(t *testing.T) {
	st := newStack(unifaiv1.StackName)
	r := stackReconcilerFake(t, st)
	long := make([]byte, 5000)
	for i := range long {
		long[i] = 'x'
	}
	if err := r.setStatus(context.Background(), st, phaseErrored, string(long), metav1.ConditionFalse, phaseErrored); err != nil {
		t.Fatal(err)
	}
	if n := len(getStack(t, r, unifaiv1.StackName).Status.Message); n > 1100 {
		t.Errorf("message not truncated: %d bytes", n)
	}
}

func TestDeleteTokenReviewBinding(t *testing.T) {
	crb := &rbacv1.ClusterRoleBinding{ObjectMeta: metav1.ObjectMeta{Name: stack.RAGTokenReviewBindingName(stackNS)}}
	r := stackReconcilerFake(t, crb)
	if err := r.deleteTokenReviewBinding(context.Background(), stackNS); err != nil {
		t.Fatal(err)
	}
	err := r.Get(context.Background(), types.NamespacedName{Name: crb.Name}, &rbacv1.ClusterRoleBinding{})
	if !apierrors.IsNotFound(err) {
		t.Errorf("binding still there: %v", err)
	}
	// Deleting it again, or one that never existed, is not an error.
	if err := r.deleteTokenReviewBinding(context.Background(), stackNS); err != nil {
		t.Errorf("second delete: %v", err)
	}
}

func TestReconcileTokenReview(t *testing.T) {
	ctx := context.Background()
	r := stackReconcilerFake(t)
	p := &stack.Plan{Namespace: stackNS, Spec: &unifaiv1.UnifaiStackSpec{}}
	name := types.NamespacedName{Name: stack.RAGTokenReviewBindingName(stackNS)}

	// Off: nothing exists and nothing fails.
	if err := r.reconcileTokenReview(ctx, p); err != nil {
		t.Fatal(err)
	}
	if err := r.Get(ctx, name, &rbacv1.ClusterRoleBinding{}); !apierrors.IsNotFound(err) {
		t.Fatalf("binding created while tokenReview is off: %v", err)
	}

	// On: created, then patched (not failing) on the next pass.
	p.Spec.RAG.TokenReview = true
	for i := 0; i < 2; i++ {
		if err := r.reconcileTokenReview(ctx, p); err != nil {
			t.Fatalf("pass %d: %v", i, err)
		}
	}
	crb := &rbacv1.ClusterRoleBinding{}
	if err := r.Get(ctx, name, crb); err != nil {
		t.Fatal(err)
	}
	if crb.RoleRef.Name != "system:auth-delegator" || len(crb.Subjects) != 1 || crb.Subjects[0].Namespace != stackNS {
		t.Errorf("binding: %+v %+v", crb.RoleRef, crb.Subjects)
	}

	// Off again: removed.
	p.Spec.RAG.TokenReview = false
	if err := r.reconcileTokenReview(ctx, p); err != nil {
		t.Fatal(err)
	}
	if err := r.Get(ctx, name, &rbacv1.ClusterRoleBinding{}); !apierrors.IsNotFound(err) {
		t.Errorf("binding kept after tokenReview was turned off: %v", err)
	}
}

func TestReconcileBackupsRemovesTheCronJobsWhenUnset(t *testing.T) {
	ctx := context.Background()
	objs := make([]client.Object, 0, len(stack.BackupNames)+1)
	for _, n := range stack.BackupNames {
		objs = append(objs, &batchv1.CronJob{ObjectMeta: metav1.ObjectMeta{Name: n, Namespace: stackNS}})
	}
	keep := &batchv1.CronJob{ObjectMeta: metav1.ObjectMeta{Name: "someone-elses", Namespace: stackNS}}
	r := stackReconcilerFake(t, append(objs, keep)...)
	st := newStack(unifaiv1.StackName)
	p := &stack.Plan{Namespace: stackNS, Spec: &st.Spec}
	if err := r.reconcileBackups(ctx, st, p); err != nil {
		t.Fatal(err)
	}
	for _, n := range stack.BackupNames {
		if err := r.Get(ctx, types.NamespacedName{Namespace: stackNS, Name: n}, &batchv1.CronJob{}); !apierrors.IsNotFound(err) {
			t.Errorf("%s kept without spec.backup: %v", n, err)
		}
	}
	if err := r.Get(ctx, types.NamespacedName{Namespace: stackNS, Name: keep.Name}, &batchv1.CronJob{}); err != nil {
		t.Errorf("a CronJob the operator does not own was deleted: %v", err)
	}
}

func TestLegacyReleasesAreTheHelmfileDummies(t *testing.T) {
	// removeLegacyReleases must never be pointed at a release the operator installs itself.
	managed := map[string]bool{}
	for _, rel := range stack.Releases {
		managed[rel.Name] = true
	}
	for _, n := range legacyReleases {
		if managed[n] {
			t.Errorf("legacy release %q is also a managed release", n)
		}
	}
}
