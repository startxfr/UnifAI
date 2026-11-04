package controller

import (
	"errors"
	"net/http"
	"strings"
	"testing"

	unifaiv1 "github.com/startxfr/unifai-operator/api/v1alpha1"
	"github.com/startxfr/unifai-operator/internal/unifai"
)

func TestDeleteFailureNamesTheOwnerOn403(t *testing.T) {
	tpl := &unifaiv1.UnifaiTemplate{}
	tpl.Spec.Owner = "admin"

	got := deleteFailure(tpl, &unifai.APIError{Status: http.StatusForbidden, Body: "insufficient permissions"})
	if !strings.Contains(got, `spec.owner "admin"`) || !strings.Contains(got, "set spec.owner") {
		t.Fatalf("a 403 should name the owner and the way out, got %q", got)
	}
	if other := deleteFailure(tpl, errors.New("boom")); !strings.Contains(other, "still referenced") {
		t.Fatalf("other errors keep the generic message, got %q", other)
	}
}
