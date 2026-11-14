package okf

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"
	"testing"
	"testing/fstest"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

var (
	sourceSumLine    = regexp.MustCompile(`^([0-9a-f]{64})  (\S+\.schema\.json)$`)
	sourceCommitLine = regexp.MustCompile(`^agents-commit: [0-9a-f]{40}$`)
)

// checkSchemaSource compares the schemas embedded under schema/ with the hashes schema/SOURCE records: every embedded
// schema is listed with its sha256, every listed file is embedded, and SOURCE names the agents commit of the profile
// files. hack/sync-okf-schemas.sh writes SOURCE.
func checkSchemaSource(schemas fs.FS, source []byte) error {
	want := map[string]string{}
	commit := false
	for _, line := range strings.Split(string(source), "\n") {
		if m := sourceSumLine.FindStringSubmatch(line); m != nil {
			want[m[2]] = m[1]
		}
		commit = commit || sourceCommitLine.MatchString(line)
	}
	embedded, err := fs.Glob(schemas, "schema/*.schema.json")
	if err != nil {
		return err
	}
	problems := make([]string, 0, len(embedded)+len(want)+1)
	if !commit {
		problems = append(problems, "SOURCE names no agents-commit")
	}
	for _, p := range embedded {
		name := path.Base(p)
		b, err := fs.ReadFile(schemas, p)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(b)
		got := hex.EncodeToString(sum[:])
		recorded, ok := want[name]
		delete(want, name)
		switch {
		case !ok:
			problems = append(problems, name+" is embedded but not recorded in SOURCE")
		case recorded != got && strings.HasPrefix(name, "zuno-okf-profile-"):
			problems = append(problems, fmt.Sprintf("%s has sha256 %s, SOURCE records %s: a profile is frozen, re-run hack/sync-okf-schemas.sh <agents-ref> instead of editing it", name, got, recorded))
		case recorded != got:
			problems = append(problems, fmt.Sprintf("%s has sha256 %s, SOURCE records %s: the legacy schemas are frozen", name, got, recorded))
		}
	}
	for name := range want {
		problems = append(problems, name+" is recorded in SOURCE but not embedded")
	}
	if len(problems) > 0 {
		sort.Strings(problems)
		return fmt.Errorf("embedded OKF schemas differ from schema/SOURCE: %s", strings.Join(problems, "; "))
	}
	return nil
}

func readSource(t *testing.T) []byte {
	t.Helper()
	b, err := os.ReadFile("schema/SOURCE")
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// zuno-demo ADR-0615 clause 7: the embedded profile schemas are the frozen files of zuno-demo-agents, and the legacy
// ones stay as they are. A hand edit, a partial sync or a schema added without the script fails here.
func TestEmbeddedSchemasMatchSource(t *testing.T) {
	if err := checkSchemaSource(schemaFS, readSource(t)); err != nil {
		t.Fatal(err)
	}
	for _, byType := range schemaFiles {
		for _, file := range byType {
			if !bytes.Contains(readSource(t), []byte("  "+file+"\n")) {
				t.Errorf("%s is used but not recorded in SOURCE", file)
			}
		}
	}
}

// The drift check itself: one changed byte, a schema missing from SOURCE or a recorded schema not embedded fails it.
func TestSchemaSourceCheckFailsOnDrift(t *testing.T) {
	copyFS := func() fstest.MapFS {
		out := fstest.MapFS{}
		paths, err := fs.Glob(schemaFS, "schema/*.schema.json")
		if err != nil || len(paths) == 0 {
			t.Fatalf("no embedded schema: %v", err)
		}
		for _, p := range paths {
			b, _ := fs.ReadFile(schemaFS, p)
			out[p] = &fstest.MapFile{Data: bytes.Clone(b)}
		}
		return out
	}
	source := readSource(t)
	if err := checkSchemaSource(copyFS(), source); err != nil {
		t.Fatalf("an exact copy must pass: %v", err)
	}
	for _, name := range []string{"zuno-okf-profile-1.0-agent.schema.json", "zuno-okf-v0.3.schema.json"} {
		changed := copyFS()
		data := changed["schema/"+name].Data
		data[len(data)/2] ^= 0x01
		if err := checkSchemaSource(changed, source); err == nil || !strings.Contains(err.Error(), name) {
			t.Errorf("one changed byte in %s passed: %v", name, err)
		}
	}
	extra := copyFS()
	extra["schema/zuno-okf-profile-1.1-agent.schema.json"] = &fstest.MapFile{Data: []byte("{}")}
	if err := checkSchemaSource(extra, source); err == nil || !strings.Contains(err.Error(), "not recorded") {
		t.Errorf("an unrecorded schema passed: %v", err)
	}
	missing := copyFS()
	delete(missing, "schema/zuno-okf-profile-1.0-task.schema.json")
	if err := checkSchemaSource(missing, source); err == nil || !strings.Contains(err.Error(), "not embedded") {
		t.Errorf("a recorded schema that is not embedded passed: %v", err)
	}
	if err := checkSchemaSource(copyFS(), bytes.ReplaceAll(source, []byte("agents-commit:"), []byte("agents-ref:"))); err == nil {
		t.Error("a SOURCE without its agents commit passed")
	}
}

// Every embedded schema compiles, including the profile's index schema, which no document type maps to.
func TestEveryEmbeddedSchemaCompiles(t *testing.T) {
	paths, err := fs.Glob(schemaFS, "schema/*.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range paths {
		if _, err := compileSchemaFile(jsonschema.NewCompiler(), path.Base(p)); err != nil {
			t.Errorf("%s: %v", p, err)
		}
	}
	if _, err := compiledSchemas(); err != nil {
		t.Fatal(err)
	}
}
