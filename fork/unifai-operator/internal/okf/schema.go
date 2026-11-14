package okf

import (
	"bytes"
	"embed"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"sync"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"sigs.k8s.io/yaml"
)

// Document versions (zuno-demo ADR-0615 clause 5). A profile document says okf_version "0.2", the version of the
// upstream Open Knowledge Format as a quoted string, and zuno.profile "1.0". A legacy document says okf_version "v0.2"
// or "v0.3" and has no zuno.profile; the 0.1 line keeps reading them, a later line (0.2) stops (ADR-0615 clause 13,
// WP-268).
const (
	// UpstreamOKFVersion is the okf_version of every profile document.
	UpstreamOKFVersion = "0.2"
	// Profile10 is the Zuno OKF profile 1.0, frozen (ADR-0615 clause 7).
	Profile10 = "1.0"
)

var (
	// LegacyVersions are the okf_version values of legacy documents.
	LegacyVersions = []string{"v0.2", "v0.3"}
	// Profiles are the zuno.profile values this operator reads: only the profiles whose schemas it embeds.
	Profiles = []string{Profile10}
	// SchemaVersions are the document versions the embedded schemas describe, as DocumentVersion returns them.
	SchemaVersions = []string{"v0.2", "v0.3", Profile10}
)

// DocumentVersion is the dispatch rule of zuno-demo ADR-0615 clause 5, the one zuno-demo-agents implements in
// platform/okf/okf_profile.py. It returns the version a document's frontmatter follows, or an error naming the
// refused value:
//
//	okf_version          zuno.profile             result
//	"v0.2" or "v0.3"     absent                   that legacy version
//	"v0.2" or "v0.3"     present                  refused: zuno.profile needs okf_version "0.2"
//	"0.2"                "1.0"                    "1.0"
//	"0.2"                absent or another value  refused: unsupported zuno.profile
//	anything else        -                        refused: unsupported okf_version
//
// Both keys must be YAML strings: an unquoted 0.2 or 1.0 is a number and is refused.
func DocumentVersion(front map[string]any) (string, error) {
	version, _ := front["okf_version"].(string) // "" for a number or an absent key: refused below
	var profile any
	if zuno, ok := front["zuno"].(map[string]any); ok {
		profile = zuno["profile"]
	}
	switch {
	case slices.Contains(LegacyVersions, version):
		if profile != nil {
			return "", fmt.Errorf("zuno.profile is only valid with okf_version %q (this document says okf_version %q)", UpstreamOKFVersion, version)
		}
		return version, nil
	case version == UpstreamOKFVersion:
		if p, ok := profile.(string); ok && slices.Contains(Profiles, p) {
			return p, nil
		}
		return "", fmt.Errorf("unsupported zuno.profile %s (this operator reads %s)", shownValue(profile), quoted(Profiles))
	default:
		return "", fmt.Errorf("unsupported okf_version %s (this operator reads %q with zuno.profile %s, or legacy %s)",
			shownValue(front["okf_version"]), UpstreamOKFVersion, quoted(Profiles), quoted(LegacyVersions))
	}
}

// shownValue renders a frontmatter value for an error message: a string quoted, anything else as written.
func shownValue(v any) string {
	switch v := v.(type) {
	case nil:
		return "(absent)"
	case string:
		return strconv.Quote(v)
	default:
		return fmt.Sprintf("%v (not a string: quote it)", v)
	}
}

func quoted(values []string) string {
	out := make([]string, len(values))
	for i, v := range values {
		out[i] = strconv.Quote(v)
	}
	return strings.Join(out, ", ")
}

//go:embed schema/*.json
var schemaFS embed.FS

// schemaFiles maps a document version, as DocumentVersion returns it, then a document `type`, to its schema file. The
// `skill` type exists from v0.3 (ADR-0579). The legacy files are frozen; the profile files are copies of
// zuno-demo-agents platform/okf/schema/, refreshed by hack/sync-okf-schemas.sh and recorded in schema/SOURCE. The
// profile's index schema (zuno-okf-profile-1.0-index.schema.json) is embedded with them but not used: the root
// index.md of a profile bundle has no `type`, and documents without one are not read.
var schemaFiles = map[string]map[string]string{
	"v0.2": {
		"agent":  "zuno-okf-v0.2.schema.json",
		"task":   "zuno-okf-task-v0.2.schema.json",
		"prompt": "zuno-okf-prompt-v0.2.schema.json",
		"tool":   "zuno-okf-tool-v0.2.schema.json",
		"rag":    "zuno-okf-rag-v0.2.schema.json",
		"policy": "zuno-okf-policy-v0.2.schema.json",
	},
	"v0.3": {
		"agent":  "zuno-okf-v0.3.schema.json",
		"task":   "zuno-okf-task-v0.3.schema.json",
		"prompt": "zuno-okf-prompt-v0.3.schema.json",
		"tool":   "zuno-okf-tool-v0.3.schema.json",
		"rag":    "zuno-okf-rag-v0.3.schema.json",
		"policy": "zuno-okf-policy-v0.3.schema.json",
		"skill":  "zuno-okf-skill-v0.3.schema.json",
	},
	Profile10: {
		"agent":             "zuno-okf-profile-1.0-agent.schema.json",
		"task":              "zuno-okf-profile-1.0-task.schema.json",
		"prompt":            "zuno-okf-profile-1.0-prompt.schema.json",
		"tool":              "zuno-okf-profile-1.0-tool.schema.json",
		"rag":               "zuno-okf-profile-1.0-rag.schema.json",
		"policy":            "zuno-okf-profile-1.0-policy.schema.json",
		"skill":             "zuno-okf-profile-1.0-skill.schema.json",
		"experience-client": "zuno-okf-profile-1.0-experience-client.schema.json",
	},
}

var (
	schemasOnce sync.Once
	schemas     map[string]map[string]*jsonschema.Schema
	schemasErr  error
)

func compiledSchemas() (map[string]map[string]*jsonschema.Schema, error) {
	schemasOnce.Do(func() {
		c := jsonschema.NewCompiler()
		out := map[string]map[string]*jsonschema.Schema{}
		for version, byType := range schemaFiles {
			out[version] = map[string]*jsonschema.Schema{}
			for typ, file := range byType {
				s, err := compileSchemaFile(c, file)
				if err != nil {
					schemasErr = err
					return
				}
				out[version][typ] = s
			}
		}
		schemas = out
	})
	return schemas, schemasErr
}

func compileSchemaFile(c *jsonschema.Compiler, file string) (*jsonschema.Schema, error) {
	b, err := schemaFS.ReadFile("schema/" + file)
	if err != nil {
		return nil, err
	}
	doc, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	if err := c.AddResource(file, doc); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	s, err := c.Compile(file)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	return s, nil
}

// ValidateSchemas checks the frontmatter of every Markdown file of the bundle that declares a known OKF `type` against
// the embedded schema of that type and of the document's own version (DocumentVersion), so a bundle mixing versions is
// read one document at a time. Files without frontmatter (README notes), without a `type` (the root index.md of a
// profile bundle, whose only key is okf_version) or with a type no embedded schema describes are not read.
func ValidateSchemas(files Files) error {
	sch, err := compiledSchemas()
	if err != nil {
		return fmt.Errorf("embedded OKF schemas: %w", err)
	}
	var problems []string
	for _, p := range files.SortedPaths() {
		if !strings.HasSuffix(p, ".md") || ignored(p) {
			continue
		}
		front, _, err := SplitFrontmatter(files[p])
		if err != nil {
			continue
		}
		js, err := yaml.YAMLToJSON(front)
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: %v", p, err))
			continue
		}
		inst, err := jsonschema.UnmarshalJSON(bytes.NewReader(js))
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: %v", p, err))
			continue
		}
		m, _ := inst.(map[string]any)
		typ, _ := m["type"].(string)
		if _, isDoc := knownType(typ); !isDoc {
			continue
		}
		version, err := DocumentVersion(m)
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: %v", p, err))
			continue
		}
		s, ok := sch[version][typ]
		if !ok {
			continue
		}
		if err := s.Validate(inst); err != nil {
			problems = append(problems, fmt.Sprintf("%s: %s", p, firstLine(err.Error())))
		}
	}
	if len(problems) > 0 {
		return fmt.Errorf("%d OKF documents fail schema validation: %s", len(problems), strings.Join(problems, "; "))
	}
	return nil
}

// knownType reports whether typ is an OKF document type of any embedded version.
func knownType(typ string) (string, bool) {
	for _, byType := range schemaFiles {
		if _, ok := byType[typ]; ok {
			return typ, true
		}
	}
	return "", false
}

func firstLine(s string) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return s[:i] + " " + strings.TrimSpace(strings.SplitN(s[i+1:], "\n", 2)[0])
	}
	return s
}
