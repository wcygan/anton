---
status: Superseded-by 0021
date: 2026-04-21
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: 0021
retrospective: false
---

# 0020 — Size cilium-agent memory limit for cgroup WSS, not process RSS

> Set `cilium-agent.resources.limits.memory` to `2560Mi` — sized against the process's **cgroup working set** (RSS + active page cache), not its RSS alone. The chart-default 1536Mi was sized with RSS-based reasoning and induced a self-perpetuating OOMKill feedback loop on k8s-2 (plan 0007).

## Status

Accepted

## Context

On 2026-04-20 k8s-2 had been rebooting ~every 3-4 hours for roughly a week (context/notes/k8s-2-instability/ captures the pre-investigation state). Plan 0007 was opened to localize the cause within the operator's two-week remote-only window.

The smoking gun was `kubectl get pod cilium-7qnnq -o json` on k8s-2 at 2026-04-21 showing `.status.containerStatuses[cilium-agent].lastState.terminated = {exitCode: 137, reason: Error, finishedAt: 2026-04-20T22:45:56Z}`. Exit code 137 is `SIGKILL` from the kernel OOM-killer. `restartCount=3` on a ~2-hour-old pod.

Quantitative breakdown at 2026-04-21 pre-rollout (cilium-agent container only, via Prometheus):

| Metric | k8s-1 | k8s-2 | k8s-3 |
|---|---|---|---|
| `container_memory_rss` | 166 MiB | **148 MiB** | 164 MiB |
| `container_memory_cache` | 3 MiB | **166 MiB** (55×) | 3 MiB |
| `container_memory_working_set_bytes` | 190 MiB | **739 MiB** (3.9×) | 189 MiB |

k8s-2's RSS was *lower* than peers. Endpoint counts and BPF map entry counts were also lower (3 endpoints vs 35-36; policy maps 2 vs 40+), because k8s-2 was cordoned and had minimal workload. Go heap was comparable across all three nodes. **The only anomalous metric was `container_memory_cache` — page cache inside the cilium-agent cgroup.**

The chart-default limit `1536Mi` had been sized as "~2x current usage" where "current usage" implicitly meant RSS (the Helm-chart comment says `cilium agents ~750Mi per node`). That reasoning is wrong for workloads that accumulate active page cache inside their own cgroup. Kubernetes and the kernel account cgroup memory as **WSS = RSS + active cache**. The cgroup OOM-killer triggers on WSS, not RSS.

On k8s-2, each cilium-agent restart re-mapped the BPF ELFs from `/var/lib/cilium/bpf/`, re-read state files from `/var/run/cilium/`, and repopulated the cgroup's page cache. Under normal operation that cache stays inactive and is reclaimable. But on a node under stress — ghost pods, stuck `ContainerCreating` events, CNI retries — the cache stays active and counts fully against WSS. WSS drifted from ~600 MiB at startup toward the 1536Mi ceiling over ~4 hours. When it crossed, the cgroup OOM-killer SIGKILL'd cilium-agent. kubelet restarted it. The restart regenerated the cache. Repeat. Plan 0007's hypothesis #4 section captures the full mechanism; `context/notes/k8s-2-instability/evidence-2026-04-21-cilium-memory-rca.md` captures the quantitative investigation.

The intervention at 2026-04-21 02:39Z raised the limit to 2560Mi. Over 21+ hours of 10-minute-interval observation (100 ticks, no interruptions), k8s-2 uptime climbed cleanly past 5× the pre-intervention reboot cadence, cilium-agent `restartCount` stayed at 0, cgroup cache re-normalized to 2-3 MiB (peer baseline), and the 6 stuck `ContainerCreating` pods self-healed once containerd's sandbox-name pressure cleared. See plan 0007 Log.

## Decision

Set `cilium-agent.resources.limits.memory: 2560Mi` in `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`, replacing the chart-default `1536Mi`. Sizing rationale: the 48h pre-rollout Prometheus window captured a pod-total WSS peak of 1775 MiB on k8s-2. 2560Mi is ~1.5× that peak, rounded to a clean 128-MiB boundary (2048 + 512). On peer nodes (k8s-1, k8s-3) cilium-agent steady-state WSS is 190 MiB, so the new ceiling is nowhere near tight for them — this is not a "raise it until it stops crashing" — it is sized against observed worst-case plus headroom.

The limit stays; it does not get rolled back when plan 0007 Phase 5 teardown runs. Panic sysctls + this limit are the two permanent outputs of plan 0007; everything else (Vector scaffold, etc.) reverts.

The companion change is a `PrometheusRule` alert at 75% of this limit (1920 MiB) for any cilium-agent pod, to proactively catch the same class of issue on any node before the OOM-killer does. That belongs to a separate follow-up commit under `kubernetes/apps/observability/` (see Follow-ups).

## Alternatives considered

- **Keep the chart default (1536Mi)** — rejected. This is what caused the outage. The restart cycle is self-perpetuating, so the "original trigger" of the first OOM on k8s-2 is moot — any node under sufficient perturbation can enter the cycle at this limit.
- **Remove the memory limit entirely (unlimited)** — rejected. A true cilium-agent memory leak would then quietly consume whole-node RAM and cascade into node-level OOM or other pods getting evicted. The limit is still a useful containment; it just needs to be sized against the right metric.
- **Smaller bump (2Gi = 2048Mi)** — rejected. 2Gi is only ~1.15× the observed peak. The 48h window had one TSDB-observable peak plus a longer Prometheus-zombie gap that missed most of the pre-intervention history. Giving only 15% headroom over the sole observed peak is tight. 2560Mi adds genuine margin (~44% over peak) at trivial cost — peers still sit at ~7% of the new ceiling.
- **Bigger bump (4Gi+)** — rejected. 2560Mi is already generous; larger values make future regressions harder to detect (a real leak would have more room to hide).
- **Tune cilium-agent to generate less page cache (e.g., `endpointGCInterval` changes)** — rejected as pre-optimization. We have no evidence that cache generation itself is pathological; only that the limit was too tight for observed cache behaviour. The simpler, more conservative fix is to size the limit correctly.
- **Move cilium-agent to a separate cgroup / memory-accounting mode** — rejected as over-engineering for a single-node observation.

## Consequences

### Accepted costs

- +1024 MiB headroom reserved per node for cilium-agent, total 3072 MiB cluster-wide. On MS-01 nodes with 96 GiB RAM each (see `context/hardware.md`), this is ~0.033% per node. Free.
- A chart upgrade could reintroduce the `1536Mi` default if someone drops our override. Two guards: (1) this ADR; (2) the follow-up `PrometheusRule` at 1920 MiB would alert within hours of a regression.
- Renovate-PR tax: none. We already override `resources` in `helmrelease.yaml`, so chart bumps merge clean.

### Restore-runbook obligation

None — this is a configuration decision, not stateful infrastructure.

### Lessons

- **Memory-limit sizing must consider WSS, not just RSS.** The default `resources.limits.memory: <2x process RSS>` heuristic is wrong for any workload that holds active page cache (CNI agents, logshippers, anything that memory-maps files or reads them repeatedly). The heuristic should be `~1.5x observed pod-level container_memory_working_set_bytes peak`, measured under realistic churn, not idle.
- **Restart loops have their own memory signature.** Page cache in a restart-looping pod never ages out to inactive; it stays hot and counts against WSS. Any workload with non-trivial restart behaviour is more prone to cgroup OOM than steady-state workloads at the same WSS.
- **dmesg "N processes OOM-killed in M milliseconds" biases toward node-level pressure** when the real answer is often cgroup-level. Six cilium-cni helpers dying in 1ms (from plan 0007 Log 2026-04-20#multi-agent-dmesg) was shared-cgroup OOM, not shared-node OOM. The distinction matters because the fix is at the cgroup, not the node.
- **Self-monitoring is a conflict of interest.** Prometheus being on the node under investigation cost us 26h of TSDB about the very phenomenon we were investigating. A second tier of monitoring that runs off-cluster (or at least off-the-node-in-question) would have materially shortened this investigation.

## Follow-ups

- [ ] Author `PrometheusRule` alert on `container_memory_working_set_bytes{container="cilium-agent"} > 1920Mi` (75% of the new limit), fires after 15m, severity `warning`. Placement: `kubernetes/apps/observability/kube-prometheus-stack/app/rules/cilium-memory.yaml` or similar — separate commit, use the `observability-integrate` skill.
- [ ] Close plan 0007 Phase 4 with verdict: hypothesis #4 confirmed; durable fix = this limit.
- [ ] Plan 0007 Phase 5 teardown: remove Vector log-sink scaffold, revert any machine-logging patches. Panic sysctls + this limit stay.
- [ ] `context/notes/k8s-2-instability/README.md`: mark investigation as resolved, promote hypothesis #4 from "trending confirmed" to "confirmed".
