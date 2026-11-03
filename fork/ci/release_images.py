#!/usr/bin/env python3
"""Resolve the six images a release `vX.Y.Z` ships (fork/RELEASING.md): operator, rag, multiagent, backend, identity, ui.

A release does not rebuild anything. publish-images.yml builds and signs each image on devel as `devel-<sha>` of the
head of the push that changed its code, and only when its code changed. For each component this walks the commit's
first-parent history back to the newest commit that has a `devel-<sha>` image and the same code for that component
(no change under its build paths in between), then checks the image's devel signature and, for the operator, that it
reports the Makefile VERSION.

    release_images.py --version 0.1.52 [--commit HEAD] [--registry quay.io/zuno] [--no-verify] [--out images.json]
    release_images.py --missing [--commit HEAD]     # the components publish-images must build

Prints and writes {"commit", "version", "images": {component: {"ref": repo@sha256:..., "tag": "devel-<sha>"}}}.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Callable, Iterable

# The paths that make an image's content, as publish-images.yml builds them: its own file rebuilds every image, the
# five application images are built together. fork/ci (the signing scripts) is not image content: changing it does not
# make an image stale, so the digest a canary tested stays the one released.
WORKFLOW = ".github/workflows/publish-images.yml"
APP_PATHS = [WORKFLOW, "rag", "multi-agent", "backend", "shared-resources/identity", "ui", "global_utils"]
OPERATOR_PATHS = [WORKFLOW] + [
    f"fork/unifai-operator/{p}" for p in ("cmd", "api", "internal", "go.mod", "go.sum", "Dockerfile", "Makefile")]
COMPONENTS = {
    "operator": OPERATOR_PATHS,
    "rag": APP_PATHS,
    "multiagent": APP_PATHS,
    "backend": APP_PATHS,
    "identity": APP_PATHS,
    "ui": APP_PATHS,
}
DEVEL_SIGNER = "https://github.com/startxfr/UnifAI/.github/workflows/publish-images.yml@refs/heads/devel"
ISSUER = "https://token.actions.githubusercontent.com"
MAX_COMMITS = 300


def run(*cmd: str) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        msg = f"{' '.join(cmd[:3])}... failed ({r.returncode}): {r.stderr.strip()[:300]}"
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error::{msg}", file=sys.stderr)
        raise SystemExit(msg)
    return r.stdout.strip()


def same_code(commit: str, head: str, paths: list[str]) -> bool:
    return subprocess.run(["git", "diff", "--quiet", commit, head, "--", *paths]).returncode == 0


def find_tag(head: str, paths: list[str], tags: set[str], history: Iterable[str],
             same: Callable[[str, str, list[str]], bool] = same_code) -> str | None:
    """The devel-<sha> tag of the newest commit of `history` that has an image and the code of `head` for `paths`."""
    for commit in history:
        if not same(commit, head, paths):
            return None  # older commits build other code
        tag = f"devel-{commit[:9]}"
        if tag in tags:
            return tag
    return None


def list_tags(repo: str) -> set[str]:
    return set(json.loads(run("skopeo", "list-tags", f"docker://{repo}"))["Tags"])


def missing(commit: str, registry: str) -> list[str]:
    """The components whose code at `commit` has no devel-<sha> image yet: what publish-images must build. Comparing
    with the images (not with the previous push) also catches a change whose own run was cancelled or replaced."""
    head = run("git", "rev-parse", commit)
    history = run("git", "rev-list", "--first-parent", "-n", str(MAX_COMMITS), head).split()
    return [c for c, paths in COMPONENTS.items()
            if find_tag(head, paths, list_tags(f"{registry}/unifai-{c}"), history) is None]


def resolve(version: str, commit: str, registry: str, verify: bool) -> dict:
    head = run("git", "rev-parse", commit)
    history = run("git", "rev-list", "--first-parent", "-n", str(MAX_COMMITS), head).split()
    images, errors = {}, []
    for component, paths in COMPONENTS.items():
        repo = f"{registry}/unifai-{component}"
        tag = find_tag(head, paths, list_tags(repo), history)
        if tag is None:
            errors.append(f"{component}: no {repo}:devel-<sha> for the code of {head[:9]} "
                          "(push to devel and wait for publish-images)")
            continue
        digest = run("skopeo", "inspect", "--no-tags", "--format", "{{.Digest}}", f"docker://{repo}:{tag}")
        ref = f"{repo}@{digest}"
        if verify:
            ok = subprocess.run(["cosign", "verify", "--certificate-identity", DEVEL_SIGNER,
                                 "--certificate-oidc-issuer", ISSUER, ref], capture_output=True).returncode == 0
            if not ok:
                errors.append(f"{component}: {ref} ({tag}) is not signed by {DEVEL_SIGNER}")
                continue
        if component == "operator":
            built = run("skopeo", "inspect", "--no-tags", "--format", '{{index .Labels "version"}}', f"docker://{ref}")
            if built != version:
                errors.append(f"operator: {ref} ({tag}) is operator {built}, the release is {version}")
                continue
        images[component] = {"ref": ref, "tag": tag}
    if errors:
        if os.environ.get("GITHUB_ACTIONS"):
            for e in errors:  # annotations: readable without the run's log
                print(f"::error::{e}", file=sys.stderr)
        raise SystemExit("\n".join(errors))
    return {"commit": head, "version": version, "images": images}


def check_expected(images: dict, expected: list[str]) -> list[str]:
    """Errors for each `component=digest` the resolved images do not match (the digest the canary tested)."""
    errors = []
    for item in expected:
        component, _, digest = item.strip().partition("=")
        if not digest:
            errors.append(f"--expect '{item}': want COMPONENT=sha256:<hex>")
            continue
        got = images.get(component, {}).get("ref", "").rpartition("@")[2]
        if got != digest:
            errors.append(f"{component}: resolved {got or 'nothing'}, expected {digest} "
                          "(a later commit changed its code since it was tested)")
    return errors


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--version", help="the release version without its pre-release part (X.Y.Z)")
    p.add_argument("--missing", action="store_true",
                   help="print the components that have no image for the code of --commit, one per line, and stop")
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--registry", default="quay.io/zuno")
    p.add_argument("--no-verify", action="store_true", help="skip the cosign check (local inspection only)")
    p.add_argument("--out")
    p.add_argument("--expect", action="append", default=[], metavar="COMPONENT=sha256:…",
                   help="fail unless COMPONENT resolves to this digest, e.g. the operator the canary tested (repeatable)")
    a = p.parse_args(argv)
    if a.missing:
        print("\n".join(missing(a.commit, a.registry)))
        return
    if not a.version:
        p.error("--version is required")
    result = resolve(a.version, a.commit, a.registry, not a.no_verify)
    errors = check_expected(result["images"], a.expect)
    if errors:
        if os.environ.get("GITHUB_ACTIONS"):
            for e in errors:
                print(f"::error::{e}", file=sys.stderr)
        raise SystemExit("\n".join(errors))
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
