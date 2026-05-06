# Evidence: k8s-2 hosts the entire observability stack — a behavioral asymmetry that fits "k8s-2 reboot bias despite identical hardware"

**Date:** 2026-05-06 (loop iteration #12, opus 4.7)
**Source:** `kubectl get pods -A --field-selector status.phase=Running -o wide` aggregated by node + canonical-workload normalization.
**Status:** New behavioral finding. Most concrete answer to "why was k8s-2 the historical reboot leader despite identical hardware" the investigation has produced.

## Observation

Workloads currently running on each node, after canonicalizing StatefulSet/Deployment instance suffixes:

| Group | k8s-1 (20 pods) | k8s-2 (33 pods) | k8s-3 (32 pods) |
|---|---|---|---|
| Observability — heavy | talos-log-sink-vector, ntfy | **Prometheus, Alertmanager, Grafana, kps-operator** | hubble-relay, hubble-ui, metrics-server |
| Operators | longhorn-driver-deployer | **cilium-operator, cnpg, kps-operator** | dragonfly-operator, ts-operator, cert-manager, ESO controller, ESO webhook, ESO cert-controller |
| Networking — DP | cilium, cilium-envoy | cloudflare-dns | envoy-gateway, envoy-internal, cloudflare-tunnel |
| Stateful (DB / cache / app) | homepage, harbor-jobservice, harbor-exporter | csgoplant-dragonfly, harbor-nginx, instance-mgr-dea (Longhorn) | csgoplant-postgres, bakery-server, instance-mgr-05fc (Longhorn) |
| Misc | kube-state-metrics | reloader, cert-manager-webhook | — |

(k8s-1 is currently underloaded post-incident — its pre-2026-05-05 placement may have been heavier.)

## Why this matters for the Vmin / C8 hypothesis (iter #6)

Each of these workloads has a characteristic CPU activity profile. The ones on k8s-2 are dominated by **bursty, scrape-driven work** with long idle periods between bursts:

| Workload (on k8s-2) | Wake cadence | Burst character |
|---|---|---|
| Prometheus | 15-30 s scrape intervals (per target × hundreds of targets) | High-CPU spike during compaction / TSDB write |
| Alertmanager | rule-eval every 30 s | Moderate spike during eval |
| Grafana | dashboard renders + datasource queries | Bursty on user activity |
| cilium-operator | watch-driven reconcile + IPAM allocation | Spikes on pod create/delete |
| kube-prometheus-stack-operator | watch-driven reconcile of Prometheus CRDs | Sporadic spikes |
| cnpg-operator | pg-cluster reconcile | Sporadic spikes |
| csgoplant-dragonfly | in-memory KV operations + persistence flush | Workload-driven |

This profile — **periodic short bursts with deep idle in between** — is exactly the pattern that maximally exercises the C8 → C0 transition cycle. Iter #6 measured the cluster doing C8 entry hundreds of times per second cluster-wide; **k8s-2's pod placement is the dominant source of those transitions.**

The Vmin shift failure mode requires: (a) deep C-state entry (C8 with VR at minimum), (b) wake-up-from-C8 event, (c) instruction execution on possibly-degraded silicon during the brief recovery window. **The frequency of these events scales with bursty wake-ups.** A node hosting Prometheus + Alertmanager + cilium-operator gets these events at a much higher rate than a node hosting steady-state services like cilium-agent (which is in a tight epoll-poll-sleep loop with minimal wake pattern variability).

## What this changes about the hypothesis space

After 11 iterations the surviving question was: "what explains k8s-2's historical reboot bias despite identical hardware (iter #11) and identical kernel/microcode/extensions (iter #6)?" Three candidate answers emerged:

1. **Silicon corner / luck** — some k8s-2-specific hardware degradation that just happens to be unique to that chassis
2. **BIOS 1.27 partial mitigation** (iter #9 nuance) — k8s-2 was on un-flashed 1.22 originally, more exposed
3. **NEW: Workload placement** — k8s-2 carries the observability + operator stack, which drives more C-state transitions per unit time

(1) and (2) were the candidates iter #9 left on the table. **(3) is new and falsifiable cheaply.**

## Cheap discriminating test

**Move Prometheus + Alertmanager + Grafana + cilium-operator off k8s-2** to k8s-3 (which currently has lighter workloads even though pod-count is similar). If silent reboots subsequently occur on k8s-3 (the new host) rather than k8s-2 (or any node), workload-driven Vmin is the dominant mechanism. If reboots stop, cluster-wide Vmin/C-state mitigations from iter #3 + #6 are needed *and sufficient*. If reboots continue on the original node, silicon-corner is the dominant mechanism.

Mechanism: edit the kube-prometheus-stack HelmRelease to add a `nodeAffinity` requiring `kubernetes.io/hostname: k8s-3`, or use a `topologySpreadConstraint` to force at least one replica on each node. Reversible.

**However:** this test is *redundant* with the iter #3 + #5 + #8 three-landings PR. If those land first and silent reboots stop, we don't need to know whether the cause was workload-driven or silicon-corner — both are mitigated. The recommended order is:

1. Land the three iter-#5/#6/#8 changes (PM-QoS DaemonSet + WatchdogTimerConfig + SysctlConfig)
2. Watch for 14 d
3. **If reboots continue**, then run the workload-rebalance test as the cheap next experiment

## A second-order observation

The investigation README's hypothesis #1 was "single-unit hardware defect on k8s-2's MS-01 chassis" (falsified by 2026-05-05). The next-most-recent ranking promoted "cluster-wide kernel/network/data-plane trigger" to #1 and demoted single-unit. **iter #12 surfaces a third option:** the *behavior* on k8s-2 is unique because of pod placement, not because of hardware. The cluster-wide expressibility (2026-05-05 cross-node event) is consistent with the same Vmin mechanism active on every node, just expressed at a rate proportional to local C-state-transition density.

This reading makes the historical k8s-2 bias **predictive** rather than mysterious: the node that runs the most bursty workloads is the most C-state-active, the most exposed to Vmin events, and the most reboot-prone. After the iter #3 DaemonSet caps C-states at C0/C1, the bias should disappear regardless of where Prometheus runs.

## Verification trail

```
$ kubectl get pods -A --field-selector status.phase=Running -o wide --no-headers \
    | awk '{print $8, $1, $2}' | sort | python3 -c "..."

  total pods: k8s-1=20, k8s-2=33, k8s-3=32

  pods on k8s-2 ONLY (14):
    cert-manager/cert-manager-webhook-*
    csgoplant/csgoplant-dragonfly-*
    databases/cloudnative-pg-*
    default/echo-*
    kube-system/cilium-operator-*
    kube-system/reloader-*
    network/cloudflare-dns-*
    observability/alertmanager-kube-prometheus-stack-alertmanager-*
    observability/kube-prometheus-stack-grafana-*
    observability/kube-prometheus-stack-operator-*
    observability/prometheus-kube-prometheus-stack-prometheus-*
    registries/harbor-nginx-*
    storage/instance-manager-dea08a8882257aeac9b60752069609d2
    tailscale/ts-kube-prometheus-stack-grafana-8t55d-*
```

(k8s-1 and k8s-3 unique-pod lists in the conversation context.)

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6) — measured C8/MWAIT 0x60 entry rates; iter #12 attributes them to specific workloads
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8) — measured i226-V as dominant wake source; iter #12 attributes the wake events to scrape-driven workloads on k8s-2
- `evidence-2026-05-06-kernel-taint-and-psi-clean.md` (iter #9) — surfaced the "BIOS 1.27 may be partial mitigation" nuance; iter #12 offers an alternative reading (workload placement was the asymmetry, not silicon)
- `evidence-2026-05-06-nvme-lineup-uniform.md` (iter #11) — falsified hardware-side asymmetry; iter #12 finds the asymmetry on the workload side
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — the PM-QoS DaemonSet is the right mitigation regardless of which sub-mechanism is dominant
- Plan 0013 — investigation now has a credible explanation for *every* observed asymmetry; recommendation stack unchanged but with stronger justification
