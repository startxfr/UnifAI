# RAG git sources: OpenShift 4.22, RHACM and RHOAI (R-530)

Study of 2026-11-07, run against the real repositories with the git connector (not yet through a cluster). A `type: git`
UnifaiRAGSource reads a public GitHub repository at a ref from its archive, keeps the AsciiDoc/Markdown files under
`paths`, resolves `include::` (following the repository's symlinks), applies `spec.git.attributes` /
`attributeFiles`, evaluates `ifdef`/`ifndef` against them, and stores one document per selected file.

| Product | Repository and ref | Documents | Text | Notes |
|---|---|---|---|---|
| OpenShift Container Platform 4.22 | `openshift/openshift-docs`, `enterprise-4.22` | 1859 (OCP dirs of the topic map, without `rest_api`) | 32 MB | one repo serves OCP, OKD, ROSA, OSD, MicroShift: the distro attributes and the `paths` choose OCP. Apache-2.0. Archive about 150 MB, read in 40 s, 150 MB of memory |
| Red Hat Advanced Cluster Management | `stolostron/rhacm-docs`, `2.17_prod` (latest production branch; `5.0_stage` is the next) | 1056 | 4.4 MB | common attributes in `modules/common-attributes.adoc`. The repository has **no LICENSE file**: ask Red Hat before publishing the content to users |
| Red Hat OpenShift AI | `opendatahub-io/opendatahub-documentation`, `main` (last commit 2026-03-24, after `v3.3` of 2026-03-11; the repository is archived and no newer public RHOAI source exists) | 25 books | 1.9 MB | this is the **upstream Open Data Hub** documentation, archived since 2026-03; the RHOAI wording is produced by the `self-managed` attribute. The official RHOAI source is not public: expect differences with docs.redhat.com. Apache-2.0 |

```yaml
apiVersion: unifai.startx.fr/v1alpha1
kind: UnifaiRAGSource
metadata: {name: ocp-4-22-docs}
spec:
  type: git
  visibility: public            # needs the owner in spec.rag.sharedPublishers
  classification: C1
  tags: [knowledge.tech, product:openshift]
  git:
    url: https://github.com/openshift/openshift-docs
    ref: enterprise-4.22
    maxFiles: 3000
    metadata: {product: OpenShift Container Platform, version: "4.22", language: en}
    attributeFiles: [_attributes/common-attributes.adoc]
    attributes:
      openshift-enterprise: ""
      product-title: OpenShift Container Platform
      product-version: "4.22"
    # the directories of _topic_maps/_topic_map.yml whose Distros contain openshift-enterprise
    paths: [welcome, release_notes, tutorials, architecture, disconnected, installing, post_installation_configuration,
            updating, support, web_console, cli_reference, security, authentication, networking, storage, registry,
            operators, extensions, cicd, openshift_images, applications, serverless, machine_configuration,
            machine_management, etcd, hosted_control_planes, vcp, nodes, windows_containers, sandboxed_containers,
            observability, scalability_and_performance, ai_workloads, edge_computing, hardware_enablement,
            hardware_accelerators, backup_and_restore, migrating_from_ocp_3_to_4, lightspeed, service_mesh, virt,
            ai_applications]
---
apiVersion: unifai.startx.fr/v1alpha1
kind: UnifaiRAGSource
metadata: {name: rhacm-2-17-docs}
spec:
  type: git
  visibility: public
  git:
    url: https://github.com/stolostron/rhacm-docs
    ref: 2.17_prod
    metadata: {product: Red Hat Advanced Cluster Management, version: "2.17", language: en}
    attributeFiles: [modules/common-attributes.adoc]
    paths: [about, add-ons, applications, business_continuity, clusters, console, get_started, gitops, global_hub,
            governance, health_metrics, mce_acm_integration, mce_release_notes, mce_troubleshooting, mcp, networking,
            observability, release_notes, search, secure_clusters, troubleshooting, virtualization]
---
apiVersion: unifai.startx.fr/v1alpha1
kind: UnifaiRAGSource
metadata: {name: rhoai-odh-3-3-docs}
spec:
  type: git
  visibility: public
  git:
    url: https://github.com/opendatahub-io/opendatahub-documentation
    ref: main
    metadata: {product: Red Hat OpenShift AI Self-Managed (from the Open Data Hub docs), version: "3.x (main, March 2026)", language: en}
    attributes: {upstream!: "", self-managed: ""}
    include: ["*.adoc"]
    exclude: ["modules/*", "assemblies/*", "examples/*", "scripts/*", "_artifacts/*", "README.adoc"]
```

Limits: macros other than includes, attributes, headings, links and images are left as the author wrote them; `ifeval`
blocks are kept; code-sample placeholders such as `{end}` or `{namespace-name}` stay literal; the first sync of
openshift-docs embeds about 32 MB of text (an hour or more on the RAG embedder), the later ones only what changed.
Check the licence of each repository before exposing its content (RHACM: none declared).
