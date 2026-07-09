---
status: In-progress
opened: 2026-07-09
closed: null
affects: security
intent: concrete-need
related-adrs: [0015, 0025, 0027, 0029]
review-by: null
---

# 0019 — Harden cluster security posture

> Remediate Anton's verified image, admission, network-isolation, and host-workload security gaps without sacrificing cluster availability.

## Goal

Reduce the high-confidence findings from the 2026-07-09 agentless security audit through staged GitOps and platform upgrades, leaving every remaining Critical finding either fixed or tied to an explicit upstream/blocker, while preserving Talos, etcd, Flux, Longhorn, and application health throughout the rollout.

## Acceptance criteria

- [ ] All repo-controlled fixable Critical findings are remediated or have a named upstream/blocker and compensating control recorded in this plan; the final Kubescape and Trivy results materially improve on the 2026-07-09 baseline.
- [ ] Pod Security Admission and public-application network isolation are deployed with explicit infrastructure exceptions, and required probes, routes, DNS, storage, and backend traffic are verified.
- [ ] Approved Talos, Kubernetes, storage, registry, and workload security updates are live, with mandatory health gates recorded after every high-risk checkpoint.
- [ ] A repeatable, agentless security-audit command is committed without adding an in-cluster scanner or new credentials.
- [ ] Final health verification shows 3/3 nodes Ready, three healthy etcd members, healthy Talos core services, Flux sources/Kustomizations/HelmReleases Ready, Longhorn volumes healthy, and no unexpected non-running pods.

## Tasks

### Phase 1: Baseline and decisions

- [x] Preserve the 2026-07-09 scan summaries and record the exact coverage gaps.
- [ ] Audit the relevant Renovate PRs, release notes, supersessions, and dependency order.
- [x] Inspect the history behind the Talos PodSecurity deletion and the accepted NetworkPolicy posture.
- [x] Author a successor ADR before adopting namespace default-deny behavior that changes ADR 0025.

### Phase 2: Low-blast-radius remediation

- [ ] Merge and verify security-relevant patch/minor image updates one at a time where their preflight gates pass.
- [x] Disable unnecessary service-account token automounting for no-API host agents.
- [ ] Replace or narrow mutable, broad host-network tooling and pin privileged/host-writing images where feasible.
- [x] Restrict Talos log-sink ingestion to expected sources and bounded resource use without breaking node logging.

### Phase 3: Admission and network isolation

- [x] Restore a deliberate PodSecurity admission configuration with explicit namespace labels or exemptions for privileged infrastructure.
- [ ] Add minimal default-deny and required allow policies to the first public application namespaces.
- [ ] Validate every selected workload's probes and live traffic paths before expanding policy coverage.

### Phase 4: Storage and platform upgrades

- [ ] Preflight and deploy the Longhorn upgrade serially, then verify volumes, replicas, CSI, and application mounts.
- [ ] Take and verify an etcd snapshot, then roll Talos one node at a time with node/etcd/Flux/Longhorn gates between nodes.
- [ ] Upgrade Kubernetes only after Talos is fully healthy and the deprecation/probe audits are clean.

### Phase 5: Repeatable audit and close-out

- [ ] Add a repo-native agentless Kubescape/Trivy audit command and concise runbook.
- [ ] Rerun configuration, RBAC, and AMD64 image scans with private-registry coverage where credentials/access already exist.
- [ ] Record final health and scan evidence, resolve or document all acceptance-criterion gaps, and close the plan.

## Log

- 2026-07-09: Plan opened after the live audit found Kubescape NSA/CISA compliance at 66.87%, 29 distinct Critical and 397 High image matches across 100 of 102 AMD64 images, Talos PodSecurity defaults deleted, and only two live NetworkPolicies.
- 2026-07-09: The rollout excludes credential rotation, destructive recovery, namespace/data deletion, Secure Boot or disk-encryption migration, and an in-cluster security operator; any such need is a separate operator-approved initiative.
- 2026-07-09: Preserved the sanitized baseline in `context/notes/2026-07-09-cluster-security-audit.md`, including the two private-image coverage gaps and candidate-image comparisons.
- 2026-07-09: Repository history traced the PodSecurity deletion to the initial Talos configuration import and found no documented rationale. ADR 0025 intentionally deferred namespace default-deny, so the changed threat posture requires a successor ADR.
- 2026-07-09: Disabled projected API tokens for idle-mitigations, NVMe collection, smartctl-exporter, storage-vxlan, and the Talos log receiver. Every rollout completed; live pods have no token volumes and their device, metric, log, and storage paths remain healthy.
- 2026-07-09: Hardened storage-vxlan with a digest pin, no-new-privileges, read-only root, RuntimeDefault seccomp, and an overlay readiness probe. All nodes reached all three Longhorn instance-manager iSCSI endpoints and all attached volumes remained healthy.
- 2026-07-09: Accepted ADR 0029, superseding ADR 0025's default-deny deferral and requiring explicit probe validation for targeted public-workload isolation.
- 2026-07-09: Upgraded Harbor to 2.15.1, the Longhorn labeler to `alpine/k8s` 1.36.2, the Harbor bucket job to AWS CLI 2.35.20, ntfy to 2.26.0, and the ClickHouse retention client to 26.5. Each change was reconciled and exercised against its live health endpoint or real CronJob path before advancing.
- 2026-07-09: Pinned Multus, install-cni, Whereabouts, storage-vxlan, smartctl-exporter, idle-mitigations, the Talos log helper, and the homepage log agent by digest. Fresh Multus/Whereabouts pods received a storage-network address after each serial CNI rollout; attached Longhorn volumes remained healthy.
- 2026-07-09: Restricted the Talos log receiver with node-source LoadBalancer ranges plus a pod-level ingress policy. An ordinary pod is denied while fresh service logs continue from all three nodes; historical TCP and UDP kernel streams use only allowlisted node addresses.
- 2026-07-09: Took a 232 MiB etcd snapshot at `$HOME/anton-backup-20260709/etcd-pre-psa-20260709T211149Z.db` (SHA-256 `b1e06487ef36f4fd15da64b6d04d56e928f85891eab4403aba06a7ee5374cc13`) and restored Talos's default PodSecurity config serially on all three nodes without reboot. Every node reports baseline enforcement with restricted audit/warn; a privileged dry-run pod in unlabeled `kube-public` is rejected.

## References

- Security baseline: `context/notes/2026-07-09-cluster-security-audit.md`
- Raw security artifacts: `/tmp/anton-security-scan.51EpNs/` (ephemeral)
- PodSecurity source: `talos/patches/controller/cluster.yaml`
- Version pins: `talos/talenv.yaml`
- NetworkPolicy decision: `context/adrs/0025-keep-chart-networkpolicies-fix-probes-upstream.md`
- Harbor scanning decision: `context/adrs/0015-adopt-harbor-for-image-registry.md`
- Platform dependency rule: `context/adrs/0027-platform-dependson-rule.md`
- Renovate dashboard: GitHub issue #10
- Security-relevant update PRs: #292, #293, #309, #319, #339, #341, #343, #345, #349
- Cluster health: `kubectl get nodes -o wide`, `flux get ks -A`, `flux get hr -A`, `talosctl service`, `talosctl etcd members`
