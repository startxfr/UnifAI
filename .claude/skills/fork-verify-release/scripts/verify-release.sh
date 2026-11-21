#!/usr/bin/env bash
# Verify a published release of the startxfr/UnifAI fork, read only (fork/docs/releasing.md, .github/workflows/release.yml).
#
#   verify-release.sh X.Y.Z sha256:<64 hex of the canaried operator>
#
# Reads: the GitHub API (gh -R startxfr/UnifAI), quay.io (skopeo, cosign, opm, anonymous), `git fetch` of origin.
# Writes nothing anywhere but a temporary directory, removed on exit. Exit 0 only when every check is OK.
# Needs: gh (logged in), git, python3 with PyYAML, skopeo, cosign, opm.
set -uo pipefail

V="${1:-}"; OP_EXPECTED="${2:-}"
if ! [[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || ! [[ "$OP_EXPECTED" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "usage: $0 X.Y.Z sha256:<64 hex>   (the FULL digest of the canaried operator, not a short one)" >&2
  exit 2
fi
GH=startxfr/UnifAI
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
SIGNER="https://github.com/$GH/.github/workflows/release.yml@refs/tags/v$V"
ISSUER=https://token.actions.githubusercontent.com
COSIGN="$(command -v cosign || echo /home/cl/.local/bin/cosign)"
W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
fail=0
ok() { echo "OK   $*"; }
ko() { echo "FAIL $*"; fail=1; }
info() { echo "INFO $*"; }
for t in gh git python3 skopeo opm "$COSIGN"; do command -v "$t" > /dev/null || { echo "missing tool: $t" >&2; exit 2; }; done
cd "$REPO" || exit 2

echo "== 1. Tag and release run, from the GitHub API"
# gh api prints the 404 body on stdout: trust the exit code, not the output.
if ! tagobj="$(gh api "repos/$GH/git/ref/tags/v$V" --jq '.object.type + " " + .object.sha' 2> /dev/null)"; then
  ko "tag v$V not found on $GH"; echo "RESULT: v$V is NOT published"; exit 1
fi
read -r ttype tsha <<< "$tagobj"
[ "$ttype" = tag ] && TAGC="$(gh api "repos/$GH/git/tags/$tsha" --jq '.object.sha')" || TAGC="$tsha"
ok "tag v$V ($ttype) -> commit $TAGC"
# A tag can have several runs (R-561: a failed run on the first cut, a green one on the re-cut): judge the newest run
# on the tag's commit, list the others.
gh -R "$GH" run list --workflow release.yml --branch "v$V" --limit 20 \
  --json databaseId,headSha,status,conclusion,createdAt,url > "$W/runs.json"
python3 - "$W/runs.json" "$TAGC" <<'PY' || fail=1
import json, sys
runs, sha = json.load(open(sys.argv[1])), sys.argv[2]
mine = sorted((r for r in runs if r["headSha"] == sha), key=lambda r: r["createdAt"])
for r in runs:
    if r["headSha"] != sha:
        print(f"INFO older run on another commit {r['headSha'][:9]}: {r['conclusion'] or r['status']} {r['url']}")
if not mine:
    print(f"FAIL no release.yml run on the tag commit {sha[:9]}"); sys.exit(1)
r = mine[-1]
good = r["status"] == "completed" and r["conclusion"] == "success"
print(("OK   " if good else "FAIL ") + f"release.yml run {r['databaseId']}: {r['status']} {r['conclusion']} {r['url']}")
sys.exit(0 if good else 1)
PY
gh -R "$GH" release view "v$V" --json isDraft,isPrerelease,publishedAt > "$W/rel.json" 2>/dev/null \
  && python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(r['isDraft'] or r['isPrerelease'])" "$W/rel.json" \
  && ok "GitHub release v$V published ($(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['publishedAt'])" "$W/rel.json"))" \
  || ko "GitHub release v$V missing, draft or pre-release"
if ! gh -R "$GH" release download "v$V" -p release.json -D "$W" 2> /dev/null; then
  ko "release.json not attached to v$V"; echo "RESULT: FAILED"; exit 1
fi

echo "== 2. release.json"
python3 - "$W/release.json" "$V" "$TAGC" "$SIGNER" "$ISSUER" "$OP_EXPECTED" > "$W/check.txt" <<'PY'
import json, re, sys
r = json.load(open(sys.argv[1])); v, commit, signer, issuer, op = sys.argv[2:7]
ref = re.compile(r"^quay\.io/zuno/[a-z-]+@sha256:[0-9a-f]{64}$")
def chk(cond, msg): print(("OK   " if cond else "FAIL ") + msg)
chk(r.get("version") == v, f"version {r.get('version')}")
chk(r.get("commit") == commit, f"commit {r.get('commit')} (tag commit {commit[:9]})")
chk(r.get("signer") == signer, f"signer {r.get('signer')}")
chk(r.get("issuer") == issuer, f"issuer {r.get('issuer')}")
imgs = r.get("images", {})
chk(set(imgs) == {"operator", "rag", "multiagent", "backend", "identity", "ui"}, "6 images: " + ",".join(imgs))
arts = {f"image {k}": i.get("ref", "") for k, i in imgs.items()} | {"bundle": r.get("bundle", ""), "catalog": r.get("catalog", "")}
chk(len(arts) == 8 and all(ref.match(x) for x in arts.values()), f"{len(arts)} artefacts, all quay.io/zuno/…@sha256 references")
got = imgs.get("operator", {}).get("ref", "").partition("@")[2]
chk(got == op, f"operator {got} = canaried {op}")
print(f"INFO kind {r.get('kind')}, channel {r.get('channel')}")
for name, x in arts.items():
    print(f"ART {name} {x}")
PY
grep -v '^ART ' "$W/check.txt"; grep -q '^FAIL' "$W/check.txt" && fail=1
grep '^ART ' "$W/check.txt" | cut -d' ' -f2- > "$W/arts.txt"
KIND="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['kind'])" "$W/release.json")"
CATALOG="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['catalog'])" "$W/release.json")"

echo "== 3. Registry tags v$V = release.json digests (raw manifest digest: since 2026-11-19 they are OCI indexes, R-561)"
while read -r name ref; do
  repo="${ref%@*}"; want="${ref#*@}"
  raw="$(skopeo inspect --raw "docker://$repo:v$V" 2> /dev/null)" || { ko "$name: $repo:v$V not readable"; continue; }
  got="sha256:$(printf '%s' "$raw" | sha256sum | cut -d' ' -f1)"
  mt="$(printf '%s' "$raw" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mediaType","?").rsplit(".",2)[-2])' 2> /dev/null)"
  [ "$got" = "$want" ] && ok "$name: $repo:v$V = ${want:7:12}… ($mt)" || ko "$name: $repo:v$V is $got, release.json says $want"
done < <(sed 's/^image /image-/' "$W/arts.txt")

echo "== 4. cosign verify, identity release.yml@refs/tags/v$V"
n=0; t=0
while read -r name ref; do
  t=$((t + 1))
  if "$COSIGN" verify --certificate-identity "$SIGNER" --certificate-oidc-issuer "$ISSUER" "$ref" > /dev/null 2>&1; then
    n=$((n + 1)); ok "cosign $name"
  else ko "cosign $name $ref"; fi
done < <(sed 's/^image /image-/' "$W/arts.txt")
[ "$n" = 8 ] && [ "$t" = 8 ] && ok "cosign $n/$t" || ko "cosign $n/$t (8/8 expected)"

echo "== 5. Post-release commit (next VERSION, rendered catalog) = release.json"
IFS=. read -r ma mi pa <<< "$V"; NEXT="$ma.$mi.$((pa + 1))"
BR=devel; [ "$KIND" = hotfix ] && BR="release-$ma.$mi"
git fetch -q origin "+refs/heads/$BR:refs/remotes/origin/$BR" --tags 2> /dev/null || ko "git fetch origin $BR"
PR="$(git log "origin/$BR" -F --grep="release(fork): v$V published, next VERSION $NEXT" --format='%H' -1)"
if [ -z "$PR" ]; then
  ko "no 'release(fork): v$V published, next VERSION $NEXT' on origin/$BR"
else
  ok "post-release commit $(git log -1 --format='%h %an: %s' "$PR")"
  git show "$PR:fork/unifai-operator/catalog/unifai-operator/catalog.yaml" > "$W/repo-catalog.yaml" 2> /dev/null
  python3 - "$W/release.json" "$V" "$NEXT" "$KIND" "$W/repo-catalog.yaml" \
    <(git show "$PR:fork/unifai-operator/Makefile") \
    <(git show "$PR:fork/unifai-operator/config/manager/kustomization.yaml") \
    <(git show "$PR:fork/unifai-operator/bundle/manifests/unifai-operator.clusterserviceversion.yaml") <<'PY' || fail=1
import json, re, sys, yaml
rel, v, nxt, kind, cat, mk, kus, csv = sys.argv[1:9]
r = json.load(open(rel)); op = r["images"]["operator"]["ref"]; bad = 0
def chk(cond, msg):
    global bad
    print(("OK   " if cond else "FAIL ") + msg); bad += not cond
m = re.search(r"^VERSION \?= (\S+)$", open(mk).read(), re.M)
chk(m and m.group(1) == nxt, f"Makefile VERSION {m and m.group(1)} (next {nxt})")
k = yaml.safe_load(open(kus))
chk(any(i.get("digest") == op.partition("@")[2] for i in k.get("images", [])), "config/manager/kustomization.yaml digest = release.json operator")
c = yaml.safe_load(open(csv))
chk(c["metadata"]["name"] == f"unifai-operator.v{v}", f"CSV {c['metadata']['name']}")
chk(c["metadata"]["annotations"].get("containerImage") == op, "CSV containerImage = release.json operator")
if kind == "hotfix":
    print("INFO hotfix: the catalog is committed to devel ('hotfix recorded in the stable channel'), not checked here")
else:
    docs = [d for d in yaml.safe_load_all(open(cat)) if d]
    b = [d for d in docs if d.get("schema") == "olm.bundle" and d.get("name") == f"unifai-operator.v{v}"]
    chk(len(b) == 1 and b[0].get("image") == f"quay.io/zuno/unifai-operator-bundle:v{v}", f"catalog.yaml: bundle v{v}")
    rel_imgs = {i["image"] for i in (b[0].get("relatedImages", []) if b else [])}
    chk(op in rel_imgs, "catalog.yaml: bundle v%s relatedImages carry the released operator" % v)
    a = next((d for d in docs if d.get("schema") == "olm.channel" and d.get("name") == "alpha"), {})
    chk(a.get("entries", [{}])[-1].get("name") == f"unifai-operator.v{v}", f"catalog.yaml: alpha head v{v}")
sys.exit(1 if bad else 0)
PY
  [ "$(git rev-parse "origin/$BR")" = "$PR" ] || info "origin/$BR moved on since: $(git log --oneline -1 "origin/$BR")"
fi

echo "== 6. opm render of the published catalog: alpha has only replaces, skipRange only on stable"
if opm render "$CATALOG" -o json > "$W/render.json" 2> "$W/render.err"; then
  python3 - "$W/render.json" "$V" "$KIND" "$W/repo-catalog.yaml" <<'PY' || fail=1
import json, sys, yaml
raw, v, kind, repo_cat = open(sys.argv[1]).read(), sys.argv[2], sys.argv[3], sys.argv[4]
dec, i, docs = json.JSONDecoder(), 0, []
while i < len(raw):
    if raw[i].isspace(): i += 1; continue
    d, i = dec.raw_decode(raw, i); docs.append(d)
ch = {d["name"]: d["entries"] for d in docs if d.get("schema") == "olm.channel"}
bad = 0
def chk(cond, msg):
    global bad
    print(("OK   " if cond else "FAIL ") + msg); bad += not cond
target = "stable" if kind == "hotfix" else "alpha"
names = {e["name"] for e in ch.get(target, [])}
chk(f"unifai-operator.v{v}" in names, f"v{v} in channel {target} (channels: {', '.join(sorted(ch))})")
alpha = ch.get("alpha", [])
extra = [e["name"] for e in alpha if set(e) - {"name", "replaces"}]
chk(not extra, "alpha: only name/replaces, no skips or skipRange" + (f" ({extra[:5]})" if extra else ""))
# One chain: from the head, `replaces` reaches every alpha entry.
by, heads = {e["name"]: e for e in alpha}, {e["name"] for e in alpha} - {e.get("replaces") for e in alpha}
seen, cur = 0, next(iter(heads)) if len(heads) == 1 else None
while cur in by:
    seen += 1; cur = by[cur].get("replaces")
chk(len(heads) == 1 and seen == len(alpha), f"alpha: one replaces chain, head {sorted(heads)}, {seen}/{len(alpha)} entries")
skips = [e["name"] for c, es in ch.items() for e in es if "skips" in e]
sr = [f"{c}:{e['name']}" for c, es in ch.items() for e in es if "skipRange" in e]
chk(not skips, "no skips in any channel" + (f" ({skips[:5]})" if skips else ""))
chk(all(s.startswith("stable:") for s in sr), "skipRange only on stable (promote.py)" + (f": {sr}" if sr else ": none yet"))
try:
    repo = [d for d in yaml.safe_load_all(open(repo_cat)) if d]
    ra = next(d["entries"] for d in repo if d.get("schema") == "olm.channel" and d.get("name") == "alpha")
    chk(ra == alpha, "alpha of the published catalog = alpha of the post-release commit's catalog.yaml")
except Exception as e:  # no post-release commit or a hotfix: already reported above
    print(f"INFO alpha not compared with the repository: {e.__class__.__name__}")
sys.exit(1 if bad else 0)
PY
else
  ko "opm render $CATALOG: $(tail -1 "$W/render.err")"
fi

echo
if [ "$fail" != 0 ]; then
  echo "RESULT: v$V NOT verified, see the FAIL lines. Do not announce it."
  exit 1
fi
echo "RESULT: v$V verified (tag, green release run, release.json, registry tags, cosign 8/8, post-release commit, catalog)"
echo
echo "---- message for zuno-demo-hachley (cc zuno-demo-cluster, helm-hachley), in French as fork-peer-brief asks ----"
python3 - "$W/release.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); v = r["version"]
print(f"UnifAI v{v} publiée et vérifiée ({r['kind']}, canal {r['channel']}, commit {r['commit'][:9]}).")
print(f"Release : https://github.com/startxfr/UnifAI/releases/tag/v{v} (release.json joint). Pin par digest uniquement :")
print(f"  operator   {r['images']['operator']['ref']}")
print(f"  bundle     {r['bundle']}")
print(f"  catalog    {r['catalog']}")
for k in ("rag", "multiagent", "backend", "identity", "ui"):
    print(f"  {k:<10} {r['images'][k]['ref']}")
print(f"Signataire : {r['signer']} (issuer {r['issuer']}) ; cosign verify OK sur les 8.")
print("Rien n'est posé sur demo333 sans le go du propriétaire dans la session zuno-demo-cluster.")
PY
