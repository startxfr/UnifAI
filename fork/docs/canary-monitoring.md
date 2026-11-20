# Canary operator monitoring (`CANARY_MONITORING`)

The procedure is in [releasing](releasing.md) (cutting a release, phase 1); this page adds the details of what is deployed.

The canary operator is scraped by the user-workload Prometheus: a ServiceMonitor, a metrics Service and a scraper
ServiceAccount with a static token Secret (the canary has no CSV, so OLM provides no ServiceAccount). The manifests are in
`fork/unifai-operator/config/canary-monitoring/` (`kustomization.yaml`, `metrics_args_patch.yaml`, `monitoring.yaml`).
Metrics appear in the namespace `unifai-operator-canary`, e.g. `controller_runtime_reconcile_total`.

| Command (in `fork/unifai-operator`) | Effect |
|---|---|
| `make canary-deploy` | applies the monitoring (`CANARY_MONITORING=on`, the default); `off` leaves it out |
| `make canary-monitoring CANARY_MONITORING=on\|off` | switches it on a running canary; `off` removes the ServiceMonitor, Service, Secret, ServiceAccount and binding (label `unifai.startx.fr/canary-monitoring=true`) |
| `make canary-delete` | also removes the cluster-scoped binding |

On a cluster without the ServiceMonitor CRD the monitoring is skipped with a notice.

Why: on 2026-11-19 zuno-demo-assist saw no `controller_runtime_reconcile_total` series on the canary. Commit `22a658306`
touches the operator Makefile, a build path, so it rebuilds the operator image without behaviour change.
