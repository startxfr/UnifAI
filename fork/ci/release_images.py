#!/usr/bin/env python3
"""Resolve the six images a release `vX.Y.Z` ships (fork/RELEASING.md): operator, rag, multiagent, backend, identity, ui.

A release does not rebuild anything. publish-images.yml builds and signs each image on devel as `devel-<sha>` of the
head of the push that changed its code, and only when its code changed. For each component this walks the commit's
first-parent history back to the newest commit that has a `devel-<sha>` image and the same code for that component
(no change under its build paths in between), then checks the image's devel signature and, for the operator, that it
reports the Makefile VERSION.

    release_images.py --version 0.1.52 [--commit HEAD] [--registry quay.io/zuno] [--no-verify] [--out images.json]

Prints and writes {"commit", "version", "images": {component: {"ref": repo@sha256:..., "tag": "devel-<sha>"}}}.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable, Iterable

# Build paths, as publish-images.yml selects them: its own file rebuilds every image, the five application images are
# built together, the operator image also when fork/ci (its signing scripts) changes.
WORKFLOW = ".github/workflows/publish-images.yml"
APP_PATHS = [WORKFLOW, "rag", "multi-agent", "backend", "shared-resources/identity", "ui", "global_utils"]
OPERATOR_PATHS = [WORKFLOW, "fork/ci"] + [
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
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


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
        raise SystemExit("\n".join(errors))
    return {"commit": head, "version": version, "images": images}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--version", required=True, help="the release version without its pre-release part (X.Y.Z)")
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--registry", default="quay.io/zuno")
    p.add_argument("--no-verify", action="store_true", help="skip the cosign check (local inspection only)")
    p.add_argument("--out")
    a = p.parse_args(argv)
    result = resolve(a.version, a.commit, a.registry, not a.no_verify)
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
