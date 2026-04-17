---
status: Accepted
date: 2026-04-17
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0014 — Add a Flux-managed CronJob that deletes `status.phase=Failed` pods cluster-wide

> Kubernetes' built-in PodGC only fires *above* a threshold (anton: 30; upstream default: 12500), so small counts of tombstone pods linger indefinitely and surface on the cluster-health dashboard as false-positive "failed workloads"; a 15-line CronJob in `kube-system` deletes them on a schedule without introducing a new operator or chart.

## Status

Accepted

## Context

The new `cluster-health-glance` dashboard (ADR 0013) surfaced five `Error`-phase pods on `k8s-1` that had been sitting idle for ~22 hours — one `cilium-operator` and four Longhorn CSI sidecars (`csi-attacher`, `csi-provisioner`, `csi-resizer`, `csi-snapshotter`). All five had `DisruptionTarget: True` with healthy replacements already Running: they were tombstones from a single drain/reboot event on that node, not live failures.

anton already sets `--terminated-pod-gc-threshold=30` on kube-controller-manager via `talos/patches/controller/cluster.yaml:13`, and that flag is live on the running controller (`kube-controller-manager ... --terminated-pod-gc-threshold=30`). But Kubernetes' `PodGC` controller only deletes terminated pods when the cluster-wide count of them *exceeds* the threshold — five is well under thirty, so they stayed. This is a documented and intentional limitation (kubernetes/kubernetes#71421, kubernetes/enhancements#2890): the threshold is a ceiling, not a target. Setting it to `0` disables the GC entirely instead of cleaning to zero; setting it to `1` still leaves one tombstone per disruption class.

The operational consequence is minor — five Pod API objects don't pressure etcd — but the dashboard consequence is not. ADR 0013's whole premise is that `cluster-health-glance` becomes the "is the cluster ok" surface, and a row titled *Unhealthy Workloads* that always shows 5 because of a day-old node reboot trains the operator to ignore the panel. The "Failed" column on that dashboard is meant to surface *current* failures, and PodGC's threshold behavior makes that guarantee impossible to hold with built-in knobs alone.

Research turned up four cleanup paths — native CronJob, lower the GC threshold further, `lwolf/kube-cleanup-operator`, and `kubernetes-sigs/descheduler`. Only the first two are proportionate to a homelab; the operator path is unmaintained since 2020, and the descheduler solves a different problem (re-scheduling live pods, not cleaning tombstones).

## Decision

Add a Flux-managed CronJob in the `kube-system` namespace that runs `kubectl delete pod --field-selector=status.phase=Failed -A` on a 30-minute schedule. The resource set is intentionally minimal:

- One `CronJob` (schedule `*/30 * * * *`, `concurrencyPolicy: Forbid`, `restartPolicy: OnFailure`, `successfulJobsHistoryLimit: 1`, `failedJobsHistoryLimit: 1`, `activeDeadlineSeconds: 120`).
- One dedicated `ServiceAccount` (`pod-gc`) in `kube-system`.
- One `ClusterRole` granting `pods: list, delete` only — no other verbs, no other resources.
- One `ClusterRoleBinding` linking the two.
- Pod spec uses `bitnami/kubectl` (already the anton convention for kubectl-based CronJobs; Renovate tracks the tag), `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `seccompProfile: RuntimeDefault`, all capabilities dropped.

The `terminated-pod-gc-threshold=30` controllerManager flag stays as it is — it remains useful as a ceiling during mass-failure events (e.g., a namespace-wide OOM storm) where the CronJob's 30-minute cadence would be slow, and backing it out costs a rolling Talos machine-config apply.

Scaffolding is handed off to the `add-flux-app` skill after this ADR lands; the 3-file Flux pattern at `kubernetes/apps/kube-system/pod-gc/` is the implementation surface.

## Alternatives considered

- **Do nothing — delete manually when the dashboard shows a corpse** — rejected. ADR 0013 Phase 1 explicitly targets "is the cluster ok" glanceability; a dashboard that requires regular operator intervention to stay green is a dashboard the operator learns to ignore.
- **Lower `terminated-pod-gc-threshold` from 30 to 1 (or to a very low number)** — rejected *as a sole fix*. Even threshold=1 leaves one tombstone per disruption class lingering until the next failure rotates it out, it costs a rolling Talos machine-config apply to change, and it sacrifices the threshold's legitimate role as a ceiling. The CronJob is strictly better for the "steady-state zero tombstones" goal. Noted as a complementary future tweak if threshold=30 ever feels too generous during a storm.
- **`lwolf/kube-cleanup-operator`** — rejected. Unmaintained since 2020, adds a Deployment + custom flags + container image we don't need, and solves a broader problem (completed Jobs + orphaned pods) than anton has. Fails the `cluster-intake` "is this proportionate" gate.
- **`kubernetes-sigs/descheduler`** — rejected. Wrong tool: it evicts *running* pods to improve placement, it does not GC terminated ones. Irrelevant to the problem.
- **Filter the dashboard query to exclude `DisruptionTarget=True` pods instead of deleting them** — rejected as a sole fix. Hides a real "5 failed pods" count behind a query filter; future operators reading raw `kubectl get pods -A` would still see the corpses. Cleaning the underlying state is the correct layer. The dashboard query will remain naive and the state will remain clean.

## Consequences

### Accepted costs

- **One new workload in `kube-system`.** Small surface area: a CronJob that runs for ~1 second every 30 minutes, a ServiceAccount, a ClusterRole with two verbs, a ClusterRoleBinding. Reviewable in one screen.
- **Renovate-PR tax: minimal.** Renovate tracks one container image (`bitnami/kubectl`). Merged with the weekly batch per standard anton convention.
- **RBAC scope is cluster-wide `pods: list, delete`.** This is the minimum workable scope — a namespace-scoped binding would require a Role per namespace and a new Role each time a namespace is added. Mitigation: the `ClusterRole` is named `pod-gc` and references no other resources or verbs, so it is trivially auditable via `kubectl describe clusterrole pod-gc`.
- **Potential for accidental deletion of a pod the operator was inspecting.** `--field-selector=status.phase=Failed` only matches terminated pods, not Running, Pending, or Succeeded — so the blast radius is tombstones only, which is the entire point. Still documented here so the deletion criterion is not silently widened in a future edit.
- **30-minute recovery cadence on the dashboard.** A fresh tombstone can sit on the dashboard for up to 30 minutes before the next GC run. Acceptable; the alternative (1-minute cadence) would spam logs and provide no real benefit for a homelab.

### What this preserves

- **Built-in `terminated-pod-gc-threshold=30` stays in place** as a ceiling against burst failures.
- **No new CRDs, no new operator, no new chart.** The addition is first-party Kubernetes primitives only, which is the homelab-appropriate layer.
- **Anti-completionism discipline (ADR 0001).** The removal graveyard is not re-polluted — a CronJob in `kube-system` with no chart dependency is cheap to remove later if it turns out to be unnecessary.
- **Dashboard integrity (ADR 0013).** The `Unhealthy Workloads` panel means what it says without a query-level workaround.

## Follow-ups

- [ ] **Scaffold the 3-file Flux pattern** at `kubernetes/apps/kube-system/pod-gc/` via `add-flux-app` — `namespace.yaml` is not needed (kube-system already exists), so the layout is `ks.yaml` + `app/kustomization.yaml` + the four resource YAMLs (CronJob, ServiceAccount, ClusterRole, ClusterRoleBinding).
- [ ] **Verify first run** — after Flux reconciles, watch for the first successful Job and confirm `kubectl get pods -A --field-selector=status.phase=Failed` returns empty.
- [ ] **Dashboard re-check** — once the CronJob is live, confirm the `cluster-health-glance` Unhealthy Workloads row reads zero under steady state. No query change required; the naive query is the desired one.
- [ ] **Revisit `terminated-pod-gc-threshold`** — if a future burst-failure incident floods etcd with Pod objects faster than the 30-minute CronJob can drain them, reopen the threshold decision. Not committed today.
