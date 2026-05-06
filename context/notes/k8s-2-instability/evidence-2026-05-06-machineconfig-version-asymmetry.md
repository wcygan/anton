# Evidence: k8s-2's machineconfig is at version 3 while k8s-1 and k8s-3 are at version 1

**Date:** 2026-05-06 (loop iteration #13, opus 4.7)
**Source:** `talosctl get machineconfigs` per node.
**Status:** Net-new asymmetry. Not a smoking gun. Adds a hidden dimension to "k8s-2 is different" — repeated apply history.

## Observation

```
$ talosctl --endpoints k8s-1 -n k8s-1 get machineconfigs
NODE    NAMESPACE   TYPE            ID         VERSION
k8s-1   config      MachineConfig   v1alpha1   1

$ talosctl --endpoints k8s-2 -n k8s-2 get machineconfigs
NODE    NAMESPACE   TYPE            ID           VERSION
k8s-2   config      MachineConfig   persistent   2
k8s-2   config      MachineConfig   v1alpha1     3

$ talosctl --endpoints k8s-3 -n k8s-3 get machineconfigs
NODE    NAMESPACE   TYPE            ID         VERSION
k8s-3   config      MachineConfig   v1alpha1   1
```

**k8s-2 has machineconfig at v1alpha1 version 3** (and a separate `persistent` resource at version 2). **k8s-1 and k8s-3 are both at v1alpha1 version 1.** Talos increments the version on each successful `apply-config`. So k8s-2 has had **3 successful config applies** since boot, while k8s-1 and k8s-3 have had 1 each.

## What this likely reflects

This is consistent with what the investigation history shows: k8s-2 has been the target of repeated config interventions across plan 0007/0009/0010:

- Plan 0007 Phase 3: Vector kmsg sink added (KmsgLogConfig patches)
- Plan 0009 ADR 0021: cilium-agent memory limit raised (multiple times)
- Plan 0010 Stage A: kubelet/CNI hardening patches
- Plan 0009 ADR 0022: cleanState retraction
- 2026-05-04 BIOS-flash restart cycle

Each `talosctl apply-config` to a single node bumps that node's local version. If most apply-config invocations during the investigation targeted k8s-2 specifically (because k8s-2 was the historical reboot leader and the focus of the diagnostic rollouts), this asymmetry naturally accumulates.

**It does not necessarily indicate config drift.** Talos's apply-config path checks the resulting config matches the supplied YAML; it doesn't accumulate stale state on each apply. Two applies of the same YAML produce the same final state.

But it does indicate **k8s-2 has been operationally treated differently** — not just receiving more apply events, but presumably being the target of *more diverse* apply events with different content. If any of those applies happened during a window where the cluster was in an unusual state (mid-Vector-sink-rollout, mid-cilium-restart), the apply path may have left subtle artifacts that don't appear in a fresh apply on k8s-1 / k8s-3.

## What's worth checking but isn't done in this iter

A clean way to verify "no actual drift" would be:

```
$ talosctl --endpoints k8s-1 -n k8s-1 get machineconfig v1alpha1 -o yaml > k8s-1-config.yaml
$ talosctl --endpoints k8s-2 -n k8s-2 get machineconfig v1alpha1 -o yaml > k8s-2-config.yaml
$ talosctl --endpoints k8s-3 -n k8s-3 get machineconfig v1alpha1 -o yaml > k8s-3-config.yaml
$ diff k8s-{1,2}-config.yaml | head -50
$ diff k8s-{2,3}-config.yaml | head -50
```

Three-way diff. If the diff is empty (modulo node-name fields), version-3 vs version-1 is purely apply-history bookkeeping with no functional consequence. If the diff is non-empty, that's a hidden config asymmetry that may be material.

Out of scope for this iter (just flagging). Worth running before any cluster-wide config patch (iter #5 SysctlConfig + iter #5 WatchdogTimerConfig) lands, so the patch lands cleanly on all three nodes from the same starting point.

## What this confirms (or fails to)

Several things checked in iter #13 that produced confirmations of known state, no new findings:

| Probe | Result |
|---|---|
| Cert expirations | `talosctl get certs` not a registered resource on this Talos version. Cert-rotation correlation can't be checked via this path. |
| etcd raft term | 32 (same as during 2026-05-05 incident). No leader-election churn since. Stable. |
| etcd db size | 122 MB / 44 MB in use (35.8%) — normal fragmentation, no compaction emergency |
| chrony / NTP sync | All three nodes within 100ms of NTP server. No clock drift. |
| BIOS sub-version | k8s-1 = 1.26, k8s-2 = 1.27, k8s-3 = 1.27 (already known) |
| Board version | All `AHWSA v1.0`, all `Venus Series` (Minisforum MS-01). Confirmed identical board revision. |

So this iter's net contribution is **one real (small) asymmetry** plus **several confirmations of known state**.

## What this does not change

The recommendation stack from iter #5 + #6 + #8 stands. The machineconfig version asymmetry doesn't affect the runtime behavior unless an actual config diff is found. Even if a diff exists, it's likely correctable as part of landing the iter #5 SysctlConfig + WatchdogTimerConfig patches — those patches force a re-apply across all nodes, which would also flatten any accidental drift.

## Cross-references

- `evidence-2026-05-06-k8s-2-hosts-observability-stack.md` (iter #12) — the dominant "k8s-2 is different" finding (workload-side asymmetry). Iter #13's machineconfig version asymmetry is the second-strongest "k8s-2 is different" datapoint, but it's procedural (apply history) not behavioral (workload).
- Plan 0007 / 0009 / 0010 — the source of the multiple applies that produced the version delta
- Plan 0013 acceptance criteria — landing the iter #5 SysctlConfig will incidentally flatten the version asymmetry by re-applying uniformly
