//go:build e2e

package e2e

// R-552: the forced deletion of a resource that others reference (upstream PR #279, released in 0.1.69) on the real
// services. The probe creates its own resources and blueprint through the MAS API (objects made from custom
// resources would be put back by the operator), then checks each mode: a plain delete is refused with 409
// RESOURCE_IN_USE; detach (retriever, tool, provider) removes the reference and keeps the agent; replace (LLM,
// condition) points the agent and the blueprint, plan included, to the replacement; cascade (agent) deletes the
// blueprint; a reference left in a config without its index entry (legacy data) still blocks a delete.
//
// It runs in a pod built from the multiagent Deployment (same image, env and labels) because the legacy case writes
// to MongoDB with pymongo. Part of the full run (E2E_FULL=1).

import (
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// resourceDeletionProbe exits 0 when every check passes; its termination message lists the failures.
const resourceDeletionProbe = `
import json, os, urllib.request, urllib.error, urllib.parse
S = os.environ.get("INTERNAL_AUTH_SECRET")
B = "http://unifai-multiagent-be:8003"
def call(method, path, body=None, params=None):
    url = B + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Content-Type": "application/json", "X-Authenticated-User": "admin", "X-Internal-Auth": S or ""})
    try:
        r = urllib.request.urlopen(req, timeout=60); return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        t = e.read().decode()
        try: t = json.loads(t)
        except Exception: pass
        return e.code, t
for cat in ["llms","tools","providers","retrievers","conditions","nodes","sandboxes"]:
    s, r = call("GET", "/api/resources/resources.list", params={"category": cat})
import time, sys
SUF = str(int(time.time()) % 100000)
out, bad = [], []
def check(cond, msg):
    out.append(("ok   " if cond else "FAIL ") + msg)
    if not cond: bad.append(msg)
def save(cat, typ, name, cfg):
    s, r = call("POST", "/api/resources/resource.save", {"category": cat, "type": typ, "name": name + "-" + SUF, "config": cfg})
    if s >= 300: raise SystemExit("save %s %s: %s %s" % (cat, typ, s, str(r)[:300]))
    return r["rid"]
def new_bp(name, agent, cond):
    draft = {"name": name + "-" + SUF, "nodes": [
        {"rid": "user_question", "name": "User Question Node", "type": "user_question_node", "config": {"type": "user_question_node"}},
        {"rid": "final_answer", "name": "Final Answer Node", "type": "final_answer_node", "config": {"type": "final_answer_node"}},
        {"rid": "$ref:" + agent}], "conditions": [{"rid": "$ref:" + cond}],
        "plan": [{"uid": "ask", "node": "user_question", "exit_condition": cond, "branches": {"agent": "agent"}},
                 {"uid": "agent", "node": agent}, {"uid": "finish", "node": "final_answer", "after": "agent"}]}
    s, r = call("POST", "/api/blueprints/blueprint.save", {"blueprintRaw": json.dumps(draft)})
    if s >= 300: raise SystemExit("blueprint: %s %s" % (s, str(r)[:300]))
    return r["blueprint_id"]
def cfg(rid):
    s, r = call("GET", "/api/resources/resource.get", params={"resourceId": rid})
    return (r.get("cfg_dict") or {}) if s == 200 else s
def gone(rid):
    s, _ = call("GET", "/api/resources/resource.get", params={"resourceId": rid})
    return s == 404
def bp_text(bid):
    s, r = call("GET", "/api/blueprints/blueprint.info.get", params={"blueprintId": bid})
    return s, json.dumps(r)
def force(rid, mode, rep=None):
    body = {"resourceId": rid, "mode": mode}
    if rep: body["replacementId"] = rep
    return call("POST", "/api/resources/resource.force.delete", body)
LLM = {"model_name": "mock", "base_url": "http://x:8000/v1", "api_key": "EMPTY"}
llm_a, llm_b = save("llms", "openai_compatible", "llm-a", LLM), save("llms", "openai_compatible", "llm-b", LLM)
cond_a, cond_b = save("conditions", "router_direct", "cond-a", {}), save("conditions", "router_direct", "cond-b", {})
ret = save("retrievers", "docs_rag", "ret", {})
tool = save("tools", "web_fetch", "tool", {})
prov = save("providers", "mcp_server", "prov", {"mcp_url": "http://mcp.invalid:9000/mcp", "server_identifier": "r552"})
agent = save("nodes", "custom_agent_node", "agent", {"llm": "$ref:" + llm_a, "retriever": "$ref:" + ret,
    "tools": ["$ref:" + tool], "providers": ["$ref:" + prov], "hitl_mode": "skip"})
bid = new_bp("bp", agent, cond_a)

# a plain delete of a referenced resource is refused with 409 RESOURCE_IN_USE (it was 400 before #279)
s, r = call("DELETE", "/api/resources/resource.delete", params={"resourceId": ret})
check(s == 409 and isinstance(r, dict) and r.get("code") == "RESOURCE_IN_USE", "plain delete of a referenced retriever answers 409 RESOURCE_IN_USE (got %s %s)" % (s, str(r)[:120]))
check(not gone(ret), "the retriever is still there after the refused delete")
# the mode must match the category
s, r = force(llm_a, "detach")
check(s == 400, "detach on an LLM is refused (got %s %s)" % (s, str(r)[:100]))
s, r = force(ret, "replace", llm_b)
check(s == 400, "replace on a retriever is refused (got %s)" % s)

# detach: retriever, tool and provider are removed from the agent, which stays
for name, rid, key in [("retriever", ret, "retriever"), ("tool", tool, "tools"), ("provider", prov, "providers")]:
    s, r = force(rid, "detach")
    check(s == 200, "detach %s answers 200 (got %s %s)" % (name, s, str(r)[:120]))
    check(gone(rid), "the %s is deleted" % name)
    c = cfg(agent)
    check(isinstance(c, dict) and rid not in json.dumps(c.get(key)), "the agent no longer references the %s (%s=%s)" % (name, key, json.dumps(c.get(key) if isinstance(c, dict) else c)))
check(isinstance(cfg(agent), dict), "the agent survives the three detaches")

# replace: an LLM in use is swapped to another LLM; the replacement must be of the same category and another resource
s, r = force(llm_a, "replace")
check(s == 400, "replace without replacementId is refused (got %s)" % s)
s, r = force(llm_a, "replace", llm_a)
check(s == 400, "replace by itself is refused (got %s)" % s)
s, r = force(llm_a, "replace", cond_b)
check(s == 400, "replace by a resource of another category is refused (got %s)" % s)
s, r = force(llm_a, "replace", llm_b)
check(s == 200, "replace the LLM answers 200 (got %s %s)" % (s, str(r)[:120]))
check(gone(llm_a), "the replaced LLM is deleted")
c = cfg(agent)
check(isinstance(c, dict) and c.get("llm") == "$ref:" + llm_b, "the agent now points to the replacement LLM (%s)" % (c.get("llm") if isinstance(c, dict) else c))
# replace a condition used by the blueprint
s, r = force(cond_a, "replace", cond_b)
check(s == 200, "replace the condition answers 200 (got %s %s)" % (s, str(r)[:120]))
st, info = call("GET", "/api/blueprints/blueprint.info.get", params={"blueprintId": bid})
spec = (info or {}).get("spec_dict") or {} if st == 200 and isinstance(info, dict) else {}
plan_conds = [step.get("exit_condition") for step in spec.get("plan", []) if isinstance(step, dict)]
check([c.get("rid") for c in spec.get("conditions", [])] == ["$ref:" + cond_b], "the blueprint catalogue lists the replacement condition (got %s)" % [c.get("rid") for c in spec.get("conditions", [])])
check(cond_b in plan_conds and cond_a not in plan_conds, "the plan steps exit on the replacement condition, not on the deleted one (R-552; got %s)" % plan_conds)
# the workflow must still build: a session submit fails with 500 "Session build failed" when the plan names a deleted condition
st, sid = call("POST", "/api/sessions/user.session.create", {"blueprintId": bid, "hitlEnabled": False, "metadata": {"title": "r552", "source": "e2e"}})
if st == 200:
    st, r = call("POST", "/api/sessions/user.session.submit", {"sessionId": sid, "inputs": {"user_prompt": "ping"}})
    check(st == 202, "the workflow still builds after the condition replace (submit answered %s %s)" % (st, str(r)[:100]))
else:
    check(False, "session create answered %s" % st)

# legacy reference: a cfg_dict $ref without nested_refs still blocks the deletion
import pymongo
col = pymongo.MongoClient("mongodb://%s:%s/" % (os.environ.get("MONGODB_IP", "mongodb"), os.environ.get("MONGODB_PORT", "27017")))["UnifAI"]["resources"]
res = col.update_one({"rid": agent}, {"$set": {"nested_refs": []}})
check(res.matched_count == 1, "legacy setup: the agent document has no nested_refs index any more")
s, u = call("GET", "/api/resources/resource.check.usage", params={"resourceId": llm_b})
check(s == 200 and u.get("in_use") is True and agent in json.dumps(u), "check.usage still sees the legacy reference to the LLM (got %s %s)" % (s, str(u)[:160]))
s, r = call("DELETE", "/api/resources/resource.delete", params={"resourceId": llm_b})
check(s == 409 and not gone(llm_b), "plain delete of an LLM referenced only by a legacy cfg_dict $ref is refused (got %s)" % s)

# cascade: deleting the agent deletes the blueprint that uses it
s, r = force(agent, "cascade")
check(s == 200, "cascade the agent answers 200 (got %s %s)" % (s, str(r)[:120]))
check(gone(agent), "the agent is deleted")
st, txt = bp_text(bid)
check(st == 404, "the blueprint that used the agent is deleted (got %s)" % st)
s, r = force(llm_b, "replace", llm_a)  # llm_a is gone: bad replacement
check(s in (400, 404), "replace by a deleted resource is refused (got %s)" % s)

print("\n".join(out))
summary = "%d checks, %d failed" % (len(out), len(bad))
if bad:
    summary += ": " + "; ".join(bad)
try: open("/dev/termination-log", "w").write(summary[:3800])
except Exception: pass
sys.exit(1 if bad else 0)
`

// checkResourceDeletion runs resourceDeletionProbe in the namespace of the stack and fails with its failed checks.
func checkResourceDeletion(t *testing.T, ns string) {
	t.Helper()
	var dep appsv1.Deployment
	must(t, c.Get(ctx, client.ObjectKey{Namespace: ns, Name: "unifai-multiagent-be"}, &dep))
	src := dep.Spec.Template.Spec
	if len(src.Containers) == 0 {
		t.Fatal("the multiagent Deployment has no container")
	}
	labels := map[string]string{"unifai.startx.fr/internal-client": "true"}
	pod := &corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "e2e-resource-deletion", Namespace: ns, Labels: labels}, Spec: corev1.PodSpec{
		RestartPolicy:    corev1.RestartPolicyNever,
		ImagePullSecrets: src.ImagePullSecrets,
		NodeSelector:     src.NodeSelector,
		Tolerations:      src.Tolerations,
		Containers: []corev1.Container{{Name: "probe", Image: src.Containers[0].Image, ImagePullPolicy: src.Containers[0].ImagePullPolicy,
			Env: src.Containers[0].Env, EnvFrom: src.Containers[0].EnvFrom, Command: []string{"python", "-c", resourceDeletionProbe}}},
	}}
	must(t, c.Create(ctx, pod))
	defer func() { _ = c.Delete(ctx, pod) }()
	var msg string
	eventually(t, "e2e-resource-deletion finished", 10*time.Minute, func() (bool, string) {
		if err := c.Get(ctx, client.ObjectKeyFromObject(pod), pod); err != nil {
			return false, err.Error()
		}
		for _, cs := range pod.Status.ContainerStatuses {
			if term := cs.State.Terminated; term != nil {
				msg = term.Message
			}
		}
		return pod.Status.Phase == corev1.PodSucceeded || pod.Status.Phase == corev1.PodFailed, string(pod.Status.Phase)
	})
	t.Log(msg)
	if pod.Status.Phase != corev1.PodSucceeded {
		t.Errorf("forced deletion of resources in use: %s", strings.TrimSpace(msg))
	}
}
