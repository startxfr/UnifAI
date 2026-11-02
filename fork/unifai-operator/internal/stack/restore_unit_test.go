package stack

import (
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

func TestRestoreSource(t *testing.T) {
	own := &unifaiv1.BackupS3Spec{Bucket: "mine", Prefix: "/a/b/"}
	st := &unifaiv1.UnifaiStack{Spec: unifaiv1.UnifaiStackSpec{Backup: &unifaiv1.BackupSpec{S3: unifaiv1.BackupS3Spec{Bucket: "bk"}}}}

	// spec.source wins over the stack's backup; slashes around the prefix are trimmed.
	src, base, err := RestoreSource("ns", st, &unifaiv1.UnifaiRestore{Spec: unifaiv1.UnifaiRestoreSpec{Source: own}})
	if err != nil || src != own || base != "s3://mine/a/b" {
		t.Errorf("explicit source: %v %q %v", src, base, err)
	}
	// No prefix: the default is unifai/<namespace>.
	if _, base, err = RestoreSource("ns", st, &unifaiv1.UnifaiRestore{}); err != nil || base != "s3://bk/unifai/ns" {
		t.Errorf("stack backup: %q %v", base, err)
	}
	// Neither a source nor a stack backup is an error.
	if _, _, err = RestoreSource("ns", &unifaiv1.UnifaiStack{}, &unifaiv1.UnifaiRestore{}); err == nil {
		t.Error("no source at all was accepted")
	}
}

func TestRestoreJob(t *testing.T) {
	p := &Plan{Namespace: "ns", Spec: &unifaiv1.UnifaiStackSpec{}}
	r := &unifaiv1.UnifaiRestore{}
	r.Name = "r1"
	src := &unifaiv1.BackupS3Spec{Bucket: "b", CredentialsSecret: "creds", Endpoint: "https://s3"}

	job := RestoreJob(p, r, src, "s3://b/p", "fp")
	if job.Name != RestoreJobName("r1") || job.Name != "unifai-restore-r1" || job.Namespace != "ns" {
		t.Errorf("job identity: %s/%s", job.Namespace, job.Name)
	}
	if *job.Spec.BackoffLimit != 0 || job.Spec.Template.Spec.RestartPolicy != corev1.RestartPolicyNever {
		t.Error("a restore must run once, without retry")
	}
	init := job.Spec.Template.Spec.InitContainers[0]
	if init.Image != DefaultAWSCLIImage || job.Spec.Template.Spec.Containers[0].Image != DefaultMongoImage {
		t.Errorf("default images: %s / %s", init.Image, job.Spec.Template.Spec.Containers[0].Image)
	}
	if init.EnvFrom[0].SecretRef.Name != "creds" {
		t.Error("credentials secret not mounted")
	}
	env := map[string]string{}
	for _, e := range init.Env {
		env[e.Name] = e.Value
	}
	want := map[string]string{"SRC": "s3://b/p", "BACKUP": "latest", "MONGODB": "true", "QDRANT": "true",
		"FINGERPRINT": "fp", "ALLOW_KEY_MISMATCH": "false", "AWS_DEFAULT_REGION": "us-east-1", "S3_ENDPOINT": "https://s3"}
	for k, v := range want {
		if env[k] != v {
			t.Errorf("env %s = %q, want %q", k, env[k], v)
		}
	}

	// A single store, a named backup, collections, a region and custom images.
	p.Spec.Backup = &unifaiv1.BackupSpec{Images: unifaiv1.BackupImages{AWSCLI: "aws:1", Mongo: "mongo:1"}}
	r.Spec.Stores = []unifaiv1.RestoreStore{unifaiv1.RestoreQdrant}
	r.Spec.Backup = "2026-01-01"
	r.Spec.Collections = []string{"a", "b"}
	r.Spec.AllowKeyMismatch = true
	src.Region = "eu-west-1"
	job = RestoreJob(p, r, src, "s3://b/p", "fp")
	env = map[string]string{}
	for _, e := range job.Spec.Template.Spec.InitContainers[0].Env {
		env[e.Name] = e.Value
	}
	for k, v := range map[string]string{"MONGODB": "false", "QDRANT": "true", "BACKUP": "2026-01-01", "COLLECTIONS": "a b",
		"ALLOW_KEY_MISMATCH": "true", "AWS_DEFAULT_REGION": "eu-west-1"} {
		if env[k] != v {
			t.Errorf("env %s = %q, want %q", k, env[k], v)
		}
	}
	if job.Spec.Template.Spec.InitContainers[0].Image != "aws:1" || job.Spec.Template.Spec.Containers[0].Image != "mongo:1" {
		t.Error("backup images ignored")
	}
}

func TestServiceConfig(t *testing.T) {
	p := &Plan{Namespace: "ns", Spec: &unifaiv1.UnifaiStackSpec{}}
	svc := &corev1.Service{Spec: corev1.ServiceSpec{ClusterIP: "10.0.0.7", Ports: []corev1.ServicePort{{Port: 8080}}}}
	svc.Name = "unifai-rag"
	cm := ServiceConfig(p, "rag-config", "RAG", "rag", svc)
	if cm.Name != "rag-config" || cm.Namespace != "ns" {
		t.Errorf("meta: %s/%s", cm.Namespace, cm.Name)
	}
	for k, v := range map[string]string{"RAG_ADDR": "10.0.0.7", "RAG_PORT": "8080", "RAG_IP": "unifai-rag"} {
		if cm.Data[k] != v {
			t.Errorf("%s = %q, want %q", k, cm.Data[k], v)
		}
	}
	// A Service without port gives an empty port, not a panic.
	svc.Spec.Ports = nil
	if got := ServiceConfig(p, "x", "RAG", "rag", svc).Data["RAG_PORT"]; got != "" {
		t.Errorf("port = %q", got)
	}
}

func TestConditionHelpers(t *testing.T) {
	u := &unstructured.Unstructured{Object: map[string]any{"status": map[string]any{"conditions": []any{
		map[string]any{"type": "Ready", "status": "False", "message": "booting"},
		map[string]any{"type": "Done", "status": "True"},
	}}}}
	if conditionTrue(u, "Ready") || !conditionTrue(u, "Done") {
		t.Error("conditionTrue")
	}
	if conditionMessage(u, "Ready") != "booting" || conditionMessage(u, "Done") != "" {
		t.Error("conditionMessage")
	}
	if conditionTrue(u, "Missing") || conditionTrue(&unstructured.Unstructured{Object: map[string]any{}}, "Ready") {
		t.Error("absent condition reported true")
	}
	if !strings.HasPrefix(RestoreJobName("x"), "unifai-restore-") {
		t.Error("job name prefix")
	}
}
