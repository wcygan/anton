# 2026-07-09 cluster security audit

This note preserves the baseline for plan
[`0019-harden-cluster-security-posture.md`](../plans/0019-harden-cluster-security-posture.md).
The raw JSON reports remain temporary because they contain a large live-cluster
inventory; the durable repository record is the normalized summary below.

## Scope and tools

- Kubernetes context: the expected Tailscale operator proxy context (literal
  tailnet name intentionally omitted).
- Kubernetes objects: 794 live objects scanned for configuration and RBAC
  findings with Trivy.
- Workload images: 102 distinct deployed AMD64 image references discovered;
  100 scanned successfully.
- Kubescape: v4.0.9, NSA framework.
- Trivy: v0.71.2 with the current vulnerability database, image scanning on
  AMD64, node collector disabled, and telemetry disabled.
- No scanner workload, namespace, credential, or other live-cluster resource
  was created by the audit.

## Pre-remediation health

- Kubernetes API `/readyz`: all checks passed.
- Nodes: `k8s-1`, `k8s-2`, and `k8s-3` Ready on Kubernetes v1.36.0 and Talos
  v1.13.0.
- Talos core services: Running and healthy on all three nodes.
- etcd: exactly three voting, non-learner members with no reported status
  errors.
- Workloads: no unexpected non-running pods.
- Network isolation: two live NetworkPolicies and no live Cilium policies.
- Pod Security Admission: 9 of 20 namespaces enforced `baseline`; 11 had no
  enforce label. Seven of fourteen committed namespace manifests had no
  enforce label.

## Kubescape baseline

- NSA framework score: **66.87%**.
- Controls: 6 passed, 18 failed, and 2 host/Kubelet controls were not evaluated.
- Resources: 141 of 534 evaluated resources were associated with at least one
  failed control.
- Broadest failed controls included ingress/egress isolation, non-root
  execution, privilege escalation, automatic service-account mapping, and CPU
  or memory limits.

## Trivy baseline

- Image findings: 29 distinct Critical and 397 distinct High vulnerability IDs
  across the successfully scanned image set.
- Package/binary occurrences before deduplication: 286 Critical and 4,919 High.
- A fixed version was reported for 25 of the 29 Critical IDs and 372 of the 397
  High IDs.
- `CVE-2026-31789` was repeated across many Linux images, but its vulnerable
  OpenSSL code path is specific to 32-bit systems and is outside this AMD64
  cluster's applicable scope.
- The largest actionable concentrations were in the `netshoot` host-network
  image, Cilium and its installer, the CNPG PostgreSQL image, ClickStack's OTel
  collector, Harbor Photon images, and Longhorn engine/manager images.

### Coverage gaps

Two deployed images could not be scanned from the audit host:

1. The private Harbor `cs2plant` image was unreachable from the current
   off-LAN path.
2. A digest-pinned private GHCR bakery image rejected anonymous access.

These are coverage gaps, not clean scan results. The final audit must retry
them only with access and credentials already available to the operator; plan
0019 does not authorize creating or rotating registry credentials.

### Candidate-image checks

| Candidate | Critical | High | Baseline comparison |
|---|---:|---:|---|
| Longhorn engine v1.12.0 | 0 | 28 | v1.11.2: 2 / 51 |
| Longhorn manager v1.12.0 | 0 | 25 | v1.11.2: 2 / 35 |
| AWS CLI 2.35.19 | 0 | 0 | 2.17.0: 0 / 65 |
| ClickHouse 26.5 | 0 | 2 | 25.7-alpine: 2 / 17 |
| ntfy 2.25.0 | 0 | 0 | 2.24.0: 0 / 2 |
| `alpine/k8s` 1.36.2 | 4 | 189 | 1.36.1: 5 / 262 |
| Harbor 2.15.1 portal | 9 | 42 | 2.15.0: 13 / 63 |
| Harbor 2.15.1 core | 4 | 56 | 2.15.0: 7 / 80 |
| Harbor 2.15.1 nginx | 9 | 42 | 2.15.0: 13 / 63 |
| netshoot v0.16 | 12 | 152 | v0.15: 24 / 382 |

The netshoot candidate remains too broad and vulnerable to treat as a complete
remediation; the host-network workload should instead use a narrower,
reproducible image or remove the dependency.

## High-confidence configuration findings

1. `talos/patches/controller/cluster.yaml` deletes Talos's default PodSecurity
   admission configuration, leaving unlabeled namespaces at Kubernetes's
   privileged default. Repository history contains no recorded rationale for
   the deletion.
2. Privileged or host-writing agents use broad or mutable images, including a
   runtime package installation in the NVMe collector, tag-only Multus install
   images, and netshoot for the storage VXLAN agent.
3. Several no-API host agents unnecessarily receive service-account tokens.
4. The Talos log receiver accepts unauthenticated plaintext TCP/UDP traffic on
   LAN-facing load-balancer ports without an explicit source policy or storage
   bound.
5. Public application namespaces do not have consistent default-deny network
   isolation. ADR 0025 deferred namespace default-deny, so a successor ADR is
   required before changing that posture.
6. Several ordinary workloads omit a restrictive container security context,
   including ntfy, the ClickHouse retention CronJob, and the Longhorn volume
   labeler.

## Ephemeral evidence

The raw working directory for this audit was
`/tmp/anton-security-scan.51EpNs/`. Useful normalized files were:

- `kubescape-controls.tsv`
- `kubescape-key-failures.tsv`
- `trivy-config-summary.tsv`
- `trivy-image-summary.tsv`
- `trivy-vulnerabilities.tsv`

The repeatable repository command added by plan 0019 replaces reliance on this
ephemeral path.
