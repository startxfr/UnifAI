// Package okftest derives test bundles from the testdata of package okf, for the tests of okf and of the controller.
// It does not import okf (okf's own tests import it), so bundles are plain path -> content maps, assignable to and from
// okf.Files.
package okftest

import (
	"fmt"
	"sort"
	"strings"
)

// TekosResource is the `resource` prefix of the documents of the derived tekos bundle.
const TekosResource = "https://github.com/startxfr/zuno-demo-agents/blob/main/agents/tekos/"

// Maintainer is the zuno.maintainer of the derived agent: the provenance.maintainer of the legacy testdata.
const Maintainer = "Zuno Demo architecture team"

// profileEnvelope replaces the legacy envelope of agent.okf.md (provenance, verification, freshness, free-text sources)
// with the upstream fields, as zuno-demo-agents WP-265 migrated agents/tekos.
const profileEnvelope = `sources:
- id: technical-docs
  resource: urn:zuno:knowledge:tech
  title: Official product documentation, indexed as knowledge.tech
- id: confluence
  resource: urn:zuno:source:confluence
  title: Internal Confluence spaces, through the search_confluence tool
generated:
  by: human:fixture-author
  at: "2026-08-05T00:00:00Z"
verified:
- by: process:zuno-demo-agents/validate_okf_schema
  at: "2026-11-14T10:00:00Z"
status: stable
stale_after: "2027-05-15T00:00:00Z"
`

// Profile10Tekos derives the Zuno OKF profile 1.0 version of testdata/tekos (okf_version v0.2), the way v03_test.go
// derives v0.3 (zuno-demo ADR-0615 clauses 2 to 4):
//   - every document says okf_version "0.2" (quoted), carries a `resource` and zuno.profile "1.0" (the prompt gets a
//     minimal zuno block);
//   - agent.okf.md swaps its legacy envelope for sources[{id, resource, title}], generated, verified, status and
//     stale_after, and provenance.maintainer moves to zuno.maintainer;
//   - a bundle-root index.md whose only frontmatter is okf_version "0.2" lists the documents;
//   - like the v0.3 fixture, the primary task declares an agent skill and a corp skill.
//
// It panics when the testdata no longer has the shape it rewrites.
func Profile10Tekos(legacy map[string][]byte) map[string][]byte {
	out := map[string][]byte{}
	for p, b := range legacy {
		out[p] = b
		if !strings.HasSuffix(p, ".md") || !strings.HasPrefix(string(b), "---\n") {
			continue // README notes: no frontmatter, not OKF documents
		}
		out[p] = []byte(toProfile10(p, string(b)))
	}
	agent := string(out["agent.okf.md"])
	i, j := strings.Index(agent, "\nprovenance:\n"), strings.Index(agent, "\nzuno:\n")
	if i < 0 || j < i {
		panic("okftest: testdata/tekos/agent.okf.md has no legacy envelope before zuno")
	}
	agent = agent[:i+1] + profileEnvelope + agent[j+1:]
	out["agent.okf.md"] = []byte(strings.Replace(agent, "  profile: \"1.0\"\n", "  profile: \"1.0\"\n  maintainer: "+Maintainer+"\n", 1))

	task := string(out["tasks/answer-technical-question.md"])
	out["tasks/answer-technical-question.md"] = []byte(strings.Replace(task, "  profile: \"1.0\"\n",
		"  profile: \"1.0\"\n  skills: [cite-sources, corp/safe-answers]\n", 1))
	out["skills/cite-sources.md"] = []byte("---\nokf_version: \"0.2\"\ntype: skill\ntitle: Cite sources\nresource: " + TekosResource +
		"skills/cite-sources.md\nzuno:\n  profile: \"1.0\"\n  name: cite-sources\n  allowed_tools: [search_confluence]\n---\n\nAlways cite the Confluence pages you used.\n")
	out["skills/corp/safe-answers.md"] = []byte("---\nokf_version: \"0.2\"\ntype: skill\ntitle: Safe answers\nresource: " + TekosResource +
		"skills/corp/safe-answers.md\nzuno:\n  profile: \"1.0\"\n  name: safe-answers\n  allowed_knowledge: [knowledge.tech]\n---\n\nNever reveal credentials.\n")
	out["index.md"] = index(out)
	return out
}

func toProfile10(p, doc string) string {
	end := strings.Index(doc[4:], "\n---\n")
	if end < 0 || !strings.HasPrefix(doc, "---\nokf_version: v0.2\n") {
		panic(fmt.Sprintf("okftest: testdata/tekos/%s is not a v0.2 document", p))
	}
	front, rest := doc[4:4+end+1], doc[4+end+1:]
	front = strings.Replace(front, "okf_version: v0.2\n", "okf_version: \"0.2\"\nresource: "+TekosResource+p+"\n", 1)
	if strings.Contains(front, "\nzuno:\n") {
		front = strings.Replace(front, "\nzuno:\n", "\nzuno:\n  profile: \"1.0\"\n", 1)
	} else {
		front += "zuno:\n  profile: \"1.0\"\n"
	}
	return "---\n" + front + rest
}

// index writes the bundle-root index.md of upstream OKF section 8: no frontmatter but okf_version, then a link to every
// document.
func index(files map[string][]byte) []byte {
	var docs []string
	for p, b := range files {
		if strings.HasSuffix(p, ".md") && strings.HasPrefix(string(b), "---\n") {
			docs = append(docs, p)
		}
	}
	sort.Strings(docs)
	var sb strings.Builder
	sb.WriteString("---\nokf_version: \"0.2\"\n---\n\n# Tekos\n\n")
	for _, p := range docs {
		fmt.Fprintf(&sb, "- [%s](/%s)\n", p, p)
	}
	return []byte(sb.String())
}
