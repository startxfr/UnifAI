//go:build e2e

package e2e

import (
	"os"
	"regexp"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

// A real OKF artifact signed keyless by the zuno-demo-agents release workflow (public, anonymous pull), and the
// public Sigstore trusted root the operator unit tests use (internal/okf/testdata/keyless).
const (
	keylessArtifact = "quay.io/zuno/okf-tekos@sha256:bf429d3e6173781f10c858ed81a7f7c23073d9b0ba7ddd1044651d3868fcadba"
	keylessIssuer   = "https://token.actions.githubusercontent.com"
	keylessSubject  = `^https://github\.com/startxfr/zuno-demo-agents/\.github/workflows/publish\.yml@refs/tags/v`
	trustedRootFile = "../../internal/okf/testdata/keyless/trusted_root.json"
)

// keylessBundle is an UnifaiAgentBundle of keylessArtifact checked against subject.
func keylessBundle(ns, name, subject string) *unifaiv1.UnifaiAgentBundle {
	return &unifaiv1.UnifaiAgentBundle{ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns}, Spec: unifaiv1.UnifaiAgentBundleSpec{
		Source: unifaiv1.BundleSource{OCI: unifaiv1.OCIBundleSource{Reference: keylessArtifact}},
		Verify: unifaiv1.BundleVerify{Keyless: &unifaiv1.KeylessVerify{Issuer: keylessIssuer, SubjectRegExp: subject,
			TrustedRootRef: unifaiv1.SecretKeySelector{Name: "e2e-sigstore-trusted-root", Key: "trusted_root.json"}}},
		Ceilings:    unifaiv1.BundleCeilings{MinClassification: "C1"},
		Entitlement: "GatewayOnly",
		LLM: unifaiv1.BundleLLM{ConfigSpec: unifaiv1.ConfigSpec{Config: raw(map[string]any{
			"model_name": "mock-model", "base_url": "http://e2e-llm:8000/v1", "api_key": "EMPTY"})}},
	}}
}

// checkAgentBundleKeyless pulls keylessArtifact through two UnifaiAgentBundles: the release identity verifies it
// (Fulcio chain, SCT, Rekor entry, issuer and subject, offline against the trusted root), another workflow
// identity is refused before anything is parsed or emitted.
func checkAgentBundleKeyless(t *testing.T, ns string) {
	t.Helper()
	root, err := os.ReadFile(trustedRootFile)
	must(t, err)
	create(t, &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "e2e-sigstore-trusted-root", Namespace: ns},
		Data: map[string][]byte{"trusted_root.json": root}})

	verified := func(b *unifaiv1.UnifaiAgentBundle) *metav1.Condition {
		var c *metav1.Condition
		eventually(t, b.Name+" verification", 5*time.Minute, func() (bool, string) {
			if err := getObj(b); err != nil {
				return false, err.Error()
			}
			c = meta.FindStatusCondition(b.Status.Conditions, "Verified")
			return c != nil, b.Status.Phase + " " + b.Status.Message
		})
		return c
	}

	good := keylessBundle(ns, "e2e-keyless", keylessSubject)
	create(t, good)
	if c := verified(good); c.Status != metav1.ConditionTrue {
		t.Fatalf("release-signed artifact not verified: %s", c.Message)
	}
	if !regexp.MustCompile(keylessSubject).MatchString(good.Status.Signer) || good.Status.ResolvedDigest == "" ||
		good.Status.OKFVersion == "" {
		t.Errorf("verified bundle status: signer %q, digest %q, okf %q", good.Status.Signer, good.Status.ResolvedDigest,
			good.Status.OKFVersion)
	}
	// Verified, then refused by the empty spec.ceilings: the checks after the signature run on its content.
	if good.Status.Phase != "Error" || !strings.Contains(good.Status.Message, "ceilings") || len(good.Status.Children) > 0 {
		t.Errorf("verified bundle beyond its ceilings: phase %s %q, children %v", good.Status.Phase, good.Status.Message,
			good.Status.Children)
	}

	// The artifact also carries a publish-dev.yml signature: only another repository is a wrong signer.
	bad := keylessBundle(ns, "e2e-keyless-wrong-signer", `^https://github\.com/startxfr/another-repository/`)
	create(t, bad)
	if c := verified(bad); c.Status != metav1.ConditionFalse {
		t.Fatalf("artifact accepted for another workflow identity: %s", c.Message)
	}
	if bad.Status.Phase != "Error" || bad.Status.Verified || len(bad.Status.Children) > 0 || bad.Status.OKFVersion != "" {
		t.Errorf("refused bundle: phase %s, verified %v, children %v, okf %q (nothing may be parsed or emitted)",
			bad.Status.Phase, bad.Status.Verified, bad.Status.Children, bad.Status.OKFVersion)
	}
}

func getObj(o client.Object) error { return c.Get(ctx, client.ObjectKeyFromObject(o), o) }

// controllerInstanceLabel is the label that assigns an object to an operator instance.
const controllerInstanceLabel = "unifai.startx.fr/operator-instance"

// Development artifacts of zuno-demo-agents (publish-dev.yml, devel 10f1bd9), pulled anonymously and pinned by digest:
// arkos (plan_draft_write, C3, primary task draft-architecture-testimonial) declares zuno.delegation.targets
// [{tekos, answer-technical-question}]; tekos (retrieve_reason_respond, C1) declares none.
const (
	delegatingArtifact = "quay.io/zuno/okf-arkos@sha256:c54b80bd20b404d88f1817ddefd0450f191f93ed8dd579c802bcf72957e49c82"
	targetArtifact     = "quay.io/zuno/okf-tekos@sha256:e6fb7962d245bbed1cfd5daa76fbab77051f7f916dfca611a069249f8fa474f5"
	devSubject         = `^https://github\.com/startxfr/zuno-demo-agents/\.github/workflows/publish-dev\.yml@refs/heads/devel$`
	gatewayURL         = "http://a2a-gateway.zuno-ai-run.svc:8080"
)

// delegationBundle is an UnifaiAgentBundle of a development artifact, with ceilings admitting what tekos and arkos declare.
func delegationBundle(ns, name, artifact string) *unifaiv1.UnifaiAgentBundle {
	b := keylessBundle(ns, name, devSubject)
	b.Spec.Source.OCI.Reference = artifact
	b.Spec.Ceilings = unifaiv1.BundleCeilings{
		ToolCapabilities: []string{"aap.cluster.audit", "aap.platform.audit", "confluence.page.read", "confluence.page.search",
			"diagram.generation.create", "git.file.write", "git.repository.create", "git.repository.list",
			"git.repository.private.list", "git.repository.private.read", "git.repository.read", "list_drive_files",
			"search_confluence", "web_search"},
		KnowledgeDomains:  []string{"knowledge.project", "knowledge.tech"},
		MinClassification: "C1",
	}
	return b
}

// ensureMockLLM deploys the mock LLM of the bundle template (http://e2e-llm:8000/v1) unless the namespace has it.
func ensureMockLLM(t *testing.T, ns string) {
	t.Helper()
	if err := c.Get(ctx, client.ObjectKey{Namespace: ns, Name: "e2e-llm"}, &appsv1.Deployment{}); err == nil {
		return
	}
	deployMockLLM(t, ns)
}

// checkAgentBundleDelegation: a bundle declaring a delegation target is refused without spec.delegation, and with it
// is emitted as an orchestrator before its draft stage plus an A2A node towards the gateway, at the highest classification
// of the task and its target; the real UnifAI accepts the resulting workflow, and a target that is not served (here: not
// created yet) is waited for.
func checkAgentBundleDelegation(t *testing.T, ns string) {
	t.Helper()
	ensureMockLLM(t, ns)
	root, err := os.ReadFile(trustedRootFile)
	must(t, err)
	if err := c.Get(ctx, client.ObjectKey{Namespace: ns, Name: "e2e-sigstore-trusted-root"}, &corev1.Secret{}); err != nil {
		create(t, &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "e2e-sigstore-trusted-root", Namespace: ns},
			Data: map[string][]byte{"trusted_root.json": root}})
	}
	phase := func(b *unifaiv1.UnifaiAgentBundle, want string, timeout time.Duration) {
		eventually(t, "bundle "+b.Name+" "+want, timeout, func() (bool, string) {
			if err := getObj(b); err != nil {
				return false, err.Error()
			}
			return b.Status.Phase == want, b.Status.Phase + " " + b.Status.Message
		})
	}
	condition := func(b *unifaiv1.UnifaiAgentBundle, typ, reason string) {
		eventually(t, "bundle "+b.Name+" "+typ+"="+reason, 5*time.Minute, func() (bool, string) {
			if err := getObj(b); err != nil {
				return false, err.Error()
			}
			cd := meta.FindStatusCondition(b.Status.Conditions, typ)
			return cd != nil && cd.Status == metav1.ConditionFalse && cd.Reason == reason, b.Status.Phase + " " + b.Status.Message
		})
	}

	// 1. Without spec.delegation the declared target is refused and nothing is emitted.
	closed := delegationBundle(ns, "e2e-deleg-closed", delegatingArtifact)
	create(t, closed)
	condition(closed, "Valid", "DelegationUnsupported")
	if len(closed.Status.Children) > 0 {
		t.Errorf("a refused delegation emitted %v", closed.Status.Children)
	}
	must(t, c.Delete(ctx, closed))

	// 2. With spec.delegation but the target not served yet: the bundle waits for it (and emits nothing).
	arkos := delegationBundle(ns, "e2e-arkos", delegatingArtifact)
	arkos.Spec.Delegation = &unifaiv1.BundleDelegation{GatewayURL: gatewayURL}
	arkos.Spec.Ceilings.DelegationTargets = []string{"tekos/answer-technical-question"}
	create(t, arkos)
	condition(arkos, "Valid", "DelegationTargetUnresolved")
	if len(arkos.Status.Children) > 0 {
		t.Errorf("a delegation towards an unserved target emitted %v", arkos.Status.Children)
	}

	// 3. The target is served: the delegating bundle emits. The target keeps its own level (C1).
	tekos := delegationBundle(ns, "e2e-tekos", targetArtifact)
	create(t, tekos)
	phase(tekos, "Ready", 10*time.Minute)
	phase(arkos, "Ready", 10*time.Minute)
	for _, task := range arkos.Status.Tasks {
		if task.Classification != "C3" {
			t.Errorf("task %s of the delegating agent runs at %s, want C3", task.Name, task.Classification)
		}
	}
	for _, task := range tekos.Status.Tasks {
		if task.Classification != "C1" {
			t.Errorf("task %s of the target runs at %s: a target is never raised by what delegates to it", task.Name, task.Classification)
		}
	}
	orch := "e2e-arkos-draft-architecture-testimonial-orchestrator"
	if !containsString(arkos.Status.Children, "UnifaiAgent/"+orch) ||
		!containsString(arkos.Status.Children, "UnifaiAgent/e2e-arkos-draft-architecture-testimonial-draft") {
		t.Fatalf("no orchestrator and draft stage among the children %v", arkos.Status.Children)
	}
	agent := &unifaiv1.UnifaiAgent{ObjectMeta: metav1.ObjectMeta{Name: orch, Namespace: ns}}
	must(t, getObj(agent))
	if agent.Spec.Type != "orchestrator_node" {
		t.Errorf("%s is a %s", orch, agent.Spec.Type)
	}
	// Children carry the operator instance of their bundle (a canary only sees what is labelled for it).
	if agent.Labels[controllerInstanceLabel] != instance {
		t.Errorf("child instance label %q, want %q", agent.Labels[controllerInstanceLabel], instance)
	}

	// 4. The real UnifAI accepts the delegating workflow (the primary task's workflow is named after the bundle).
	wf := &unifaiv1.UnifaiWorkflow{ObjectMeta: metav1.ObjectMeta{Name: "e2e-arkos", Namespace: ns}}
	waitPhase(t, wf, "Ready", 10*time.Minute)
	bp := string(wf.Spec.Blueprint.Raw)
	for _, want := range []string{`"base_url":"` + gatewayURL + `/agents/tekos"`, `"auth_method":"forward_user_token"`,
		`"X-Zuno-Delegated-By":"arkos:draft-architecture-testimonial"`, `"X-Zuno-Delegation-Depth":"1"`,
		`"X-Zuno-Task":"answer-technical-question"`} {
		if !strings.Contains(bp, want) {
			t.Errorf("delegating workflow lacks %s", want)
		}
	}

	// 5. A free-form workflow (not owned by a bundle) with an A2A node stays refused, towards the gateway too: only the
	// bundle's own workflow may delegate. (A bundle-owned workflow is rewritten by its bundle, so it cannot hold a
	// foreign host: that rule is covered by the unit tests.)
	free := &unifaiv1.UnifaiWorkflow{ObjectMeta: metav1.ObjectMeta{Name: "e2e-free-a2a", Namespace: ns}, Spec: unifaiv1.UnifaiWorkflowSpec{
		Blueprint: *raw(map[string]any{
			"nodes": []any{
				map[string]any{"rid": "user_question", "name": "User Question Node", "type": "user_question_node", "config": map[string]any{"type": "user_question_node"}},
				map[string]any{"rid": "final_answer", "name": "Final Answer Node", "type": "final_answer_node", "config": map[string]any{"type": "final_answer_node"}},
				map[string]any{"rid": "a2a-free", "name": "Free A2A", "type": "a2a_agent_node", "config": map[string]any{
					"type": "a2a_agent_node", "base_url": gatewayURL + "/agents/tekos", "auth_method": "forward_user_token"}}},
			"plan": []any{
				map[string]any{"uid": "ask", "node": "user_question"},
				map[string]any{"uid": "a2a", "node": "a2a-free", "after": "ask"},
				map[string]any{"uid": "finish", "node": "final_answer", "after": "a2a"}},
		})}}
	create(t, free)
	eventually(t, "a free-form A2A workflow is refused", 5*time.Minute, func() (bool, string) {
		if err := getObj(free); err != nil {
			return false, err.Error()
		}
		return free.Status.Phase == "Error" && strings.Contains(free.Status.Message, "A2A delegation is disabled"), free.Status.Phase + " " + free.Status.Message
	})
}
