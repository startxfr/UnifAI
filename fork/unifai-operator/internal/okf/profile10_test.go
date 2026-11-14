package okf

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/startxfr/unifai-operator/internal/okf/okftest"
)

// profile10Tekos is the tekos testdata moved to the Zuno OKF profile 1.0 (zuno-demo ADR-0615), see okftest.
func profile10Tekos(t *testing.T) Files {
	t.Helper()
	return okftest.Profile10Tekos(loadTekos(t))
}

// edit replaces the first old in one file of a copy of the bundle, and fails the test when old is not there.
func edit(t *testing.T, files Files, p, old, new string) Files {
	t.Helper()
	if !strings.Contains(string(files[p]), old) {
		t.Fatalf("%s does not contain %q", p, old)
	}
	out := Files{}
	for k, v := range files {
		out[k] = v
	}
	out[p] = []byte(strings.Replace(string(files[p]), old, new, 1))
	return out
}

// Every row of the dispatch table of ADR-0615 clause 5, on decoded frontmatter: strings as YAML gives them, and
// numbers both as sigs.k8s.io/yaml (float64) and as the schema validator (json.Number) decode an unquoted value.
func TestDocumentVersionDispatchTable(t *testing.T) {
	zuno := func(kv ...any) map[string]any {
		m := map[string]any{}
		for i := 0; i < len(kv); i += 2 {
			m[kv[i].(string)] = kv[i+1]
		}
		return m
	}
	for _, c := range []struct {
		name    string
		front   map[string]any
		want    string
		wantErr string
	}{
		{"legacy v0.2", map[string]any{"okf_version": "v0.2", "zuno": zuno("name", "x")}, "v0.2", ""},
		{"legacy v0.3", map[string]any{"okf_version": "v0.3"}, "v0.3", ""},
		{"legacy with a null profile", map[string]any{"okf_version": "v0.3", "zuno": zuno("profile", nil)}, "v0.3", ""},
		{"legacy carrying a profile", map[string]any{"okf_version": "v0.3", "zuno": zuno("profile", "1.0")}, "",
			`zuno.profile is only valid with okf_version "0.2" (this document says okf_version "v0.3")`},
		{"profile 1.0", map[string]any{"okf_version": "0.2", "zuno": zuno("profile", "1.0")}, "1.0", ""},
		{"upstream without zuno", map[string]any{"okf_version": "0.2"}, "", "unsupported zuno.profile (absent)"},
		{"upstream without a profile", map[string]any{"okf_version": "0.2", "zuno": zuno("name", "x")}, "", "unsupported zuno.profile (absent)"},
		{"upstream with zuno not a mapping", map[string]any{"okf_version": "0.2", "zuno": "1.0"}, "", "unsupported zuno.profile (absent)"},
		{"another profile", map[string]any{"okf_version": "0.2", "zuno": zuno("profile", "1.1")}, "", `unsupported zuno.profile "1.1"`},
		{"unquoted profile", map[string]any{"okf_version": "0.2", "zuno": zuno("profile", 1.0)}, "", "unsupported zuno.profile 1 (not a string"},
		{"unquoted okf_version (yaml)", map[string]any{"okf_version": 0.2, "zuno": zuno("profile", "1.0")}, "", "unsupported okf_version 0.2 (not a string"},
		{"unquoted okf_version (schema)", map[string]any{"okf_version": json.Number("0.2")}, "", "unsupported okf_version 0.2 (not a string"},
		{"unknown legacy version", map[string]any{"okf_version": "v0.4"}, "", `unsupported okf_version "v0.4"`},
		{"future upstream version", map[string]any{"okf_version": "0.3", "zuno": zuno("profile", "1.0")}, "", `unsupported okf_version "0.3"`},
		{"profile number as okf_version", map[string]any{"okf_version": "1.0", "zuno": zuno("profile", "1.0")}, "", `unsupported okf_version "1.0"`},
		{"no okf_version", map[string]any{"type": "agent"}, "", "unsupported okf_version (absent)"},
	} {
		got, err := DocumentVersion(c.front)
		switch {
		case c.wantErr == "" && (err != nil || got != c.want):
			t.Errorf("%s: got %q, %v; want %q", c.name, got, err, c.want)
		case c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)):
			t.Errorf("%s: got %q, %v; want an error containing %q", c.name, got, err, c.wantErr)
		}
	}
}

func TestValidateSchemasAcceptsProfile10(t *testing.T) {
	files := profile10Tekos(t)
	if _, ok := files["index.md"]; !ok {
		t.Fatal("the profile fixture has no root index.md")
	}
	if err := ValidateSchemas(files); err != nil {
		t.Fatalf("a profile 1.0 bundle should satisfy the embedded profile schemas: %v", err)
	}
}

// The same table, end to end: YAML as a bundle carries it, through ValidateSchemas.
func TestValidateSchemasDispatchesEachRow(t *testing.T) {
	const agent = "agent.okf.md"
	profileZuno := "zuno:\n  profile: \"1.0\"\n"
	for _, c := range []struct {
		name    string
		files   Files
		wantErr string
	}{
		{"legacy v0.2", loadTekos(t), ""},
		{"legacy v0.3", v03Tekos(t), ""},
		{"profile 1.0", profile10Tekos(t), ""},
		{"legacy v0.3 carrying zuno.profile", edit(t, v03Tekos(t), agent, "zuno:\n", profileZuno), "zuno.profile is only valid"},
		{"okf_version 0.2 without a profile", edit(t, profile10Tekos(t), agent, "  profile: \"1.0\"\n", ""), "agent.okf.md: unsupported zuno.profile (absent)"},
		{"okf_version 0.2, profile 1.1", edit(t, profile10Tekos(t), agent, "profile: \"1.0\"", "profile: \"1.1\""), `agent.okf.md: unsupported zuno.profile "1.1"`},
		{"unquoted profile", edit(t, profile10Tekos(t), agent, "profile: \"1.0\"", "profile: 1.0"), "agent.okf.md: unsupported zuno.profile 1 (not a string"},
		{"unquoted okf_version", edit(t, profile10Tekos(t), agent, "okf_version: \"0.2\"", "okf_version: 0.2"), "agent.okf.md: unsupported okf_version 0.2 (not a string"},
		{"okf_version v0.4", edit(t, v03Tekos(t), agent, "okf_version: v0.3", "okf_version: v0.4"), `agent.okf.md: unsupported okf_version "v0.4"`},
		{"okf_version absent", edit(t, profile10Tekos(t), agent, "okf_version: \"0.2\"\n", ""), "agent.okf.md: unsupported okf_version (absent)"},
	} {
		err := ValidateSchemas(c.files)
		switch {
		case c.wantErr == "" && err != nil:
			t.Errorf("%s: %v", c.name, err)
		case c.wantErr != "" && (err == nil || !strings.Contains(err.Error(), c.wantErr)):
			t.Errorf("%s: got %v, want an error containing %q", c.name, err, c.wantErr)
		}
	}
}

// Each version is checked against its own schemas: the legacy envelope is refused in a profile document, the profile's
// keys are refused in a legacy one.
func TestValidateSchemasAppliesTheSchemasOfTheDocumentVersion(t *testing.T) {
	files := edit(t, profile10Tekos(t), "agent.okf.md", "status: stable\n", "status: stable\nprovenance:\n  maintainer: x\n")
	if err := ValidateSchemas(files); err == nil || !strings.Contains(err.Error(), "agent.okf.md") {
		t.Fatalf("provenance in a profile 1.0 agent passed: %v", err)
	}
	files = edit(t, v03Tekos(t), "agent.okf.md", "zuno:\n", "zuno:\n  maintainer: x\n")
	if err := ValidateSchemas(files); err == nil || !strings.Contains(err.Error(), "agent.okf.md") {
		t.Fatalf("zuno.maintainer in a v0.3 agent passed: %v", err)
	}
	files = edit(t, profile10Tekos(t), "tasks/write-code.md", "resource: ", "x-resource: ")
	if err := ValidateSchemas(files); err == nil || !strings.Contains(err.Error(), "tasks/write-code.md") {
		t.Fatalf("a profile 1.0 task without its resource passed: %v", err)
	}
}

// ADR-0615 clause 5: the version is checked one document at a time, so a bundle mixing profile 1.0 and legacy
// documents is read, each document against its own schema.
func TestValidateSchemasReadsAMixedBundle(t *testing.T) {
	files := profile10Tekos(t)
	files["tasks/write-code.md"] = loadTekos(t)["tasks/write-code.md"]
	if err := ValidateSchemas(files); err != nil {
		t.Fatalf("a v0.2 task in a profile 1.0 bundle: %v", err)
	}
	if _, err := Parse(files); err != nil {
		t.Fatalf("a v0.2 task in a profile 1.0 bundle: %v", err)
	}
}

// The root index.md of a profile bundle has okf_version "0.2" and no type: DocumentVersion would refuse it (no
// zuno.profile), so it must be skipped like any document without a type, in a profile bundle as in a legacy one.
func TestValidateSchemasSkipsTheRootIndex(t *testing.T) {
	idx := profile10Tekos(t)["index.md"]
	if _, err := DocumentVersion(map[string]any{"okf_version": "0.2"}); err == nil {
		t.Fatal("the index frontmatter alone should not dispatch")
	}
	legacy := loadTekos(t)
	legacy["index.md"] = idx
	for name, files := range map[string]Files{"profile": profile10Tekos(t), "legacy": legacy} {
		if err := ValidateSchemas(files); err != nil {
			t.Errorf("%s bundle with a root index.md: %v", name, err)
		}
		if _, err := Parse(files); err != nil {
			t.Errorf("%s bundle with a root index.md: %v", name, err)
		}
	}
}

// Documents with a type no embedded schema describes are still skipped, whatever their version.
func TestValidateSchemasSkipsUnknownTypes(t *testing.T) {
	files := profile10Tekos(t)
	files["notes/runbook.md"] = []byte("---\nokf_version: v9\ntype: runbook\n---\n\nbody\n")
	files["notes/concept.md"] = []byte("---\nokf_version: \"0.2\"\ntype: concept\n---\n\nAn upstream concept page.\n")
	if err := ValidateSchemas(files); err != nil {
		t.Fatalf("documents of an unknown type are not read: %v", err)
	}
}

func TestParseProfile10(t *testing.T) {
	b, err := Parse(profile10Tekos(t))
	if err != nil {
		t.Fatal(err)
	}
	if b.OKFVersion != UpstreamOKFVersion || b.Profile != Profile10 {
		t.Fatalf("versions: okf_version %q, profile %q", b.OKFVersion, b.Profile)
	}
	if b.Name != "tekos" || b.Status != "active" || b.Classification != C1 || len(b.Tasks) != 4 || b.Description == "" {
		t.Fatalf("unexpected bundle %+v", b)
	}
	if b.Maintainer != okftest.Maintainer {
		t.Fatalf("maintainer %q, want zuno.maintainer %q", b.Maintainer, okftest.Maintainer)
	}
	var primary Task
	for _, tk := range b.Tasks {
		if tk.Name == b.PrimaryTask {
			primary = tk
		}
	}
	msg := b.SystemMessage(primary)
	if !strings.HasPrefix(msg, "You are Tekos") || strings.Contains(msg, "profile:") {
		t.Fatalf("the system message must be the prompt body, without its frontmatter: %.80q", msg)
	}
	if i, j := strings.Index(msg, "Always cite"), strings.Index(msg, "Never reveal"); i < 0 || j < i {
		t.Fatalf("the profile 1.0 skills must follow the prompt in order:\n%s", msg)
	}
	// The profile envelope is advisory metadata: none of it is reported unmapped.
	for _, u := range b.Unmapped {
		for _, key := range []string{"resource", "sources", "verified", "stale_after", "generated", "maintainer"} {
			if strings.HasPrefix(u, key) {
				t.Errorf("envelope field reported unmapped: %s", u)
			}
		}
	}
}

// status.display.maintainer: zuno.maintainer in profile 1.0, else the legacy provenance.maintainer.
func TestParseMaintainer(t *testing.T) {
	files := edit(t, profile10Tekos(t), "agent.okf.md", "  maintainer: "+okftest.Maintainer+"\n", "  maintainer: Profile maintainers\n")
	if b, err := Parse(files); err != nil || b.Maintainer != "Profile maintainers" {
		t.Fatalf("profile 1.0: %+v, %v", b, err)
	}
	if b, err := Parse(edit(t, files, "agent.okf.md", "  maintainer: Profile maintainers\n", "")); err != nil || b.Maintainer != "" {
		t.Fatalf("profile 1.0 without zuno.maintainer: %q, %v", b.Maintainer, err)
	}
	legacy, err := Parse(loadTekos(t))
	if err != nil || legacy.Maintainer != "Zuno Demo architecture team" || legacy.Profile != "" {
		t.Fatalf("legacy v0.2: %+v, %v", legacy, err)
	}
	// zuno.maintainer wins when both are present (only a document no schema admits has both).
	both, err := Parse(edit(t, loadTekos(t), "agent.okf.md", "zuno:\n", "zuno:\n  maintainer: Profile maintainers\n"))
	if err != nil || both.Maintainer != "Profile maintainers" {
		t.Fatalf("both maintainers: %q, %v", both.Maintainer, err)
	}
}

// Parse applies the dispatch to agent.okf.md itself, so a caller that skips ValidateSchemas still gets the refusal.
func TestParseRefusesAnUnsupportedVersion(t *testing.T) {
	for _, c := range []struct{ old, new, want string }{
		{"okf_version: \"0.2\"", "okf_version: 0.2", "unsupported okf_version 0.2"},
		{"profile: \"1.0\"", "profile: \"2.0\"", `unsupported zuno.profile "2.0"`},
	} {
		if _, err := Parse(edit(t, profile10Tekos(t), "agent.okf.md", c.old, c.new)); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: got %v, want %q", c.new, err, c.want)
		}
	}
}

// Parse dispatches every document it reads, not only agent.okf.md, so it does not rely on ValidateSchemas having run
// first (the invalid-task-unsupported-version case of zuno-demo-agents).
func TestParseRefusesAnUnsupportedVersionInATask(t *testing.T) {
	files := edit(t, profile10Tekos(t), "tasks/write-code.md", "okf_version: \"0.2\"", "okf_version: \"0.9\"")
	if _, err := Parse(files); err == nil || !strings.Contains(err.Error(), `tasks/write-code.md: unsupported okf_version "0.9"`) {
		t.Fatalf("a task with okf_version 0.9 parsed: %v", err)
	}
	files = edit(t, v03Tekos(t), "tasks/write-code.md", "okf_version: v0.3", "okf_version: v0.4")
	if _, err := Parse(files); err == nil || !strings.Contains(err.Error(), `tasks/write-code.md: unsupported okf_version "v0.4"`) {
		t.Fatalf("a legacy task with okf_version v0.4 parsed: %v", err)
	}
}
