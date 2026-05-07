# Runbook: Multus NetworkAttachmentDefinition not attached

**Triggered by:** `PodNADAttachFailed` (critical), `LonghornVolumeStuckAttaching`
(critical), `LonghornVolumeFaulted` (critical) — when a single root cause is
the symptom across all three.

**Driving incident:** [2026-05-06/07 harbor-postgres quorum incident](../../../context/plans/0016-harden-flux-cold-start-ordering.md). Rolling Talos reboot left
Longhorn instance-manager pods on k8s-1 and k8s-3 `1/1 Running` with their
`k8s.v1.cni.cncf.io/networks: longhorn-storage` annotation requested but
Multus' CNI-add silently failed to attach `lhnet1@vxlan-storage`. Every
cross-node Longhorn replica attach to those nodes timed out for ~7h before
the downstream `HarborPostgresQuorumAtRisk` alert finally surfaced it.

## Symptoms

Any of these on their own:

- `PodNADAttachFailed` fires — a pod has annotation
  `k8s.v1.cni.cncf.io/networks` requesting a NAD but no
  `k8s.v1.cni.cncf.io/network-status` reply for >5m.
- `LonghornVolumeStuckAttaching` fires — a volume is `state=attaching`
  for >10m.
- An instance-manager pod's interface listing has only `lo` + `eth0`
  (no `lhnet1@if13`):
  ```sh
  kubectl -n storage exec instance-manager-<id> -- ip -4 -br addr show
  ```

## Diagnosis (one minute)

```sh
# 1. Identify the broken IM pod (look for one missing lhnet1):
for pod in $(kubectl -n storage get pods -l longhorn.io/component=instance-manager -o name); do
  printf "%s\n" "$pod"
  kubectl -n storage exec "$pod" -- ip -4 -br addr show 2>&1 | grep -E '^(lhnet1|eth0)' || true
  echo
done
```

A healthy IM has both `eth0@ifN` and `lhnet1@if13`. A broken one has only
`eth0@ifN`.

```sh
# 2. Confirm the storage-vxlan host-shim is up on the affected node:
kubectl -n network exec storage-vxlan-<id-on-node> -- \
  ip -4 -br addr show lhnet1-host
# expect: lhnet1-host@vxlan-storage UP 10.100.1.X/24
```

If the host-shim is also missing, it's a different (storage-vxlan
DaemonSet) failure — see plan 0004 (now closed) for the load-bearing
`lhnet1-host` wiring rationale.

## Fix (30 seconds)

```sh
# 3. Delete the broken IM pod. Longhorn's controller will recreate it;
# Multus typically attaches lhnet1 cleanly on the second attempt.
kubectl -n storage delete pod instance-manager-<id>
```

The new IM pod is recreated within ~5s. Verify with the diagnosis loop
above — `lhnet1@if13` should now be present.

Within ~30s of the new IM coming up:
- `LonghornVolumeStuckAttaching` clears as the engine completes attach.
- `PodNADAttachFailed` clears as Multus writes back the `network-status`
  annotation.
- Longhorn rebuilds any missing replicas onto the recovered node.

## Why this happens

Multus' CNI-add path has a non-obvious failure mode: the daemon can return
`success` to kubelet without actually attaching the secondary interface,
when an upstream condition (e.g., the `vxlan-storage` parent device not yet
existing on the host, or a Whereabouts IPAM transient) causes the
attachment macvlan-bridge call to silently no-op.

The pod then runs as `1/1 Running` indistinguishable from a healthy pod
in every Flux/k8s/Longhorn surface. Only the missing interface inside the
pod tells the truth.

## Prevention

Three layers of detection are now in place — see plan 0016 Phase 3:

1. **`PodNADAttachFailed`** (`kubernetes/apps/network/multus/app/prometheusrule.yaml`)
   pages within 5m of the failure via the `kube_pod_annotations`
   set-difference query.
2. **`LonghornVolumeStuckAttaching`** + **`LonghornVolumeFaulted`** + **`LonghornVolumeDegraded`**
   (`kubernetes/apps/storage/longhorn/app/prometheusrule.yaml`) page on the
   downstream Longhorn symptom regardless of root cause.
3. **`MultusServerRequestErrors`** + **`MultusDaemonRestarting`** alert on
   daemon-level instability.

Self-healing automation (option (c) from the plan 0016 Phase 3 discussion
— a controller that auto-deletes IM pods with NAD-attach failures) is
intentionally not built. Expected occurrence rate is too low to justify
the chart-fork overhead; one-shot operator deletion via this runbook is
fast enough.

## Related

- Plan 0016 — `context/plans/0016-harden-flux-cold-start-ordering.md`
- ADR 0017 — Multus CNI for Longhorn storage network
- ADR 0018 — install-cni init container
- `kubernetes/apps/network/CLAUDE.md` — storage-vxlan host-shim
- `kubernetes/apps/storage/CLAUDE.md` — Longhorn iSCSI / lhnet1 wiring
