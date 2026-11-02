package controller

import (
	"context"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/utils/ptr"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/stack"
)

func stackReconcilerWith(t *testing.T, objs ...client.Object) *StackReconciler {
	t.Helper()
	s := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(s); err != nil {
		t.Fatal(err)
	}
	return &StackReconciler{Client: fake.NewClientBuilder().WithScheme(s).WithObjects(objs...).Build()}
}

func TestNetworkIsolated(t *testing.T) {
	st := &unifaiv1.UnifaiStack{}
	if !networkIsolated(st) {
		t.Error("isolation must be on by default")
	}
	st.Spec.Exposure.NetworkPolicy = ptr.To(false)
	if networkIsolated(st) {
		t.Error("explicit false ignored")
	}
	st.Spec.Exposure.NetworkPolicy = ptr.To(true)
	if !networkIsolated(st) {
		t.Error("explicit true ignored")
	}
}

func TestSecretDataAndConfigHash(t *testing.T) {
	sec := &corev1.Secret{Data: map[string][]byte{"a": []byte("1")}, StringData: map[string]string{"b": "2", "a": "3"}}
	got := secretData(sec)
	if string(got["a"]) != "3" || string(got["b"]) != "2" || len(got) != 2 {
		t.Errorf("StringData must override Data: %v", got)
	}

	cm := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: "c"}, Data: map[string]string{"k": "v"}}
	sc := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "s"}, StringData: map[string]string{"k": "v"}}
	h := configHash([]client.Object{cm, sc})
	if h == "" || h != configHash([]client.Object{sc, cm}) {
		t.Error("hash must not depend on the object order")
	}
	// The same secret as Data or StringData hashes the same: no rollout from the way it was built.
	sc2 := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "s"}, Data: map[string][]byte{"k": []byte("v")}}
	if h != configHash([]client.Object{cm, sc2}) {
		t.Error("Data and StringData must hash alike")
	}
	cm2 := cm.DeepCopy()
	cm2.Data["k"] = otherName
	if h == configHash([]client.Object{cm2, sc}) {
		t.Error("a changed ConfigMap did not change the hash")
	}
	// Objects that are neither a ConfigMap nor a Secret are not read by the pods.
	if h != configHash([]client.Object{cm, sc, &appsv1.Deployment{}}) {
		t.Error("a Deployment changed the hash")
	}
}

func TestLiveVolumes(t *testing.T) {
	r := stackReconcilerWith(t,
		&corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: "data", Namespace: "ns"},
			Spec: corev1.PersistentVolumeClaimSpec{StorageClassName: ptr.To("fast")}},
		&corev1.PersistentVolumeClaim{ObjectMeta: metav1.ObjectMeta{Name: "elsewhere", Namespace: otherName}},
		&appsv1.StatefulSet{ObjectMeta: metav1.ObjectMeta{Name: "mongodb", Namespace: "ns"},
			Spec: appsv1.StatefulSetSpec{VolumeClaimTemplates: []corev1.PersistentVolumeClaim{{ObjectMeta: metav1.ObjectMeta{Name: "db"}}}}},
	)
	pvcs, tpl, err := r.liveVolumes(context.Background(), "ns")
	if err != nil {
		t.Fatal(err)
	}
	if len(pvcs) != 1 || *pvcs["pvc/data"].StorageClassName != "fast" {
		t.Errorf("pvcs: %v", pvcs)
	}
	if _, ok := tpl["mongodb/db"]; !ok || len(tpl) != 1 {
		t.Errorf("templates: %v", tpl)
	}
}

func TestSeedFromExisting(t *testing.T) {
	r := stackReconcilerWith(t,
		&corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "multiagent-be-secret", Namespace: "ns"},
			Data: map[string][]byte{stack.KeyCredentialKey: []byte("cred"), stack.KeyOAuthState: nil, "unrelated": []byte("x")}},
	)
	data := map[string][]byte{}
	if err := r.seedFromExisting(context.Background(), "ns", data); err != nil {
		t.Fatal(err)
	}
	// Only the known non-empty keys are copied; a missing source Secret is skipped.
	if string(data[stack.KeyCredentialKey]) != "cred" || len(data) != 1 {
		t.Errorf("seeded: %v", data)
	}
	// An empty namespace seeds nothing.
	empty := map[string][]byte{}
	if err := r.seedFromExisting(context.Background(), "none", empty); err != nil || len(empty) != 0 {
		t.Errorf("empty: %v %v", empty, err)
	}
}

func TestClusterDomainOutsideOpenShift(t *testing.T) {
	// The Ingress config kind is unknown to the cluster: no domain, no error.
	if d := stackReconcilerWith(t).clusterDomain(context.Background()); d != "" {
		t.Errorf("domain = %q", d)
	}
}
