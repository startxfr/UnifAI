#!/usr/bin/env bash
# Fails when a deliberate fork divergence from upstream was lost, typically by an upstream sync that took upstream's
# version of the file (run from fork/unifai-operator: `make fork-check`). Each check says what to redo.
set -euo pipefail
root=${1:-../..}
fail=0
need() { # file, fixed string, explanation
  if ! grep -qF -- "$2" "$root/$1"; then
    echo "LOST fork divergence in $1: expected '$2'. $3" >&2
    fail=1
  fi
}
# UI image: nginx reads unifai.crt, the name every operator mounts (0.1.49 mounts unifai.crt only); the Dockerfile
# copies the build-time bundle onto it. Upstream reads unifai_bundle.pem, which crashes the UI under those operators.
need ui/deployment/nginx.conf.template "ssl_certificate /etc/nginx/ssl/unifai.crt;" "Redo: nginx must read unifai.crt (R-523 follow-up, 0.1.50)."
need ui/deployment/Dockerfile "/etc/nginx/ssl/unifai.crt" "Redo: copy ui/UnifAI-secrets/certificates/unifai_bundle.pem to /etc/nginx/ssl/unifai.crt."
exit $fail
