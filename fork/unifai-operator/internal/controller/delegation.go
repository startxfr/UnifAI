package controller

import (
	"context"
	"fmt"
	"strings"

	"sigs.k8s.io/controller-runtime/pkg/client"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/okf"
)

// Read-only A2A delegation through the zuno a2a-gateway (zuno ADR-0401/0403/0585, WP-173 short path). A bundle declaring
// zuno.delegation.targets, with spec.delegation set, emits each task as an orchestrator over the task's own agent and
// one A2A node per target. The gateway checks the user's groups, the declared targets, depth and cycles from the
// chain headers the node sends; the operator makes sure only a reviewed bundle can send them.

const (
	defaultDelegationRounds = 5
	headerDelegatedBy       = "X-Zuno-Delegated-By"
	headerDelegationDepth   = "X-Zuno-Delegation-Depth"
	headerTargetTask        = "X-Zuno-Task"
)

// delegationTarget is a declared target resolved against its UnifaiAgentBundle in the namespace.
type delegationTarget struct {
	Agent, Task string
	Title       string
	Description string
	Level       okf.Level
}

func (t delegationTarget) key() string { return t.Agent + "/" + t.Task }

// resolveTargets finds each target's bundle (same namespace, Verified, served), refuses a task other than the
// target's primary one (the gateway takes no task selector yet: another task would silently reach the primary)
// and reads the target task's effective classification.
func (r *AgentBundleReconciler) resolveTargets(ctx context.Context, cr *unifaiv1.UnifaiAgentBundle, b *okf.Bundle) ([]delegationTarget, error) {
	if len(b.DelegationTargets) == 0 {
		return nil, nil
	}
	var list unifaiv1.UnifaiAgentBundleList
	if err := r.List(ctx, &list, client.InNamespace(cr.Namespace)); err != nil {
		return nil, err
	}
	byAgent := map[string]*unifaiv1.UnifaiAgentBundle{}
	for i := range list.Items {
		if a := list.Items[i].Status.Agent; a != "" {
			byAgent[a] = &list.Items[i]
		}
	}
	out := make([]delegationTarget, 0, len(b.DelegationTargets))
	for _, d := range b.DelegationTargets {
		key := d.Agent + "/" + d.Task
		if d.Agent == b.Name {
			return nil, permanent("delegation target %s: an agent does not delegate to itself", key)
		}
		tb := byAgent[d.Agent]
		if tb == nil || !tb.Status.Verified || tb.Status.Phase != phaseReady {
			return nil, fmt.Errorf("delegation target %s: no Verified, Ready UnifaiAgentBundle for agent %s in %s yet", key, d.Agent, cr.Namespace)
		}
		if tb.Status.PrimaryTask != d.Task {
			return nil, permanent("delegation target %s: only the primary task (%s) of %s can be reached through the gateway today",
				key, tb.Status.PrimaryTask, d.Agent)
		}
		level := okf.Level(0)
		for _, t := range tb.Status.Tasks {
			if t.Name == d.Task {
				if level, _ = okf.ParseLevel(t.Classification); level == 0 {
					return nil, fmt.Errorf("delegation target %s: unknown classification %q", key, t.Classification)
				}
			}
		}
		if level == 0 {
			return nil, fmt.Errorf("delegation target %s: task %s is not served by %s", key, d.Task, tb.Name)
		}
		dt := delegationTarget{Agent: d.Agent, Task: d.Task, Level: level, Title: d.Agent}
		if disp := tb.Status.Display; disp != nil {
			if disp.DisplayName != "" {
				dt.Title = disp.DisplayName
			}
			dt.Description = disp.Description
		}
		out = append(out, dt)
	}
	return out, nil
}

// raisedLevel is the classification a delegating task runs at: the highest of its own and its targets', from its
// first call (ADR-0401/0403 monotone classification, applied statically).
func raisedLevel(level okf.Level, targets []delegationTarget) okf.Level {
	for _, tg := range targets {
		level = max(level, tg.Level)
	}
	return level
}

// delegatingTask is the orchestrator of a delegating task and the blueprint of its workflow.
func delegatingTask(cr *unifaiv1.UnifaiAgentBundle, b *okf.Bundle, t okf.Task, common unifaiv1.CommonSpec, cond, agent string,
	targets []delegationTarget) (client.Object, map[string]any) {
	orch := agent + "-orchestrator"
	obj := &unifaiv1.UnifaiAgent{ObjectMeta: childMeta(cr, orch), Spec: unifaiv1.UnifaiAgentSpec{
		CommonSpec: common, Type: "orchestrator_node",
		ConfigSpec: unifaiv1.ConfigSpec{Config: rawJSON(orchestratorConfig(cr, b, t, agent, targets))}}}
	return obj, delegatingBlueprint(cond, orch, agent, a2aNodes(cr.Spec.Delegation, b.Name, t.Name, targets))
}

// orchestratorConfig coordinates a delegating task: its own agent first, a target only when asked for.
func orchestratorConfig(cr *unifaiv1.UnifaiAgentBundle, b *okf.Bundle, t okf.Task, agentName string, targets []delegationTarget) map[string]any {
	rounds := int(cr.Spec.Delegation.MaxRounds)
	if rounds == 0 {
		rounds = defaultDelegationRounds
	}
	title := t.Title
	if title == "" {
		title = t.Name
	}
	var msg strings.Builder
	fmt.Fprintf(&msg, "You coordinate the answer of %s for the task %q.\n", agentTitle(b), title)
	fmt.Fprintf(&msg, "Delegate the user's request to the agent %s first: it has this task's documents, tools and instructions.\n", agentName)
	msg.WriteString("Delegate to another agent below only when the user asks for what it provides, at most once per request:\n")
	for _, tg := range targets {
		fmt.Fprintf(&msg, "- %s (%s): %s\n", tg.Title, tg.key(), strings.TrimSpace(tg.Description))
	}
	msg.WriteString("Then give a single final answer built from their results, keeping the sources they cite.")
	return map[string]any{"llm": "$ref:llm/" + agentName, "system_message": msg.String(), "max_rounds": rounds}
}

func agentTitle(b *okf.Bundle) string {
	if b.Title != "" {
		return b.Title
	}
	return b.Name
}

// a2aNodes are the inline blueprint nodes of the targets. They carry the user's own token and the delegation chain
// (<caller agent>:<task>, depth 1) that the gateway verifies; X-Zuno-Task names the target task for when the gateway
// reads it (it is the primary task today).
func a2aNodes(d *unifaiv1.BundleDelegation, agent, task string, targets []delegationTarget) []map[string]any {
	out := make([]map[string]any, 0, len(targets))
	for _, tg := range targets {
		out = append(out, map[string]any{
			"rid": "a2a-" + tg.Agent, "name": tg.Title, "type": a2aNodeType,
			"config": map[string]any{
				"type":        a2aNodeType,
				"base_url":    strings.TrimRight(d.GatewayURL, "/") + "/agents/" + tg.Agent,
				"auth_method": "forward_user_token",
				"additional_headers": map[string]any{
					headerRunID:           "{session_id}",
					headerDelegatedBy:     agent + ":" + task,
					headerDelegationDepth: "1",
					headerTargetTask:      tg.Task,
				},
			},
		})
	}
	return out
}

// delegatingBlueprint: question -> orchestrator -> (task agent | target A2A nodes) -> answer. The workers act only on
// the work the orchestrator sends them, so a target is not called on a turn that does not need it.
func delegatingBlueprint(cond, orchestrator, agent string, a2a []map[string]any) map[string]any {
	nodes := []any{
		map[string]any{"name": "User Question Node", "rid": "user_question", "type": "user_question_node",
			"config": map[string]any{"retries": 1, "type": "user_question_node"}},
		map[string]any{"name": "Final Answer Node", "rid": "final_answer", "type": "final_answer_node",
			"config": map[string]any{"retries": 1, "type": "final_answer_node"}},
		map[string]any{"rid": "$ref:agent/" + orchestrator},
		map[string]any{"rid": "$ref:agent/" + agent},
	}
	plan := []any{
		map[string]any{"uid": "ask", "node": "user_question", "branches": map[string]any{"agent": "orchestrate"},
			"exit_condition": "$rid:condition/" + cond},
		map[string]any{"uid": "orchestrate", "node": "$rid:agent/" + orchestrator},
		map[string]any{"uid": "agent", "node": "$rid:agent/" + agent, "after": "orchestrate"},
	}
	workers := []any{"agent"}
	for _, n := range a2a {
		nodes = append(nodes, n)
		uid := n["rid"].(string)
		plan = append(plan, map[string]any{"uid": uid, "node": uid, "after": "orchestrate"})
		workers = append(workers, uid)
	}
	plan = append(plan, map[string]any{"uid": "finish", "node": "final_answer", "after": workers})
	return map[string]any{
		"conditions": []any{map[string]any{"rid": "$ref:condition/" + cond}},
		"nodes":      nodes,
		"plan":       plan,
	}
}

// delegationOutsideCeilings lists the declared targets missing from spec.ceilings.delegationTargets.
func delegationOutsideCeilings(cr *unifaiv1.UnifaiAgentBundle, b *okf.Bundle) []string {
	declared := make([]string, 0, len(b.DelegationTargets))
	for _, d := range b.DelegationTargets {
		declared = append(declared, d.Agent+"/"+d.Task)
	}
	return outside(declared, cr.Spec.Ceilings.DelegationTargets)
}

// bundleMayDelegate reports whether a workflow is the delegating workflow of a bundle that may delegate, and through
// which gateway: owned by a Verified UnifaiAgentBundle with spec.delegation, listed among its children. Only such a
// workflow may hold A2A nodes, and only towards that gateway.
func bundleMayDelegate(ctx context.Context, c client.Reader, wf *unifaiv1.UnifaiWorkflow) (string, bool) {
	for _, ref := range wf.OwnerReferences {
		if ref.Kind != "UnifaiAgentBundle" || ref.Controller == nil || !*ref.Controller {
			continue
		}
		var cr unifaiv1.UnifaiAgentBundle
		if err := c.Get(ctx, client.ObjectKey{Namespace: wf.Namespace, Name: ref.Name}, &cr); err != nil {
			return "", false
		}
		if cr.UID != ref.UID || cr.Spec.Delegation == nil || !cr.Status.Verified {
			return "", false
		}
		return strings.TrimRight(cr.Spec.Delegation.GatewayURL, "/") + "/agents/", true
	}
	return "", false
}

// a2aBaseURLs lists the base_url of every A2A node of a resolved blueprint.
func a2aBaseURLs(v any) []string {
	var out []string
	switch t := v.(type) {
	case map[string]any:
		if s, _ := t["type"].(string); s == a2aNodeType {
			if cfg, ok := t["config"].(map[string]any); ok {
				u, _ := cfg["base_url"].(string)
				out = append(out, u)
			}
			return out
		}
		for _, e := range t {
			out = append(out, a2aBaseURLs(e)...)
		}
	case []any:
		for _, e := range t {
			out = append(out, a2aBaseURLs(e)...)
		}
	}
	return out
}
