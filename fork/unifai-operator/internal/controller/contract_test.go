package controller

import (
	"reflect"
	"testing"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/okf"
)

func TestHeaderNameCapitalisesEachWordOfTheNamespace(t *testing.T) {
	for ns, want := range map[string]string{"zuno": "X-Zuno-Agent", "unifai": "X-Unifai-Agent", "my-corp": "X-My-Corp-Agent"} {
		if got := headerName(ns, headerAgent); got != want {
			t.Errorf("headerName(%q) = %q, want %q", ns, got, want)
		}
	}
}

// Unset, a bundle sends its headers under unifai and zuno (until 0.2); set, under its namespace only.
func TestContractNamespaceSelectsTheHeaders(t *testing.T) {
	both := map[string]any{}
	contractOf("").set(both, headerTask, "answer")
	if !reflect.DeepEqual(both, map[string]any{"X-Unifai-Task": "answer", "X-Zuno-Task": "answer"}) {
		t.Errorf("default contract: %v", both)
	}
	nodes := a2aNodes(contractOf("acme"), &unifaiv1.BundleDelegation{GatewayURL: "http://gw:8080"}, "arkos", "draft", okf.C2, 100,
		[]delegationTarget{{Agent: "tekos", Task: "answer"}})
	headers := nodes[0]["config"].(map[string]any)["additional_headers"].(map[string]any)
	want := map[string]any{"X-Acme-Run-Id": "{session_id}", "X-Acme-Delegated-By": "arkos:draft", "X-Acme-Delegation-Depth": "1",
		"X-Acme-Task": "answer", "X-Acme-Data-Classification": "C2", "X-Acme-Max-Tokens": "100"}
	if !reflect.DeepEqual(headers, want) {
		t.Errorf("acme contract: %v, want %v", headers, want)
	}
}
