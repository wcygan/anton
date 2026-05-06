# Evidence: Cilium BPF program count differential aligns with 2026-05-05 reboot ordering — small supporting datum for workload-driven Vmin reading

**Date:** 2026-05-06 (loop iteration #16, opus 4.7)
**Source:** `kubectl exec` into each node's `cilium-agent` pod, `bpftool prog show | wc -l` and `bpftool map show | wc -l`.
**Status:** Small new datapoint, weakly supportive of iter #12's workload-driven reading. Node conditions are clean.

## Observation

| Node | BPF programs | BPF maps | 2026-05-05 reboot order | iter #12 pod count |
|---|---|---|---|---|
| k8s-1 | **534** | **224** | second to reboot (~19:33Z) | 20 |
| k8s-2 | 643 | 251 | held throughout | 33 |
| **k8s-3** | **689** | **265** | **first to reboot (19:07Z)** | 32 |

**k8s-3 has the most BPF programs and was the first node to silent-reboot.** k8s-1 has the fewest BPF programs and was the second. k8s-2 in the middle held that day.

## What the differential reflects

BPF program count is roughly proportional to **Cilium endpoint count + LB backend count + policy rule count**. Each endpoint gets its own ingress + egress BPF programs; each policy gets compiled in. So this metric is a function of pod density + service density + policy density per node.

Per the iter #12 workload map:
- **k8s-3** hosts the heavy network plane (envoy-gateway, envoy-internal, cloudflare-tunnel, hubble-relay, hubble-ui, tailscale operator) — many service endpoints, many policies
- **k8s-2** hosts the observability stack (Prometheus, Alertmanager, Grafana) plus operators — moderate endpoint count
- **k8s-1** is post-incident underloaded — fewest endpoints

So the BPF differential is **explained by workload placement**, not a fundamental driver asymmetry.

## What it might mean

Two readings:

1. **The BPF count differential is a marker for cluster-wide-reboot susceptibility on 2026-05-05.** k8s-3 (most BPF) reboots first, k8s-1 (least BPF) reboots second, k8s-2 (middle, with the heavy observability stack) gets lucky. Each Cilium endpoint BPF program runs in the kernel-mode BPF VM; every packet through that endpoint executes the program. More programs → more BPF VM activity → more wake events from C-states → more Vmin exposure.

2. **The BPF count differential reflects pod count, which reflects workload density, which drives wake events generically.** The mechanism is the workload placement (iter #12), not the BPF count specifically. BPF count is a proxy for "how busy is this node's networking stack."

(1) and (2) are not really distinguishable — they predict the same observable. But (1) suggests a forward-looking watch metric: alert when a node's BPF program count exceeds a threshold, as a predictor of accumulating idle-wake load.

The historical k8s-2 bias (R0–R8 all on k8s-2) doesn't fit (1) directly — k8s-2 has the middle BPF count today, not the highest. But the historical period had k8s-2 hosting more workloads than now (it was the BIOS-flash investigation target, ran more pods at various points). Without historical BPF-count data, can't quantitatively check.

## What it does NOT prove

- Doesn't establish BPF map operations per second on any node — count is static; activity is dynamic
- Doesn't show BPF JIT or map-creation events in the seconds before the 2026-05-05 reboots
- Doesn't isolate BPF as the wake source vs. other periodic activity (Prometheus scrapes, etcd activity, kubelet probes)
- Could be coincidence given N=2 reboot events on 2026-05-05

## Forward-looking implication

If iter #5/#6/#8 PR doesn't fully prevent silent reboots, **a forward-looking metric to watch is `cilium_bpf_program_count` (if Cilium exposes it, otherwise via a recurring `bpftool prog show | wc -l` collector).** A PrometheusRule that fires when any node's BPF program count grows unusually would give early warning of mounting wake-event load.

This is a minor recommendation, not a critical one. The cluster-wide PM-QoS DaemonSet from iter #3 caps the failure surface regardless of BPF count.

## Node conditions are clean

All three nodes: `Ready=True`, no MemoryPressure, no DiskPressure, no PIDPressure, no NetworkUnavailable. Standard quiet-cluster state. No kubelet-level pressure that would correlate with imminent silent reboot.

## Cross-references

- `evidence-2026-05-06-k8s-2-hosts-observability-stack.md` (iter #12) — workload-driven Vmin reading; iter #16 adds Cilium-BPF-count as a quantitative marker
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8) — i226-V IRQ count; iter #16 BPF-count adds a second per-node activity metric
- `evidence-2026-05-06-c-states-active.md` (iter #6) — C8 entry rate measurement; BPF activity is one of many wake sources for these entries
- Plan 0013 — no plan-level change; minor forward-looking metric suggestion

## Honest assessment

This iter produced a single weakly-suggestive datapoint that's predicted by iter #12's workload-placement reading. It does not change the recommendation stack. The information value is real but small — diminishing returns continue.
