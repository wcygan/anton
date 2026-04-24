---
name: Drain on anton stalls on PDB-gated singletons when Multus OOMs on the destination node
description: Cordon+drain of one node triggers pod-creation burst on survivors that OOMs Multus; PDB-protected pods (Dragonfly maxUnavailable=1) block drain while replacements stay ContainerCreating
type: project
---

Drain of a single node during Harbor+SeaweedFS+Longhorn workload mix reliably triggers a Multus OOM cascade on the destination node, which in turn blocks PDB-gated evictions.

**Why:** Observed 2026-04-23 (plan 0006 controlled-reboot acceptance test on k8s-3). Cordon + drain of k8s-3 pushed ~6 Harbor replicas + seaweedfs-volume-1 + others to k8s-1. k8s-1's Multus pod OOMKilled 4 times (despite the 50→256Mi bump from 2026-04-21), causing every new pod on k8s-1 to get `FailedCreatePodSandBox: CNI request ... EOF`. `harbor-redis-2` replacement stayed ContainerCreating, keeping Dragonfly PDB at `currentHealthy=2/3 disruptionsAllowed=0`, which blocked `harbor-redis-1` eviction for the full 5-min drain timeout. Drain exited non-zero but workloads were effectively evacuated anyway — the reboot cleared the last pod.

**How to apply:**
- Do not rely on `kubectl drain` to fully complete on this cluster during reboots. Expect PDB-related eviction errors on Dragonfly/Harbor singletons and plan for the reboot itself to finish the eviction.
- Before drain, verify `kubectl -n network get pod -l app=multus -o wide` shows no recent restarts — if Multus is already unstable, fix that first or the drain will cascade.
- A drain-timeout-exit does NOT mean the reboot should be aborted; inspect residual pods with `kubectl get pods --field-selector=spec.nodeName=<node>` and if only DaemonSets + PDB-protected singletons remain, the reboot will clean them up safely.
- Probes during drain: use `kubectl exec` on a pre-existing Running pod on the *destination* node (one that's already past CNI admission) for in-cluster health checks. Throwaway `kubectl run` probes spawned during the drain will get caught in the same Multus OOM and time out, giving a false-negative reading on cluster health.
- The 256Mi Multus limit (set 2026-04-21) is sufficient for steady state but can still OOM under drain-induced pod-creation burst. Consider bumping further (512Mi) if reboots become routine, or staging drains in smaller waves.
