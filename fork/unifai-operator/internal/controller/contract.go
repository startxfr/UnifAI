package controller

import "strings"

// The contract headers the emitted LLMs, MCP providers and A2A nodes send to the gateways behind them:
// X-<Namespace>-<Name>. A bundle's spec.contractNamespace picks the namespace.
const (
	headerAgent           = "Agent"
	headerTask            = "Task"
	headerClassification  = "Data-Classification"
	headerRunID           = "Run-Id"
	headerMaxTokens       = "Max-Tokens"
	headerDelegatedBy     = "Delegated-By"
	headerDelegationDepth = "Delegation-Depth"
	headerTargetTask      = "Task"
)

// defaultContractNamespaces are sent when a bundle sets no contractNamespace: unifai, and zuno until 0.2 so that the
// gateways reading X-Zuno-* keep working across the upgrade. From 0.2: unifai only.
var defaultContractNamespaces = contract{"unifai", "zuno"}

// contract is the namespaces under which an emitted object sends each header.
type contract []string

func contractOf(namespace string) contract {
	if namespace != "" {
		return contract{namespace}
	}
	return defaultContractNamespaces
}

// set puts the header under every namespace of the contract, e.g. X-Unifai-Agent and X-Zuno-Agent.
func (c contract) set(headers map[string]any, name string, value any) {
	for _, ns := range c {
		headers[headerName(ns, name)] = value
	}
}

// headerName is X-<Namespace>-<name>, each dash-separated word of the namespace capitalised (zuno: X-Zuno-Agent).
func headerName(namespace, name string) string {
	words := strings.Split(namespace, "-")
	for i, w := range words {
		if w != "" {
			words[i] = strings.ToUpper(w[:1]) + w[1:]
		}
	}
	return "X-" + strings.Join(words, "-") + "-" + name
}
