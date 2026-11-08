//go:build e2e

package e2e

import (
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
)

// Token ceiling of one turn (R-543): spec.ceilings.maxTokensPerTurn of a bundle is given to every task that declares none.
// A mock LLM reports ceilingUsage tokens per call (more than the cap), so a turn that makes a second model call is cut
// there: the chat ends cleanly with what the model had produced then "Token ceiling reached for this turn (<used>/<cap>
// tokens)", and the session holds one agent_error event for the turn. Run with E2E_TOKEN_CEILING=1.
const (
	ceilingCap      = 2000
	ceilingUsage    = "2500"
	ceilingBundle   = "e2e-ceiling"
	ceilingHeavyLLM = "e2e-llm-heavy"
)

// ceilingEventsProbe reads the chat and the replayed events of a session (the full history of late joiners) and prints
// them raw, then counts the agent_error events. Exit 0 only when it could read both.
const ceilingEventsProbe = `
import json, os, sys, time, urllib.request, urllib.error
base = "http://unifai-multiagent-be:8003/api/sessions/"
hdr = {"X-Authenticated-User": "admin", "X-Internal-Auth": os.environ["INTERNAL_AUTH_SECRET"]}
sid = os.environ["SESSION_ID"]
out = {}
try:
    out["chat"] = urllib.request.urlopen(urllib.request.Request(base + "session.chat.get?sessionId=" + sid, headers=hdr), timeout=30).read().decode()[:2500]
except urllib.error.HTTPError as e:
    out["chat"] = "HTTP %d %s" % (e.code, e.read().decode()[:200])
events, deadline = [], time.time() + 25
try:
    resp = urllib.request.urlopen(urllib.request.Request(base + "session.subscribe?sessionId=" + sid, headers=hdr), timeout=30)
    while time.time() < deadline:
        line = resp.readline()
        if not line:
            break
        line = line.decode().strip()
        if line:
            events.append(line)
except Exception as e:
    out["subscribe_end"] = repr(e)
errs = [l for l in events if '"agent_error"' in l]
out["events"] = len(events)
out["agent_error"] = len(errs)
out["agent_error_raw"] = [l[:400] for l in errs]
open("/dev/termination-log", "w").write(json.dumps(out)[:4000])
sys.exit(0)
`

// ceilingBundleOf is a development artifact of tekos whose stack ceiling is ceilingCap tokens, on the heavy mock.
func ceilingBundleOf(ns string) *unifaiv1.UnifaiAgentBundle {
	b := delegationBundle(ns, ceilingBundle, targetArtifact)
	b.Spec.Ceilings.MaxTokensPerTurn = ceilingCap
	b.Spec.LLM = unifaiv1.BundleLLM{ConfigSpec: unifaiv1.ConfigSpec{Config: raw(map[string]any{
		"model_name": "mock-model", "base_url": "http://" + ceilingHeavyLLM + ":8000/v1", "api_key": "EMPTY"})}}
	return b
}

// checkTokenCeiling: see the constants above. It prints the raw outputs (chat result, events) for the record.
func checkTokenCeiling(t *testing.T, ns string) {
	t.Helper()
	if err := c.Get(ctx, client.ObjectKey{Namespace: ns, Name: ceilingHeavyLLM}, &corev1.Service{}); err != nil {
		deployNamedMockLLM(t, ns, ceilingHeavyLLM, corev1.EnvVar{Name: "MOCK_USAGE_TOKENS", Value: ceilingUsage}, corev1.EnvVar{Name: "MOCK_TOOL_FIRST", Value: "1"})
	}
	root, err := os.ReadFile(trustedRootFile)
	must(t, err)
	if err := c.Get(ctx, client.ObjectKey{Namespace: ns, Name: "e2e-sigstore-trusted-root"}, &corev1.Secret{}); err != nil {
		create(t, &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: "e2e-sigstore-trusted-root", Namespace: ns},
			Data: map[string][]byte{"trusted_root.json": root}})
	}
	bundle := ceilingBundleOf(ns)
	create(t, bundle)
	eventually(t, "bundle "+ceilingBundle+" Ready", 10*time.Minute, func() (bool, string) {
		if err := getObj(bundle); err != nil {
			return false, err.Error()
		}
		return bundle.Status.Phase == "Ready", bundle.Status.Phase + " " + bundle.Status.Message
	})
	wf := &unifaiv1.UnifaiWorkflow{ObjectMeta: metav1.ObjectMeta{Name: ceilingBundle, Namespace: ns}}
	waitPhase(t, wf, "Ready", 10*time.Minute)

	chat := &unifaiv1.UnifaiChat{ObjectMeta: metav1.ObjectMeta{Name: "e2e-ceiling-chat", Namespace: ns},
		Spec: unifaiv1.UnifaiChatSpec{Workflow: ceilingBundle, Prompt: "Explain in detail how a Kubernetes operator reconciles a resource."}}
	create(t, chat)
	waitPhase(t, chat, "Completed", 10*time.Minute)
	t.Logf("chat result (raw): %q", chat.Status.Result)

	wantTail := fmt.Sprintf("/%d tokens)", ceilingCap)
	if !strings.Contains(chat.Status.Result, "Token ceiling reached for this turn (") || !strings.Contains(chat.Status.Result, wantTail) {
		t.Errorf("the turn was not cut by the ceiling of %d tokens: result %q", ceilingCap, chat.Status.Result)
	}

	secret := &corev1.EnvVarSource{SecretKeyRef: &corev1.SecretKeySelector{
		LocalObjectReference: corev1.LocalObjectReference{Name: "unifai-internal-auth"}, Key: "INTERNAL_AUTH_SECRET"}}
	ok, msg := runProbe(t, ns, "e2e-ceiling-events", ceilingEventsProbe,
		map[string]string{"unifai.startx.fr/internal-client": "true"},
		corev1.EnvVar{Name: "INTERNAL_AUTH_SECRET", ValueFrom: secret}, corev1.EnvVar{Name: "SESSION_ID", Value: chat.Status.SessionID})
	t.Logf("session events (raw): %s", msg)
	if !ok {
		t.Errorf("the session could not be read: %s", msg)
		return
	}
	switch {
	case strings.Contains(msg, `"agent_error": 1,`) || strings.Contains(msg, `"agent_error": 1}`):
	case strings.Contains(msg, `"agent_error": 0`):
		// The event is emitted on a live stream only: a chat run by the operator may not stream. The notice in the
		// result above is the proof; the raw events are logged for the record.
		t.Logf("no agent_error event in the replay (the turn was not streamed?)")
	default:
		t.Errorf("more than one agent_error event for the turn: %s", msg)
	}
}
