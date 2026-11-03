#!/usr/bin/env bash
# Runs the light e2e suite (make test-e2e, no E2E_FULL) on a throwaway kind cluster: the gate of a release
# (fork/RELEASING.md, phase 2), on a GitHub runner or a workstation with docker or podman.
#
#   hack/kind/e2e.sh <operator image (repo@sha256:...)> <UnifAI images tag (e.g. devel-<sha>)>
#
# What kind lacks compared with OpenShift, and how it is stood in for:
# - the Route API: a bare CRD (route-crd.yaml), no router, so the test skips what goes through a Route
#   (E2E_EXTERNAL=0);
# - the cluster apps domain: E2E_DOMAIN gives the stack its hosts;
# - ReadWriteMany storage: static hostPath volumes of a class `e2e-shared` (one node, so they are shared);
# - Prometheus: the operator's ServiceMonitor is left out.
# Set KEEP_CLUSTER=1 to keep the cluster afterwards (kind delete cluster --name unifai-e2e).
set -euo pipefail

operator="${1:?operator image repo@sha256:...}"
version="${2:?UnifAI images tag}"
cluster="${KIND_CLUSTER:-unifai-e2e}"
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)" # fork/unifai-operator
cd "$root"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    echo "::group::cluster state on failure"
    kubectl get pods -A -o wide || true
    kubectl get pvc -A || true
    kubectl get events -A --sort-by=.lastTimestamp | tail -n 80 || true
    kubectl -n unifai-operator-system logs deploy/unifai-operator-controller-manager --tail=200 || true
    echo "::endgroup::"
    if [ -n "${GITHUB_ACTIONS:-}" ]; then
      # Annotations (readable without the run's log): the pods that are not up, and why.
      kubectl get pods -A --no-headers 2>/dev/null | awk '$4 != "Running" && $4 != "Completed" {print "::error::pod " $1 "/" $2 " " $3 " " $4 " restarts=" $5}' || true
      kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{" "}{range .status.containerStatuses[*]}{.state.waiting.reason}{":"}{.state.waiting.message}{" "}{end}{"\n"}{end}' 2>/dev/null |
        grep -E 'ImagePull|ErrImage|CrashLoop|CreateContainer' | cut -c1-400 | sed 's/^/::error::waiting /' || true
      kubectl get pvc -A --no-headers 2>/dev/null | awk '$3 != "Bound" {print "::error::pvc " $1 "/" $2 " " $3}' || true
      kubectl get events -A --field-selector type=Warning --no-headers 2>/dev/null | tail -n 15 | cut -c1-400 | sed 's/^/::warning::event /' || true
      df -h / | tail -n1 | sed 's/^/::notice::disk /' || true
    fi
  fi
  [ -n "${KEEP_CLUSTER:-}" ] || kind delete cluster --name "$cluster" || true
}
trap cleanup EXIT

kind create cluster --name "$cluster" --wait 120s
kubectl apply -f "$here/route-crd.yaml"

# Shared volumes: the stack claims two ReadWriteMany volumes (RAG and multiagent uploads) per namespace.
cat <<'EOF' | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: e2e-shared
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: Immediate
reclaimPolicy: Delete
EOF
for i in 1 2 3 4 5 6; do
  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: e2e-shared-$i
spec:
  storageClassName: e2e-shared
  capacity: {storage: 200Gi}
  accessModes: [ReadWriteMany, ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  hostPath: {path: /var/local/e2e-shared-$i, type: DirectoryOrCreate}
EOF
done

# The operator, from its kustomize config (no OLM, no ServiceMonitor), on the image under test.
make manifests kustomize > /dev/null
(cd config/manager && "$root/bin/kustomize" edit set image controller="$operator")
bin/kustomize build config/default | yq 'select(.kind != "ServiceMonitor")' | kubectl apply --server-side -f -
git checkout -- config/manager/kustomization.yaml
kubectl -n unifai-operator-system rollout status deploy/unifai-operator-controller-manager --timeout=300s

# What `make test-e2e` runs, with the kind values (E2E_DOMAIN and E2E_EXTERNAL are read by the tests only).
E2E_VERSION="$version" E2E_DOMAIN=apps.kind.invalid E2E_EXTERNAL=0 \
  E2E_STORAGE_CLASS=standard E2E_SHARED_STORAGE_CLASS=e2e-shared E2E_NODE_SELECTOR= \
  E2E_TIMEOUT="${E2E_TIMEOUT:-40m}" \
  go test -tags e2e -count=1 -timeout "${E2E_GO_TIMEOUT:-100m}" -v ./test/e2e/
