# Evidence: k8s-2 storage-mesh i40e link flap **41 seconds before** k8s-3's silent reboot

**Date:** 2026-05-06 (loop iteration #2, opus 4.7)
**Source:** Live `talosctl --endpoints k8s-2 -n k8s-2 dmesg`, kept-data window covers 2026-05-05T18:31Z onward (k8s-2 is on the same boot since 2026-05-04T01:47Z, boot ID `28688229-2d15-4216-b028-8b558a5530fe` per `kubectl get node k8s-2 -o jsonpath='{.status.nodeInfo.bootID}'`)
**Status:** Net-new datapoint — does not appear in plan 0009, plan 0013, the 2026-05-05 incident, postmortem, or evidence note. Surfacing as a precursor signal worth verifying against prior events.

## Observation

Reconstructed from k8s-2's kept dmesg ring buffer (k8s-2 held throughout the 2026-05-05 incident, so its ring buffer covers the full build-up to k8s-3's verified silent reboot at 19:07:13Z):

| Time UTC | Event on k8s-2 (held node) |
|---|---|
| 19:06:32.358Z | `i40e 0000:02:00.1 enp2s0f1np1: NIC Link is Down` |
| 19:06:32.360Z | `i40e 0000:02:00.0 enp2s0f0np0: NIC Link is Down` |
| 19:06:38.719Z | `i40e 0000:02:00.1 enp2s0f1np1: NIC Link is Up, 10 Gbps Full Duplex` |
| 19:06:38.721Z | `i40e 0000:02:00.1 enp2s0f1np1: NIC Link is Down` *(immediate re-flap)* |
| 19:06:39.765Z | `i40e 0000:02:00.1 enp2s0f1np1: NIC Link is Up, 10 Gbps Full Duplex` |
| 19:06:39.768Z | `i40e 0000:02:00.0 enp2s0f0np0: NIC Link is Up, 10 Gbps Full Duplex` |
| 19:07:07.154Z | `service[etcd](Running): Health check failed: context deadline exceeded` |
| 19:07:12.157Z | `service[etcd](Running): Health check successful` |
| **19:07:13.000Z** | **k8s-3 silent-reboots** (boot ID `e55639d4…`, verified via live `/proc/uptime` per the postmortem correction) |
| 19:07:20.222Z | `enabled shared IP ... vip ... 192.168.1.101 ... link enp87s0` (k8s-2 takes the cluster VIP) |

Both 10G SFP+ ports on k8s-2's i40e (Intel X710) card flap **simultaneously, for ~6 seconds, twice**, and then the cluster VIP fails over to k8s-2 ~7 seconds after k8s-3's reboot. The full physical-link disruption fits inside a 7-second window; the etcd health-check failure 30 seconds later is consistent with k8s-2's etcd timing out on its peer connection to k8s-3.

## Why this is interesting

ADR 0009 — **the SFP+ storage mesh is a full-mesh point-to-point DAC topology**: each node has one DAC cable to each of the other two nodes. There is no switch in this path. So `enp2s0f0np0` is a direct DAC link to one peer, and `enp2s0f1np1` is a direct DAC link to the other peer. They are physically independent cables to physically different peers.

**Both ports going Link Down at the same millisecond is therefore not a peer-side event** — a single peer reboot or single DAC cable fault would only flap one port. Simultaneous bilateral flap means the failure is either:
- **k8s-2's i40e card itself**: a NIC firmware reset, a PCIe link blip, or a brief CPU-side hang where the i40e PHY watchdog autonomously declares "no host responding, link down" and re-negotiates when the host returns
- **A power-rail event on k8s-2**: a brief brownout on the PCIe slot's 12V/3.3V rails, simultaneously affecting both PHYs on the same card

A short kernel/CPU hang on k8s-2 — long enough for the i40e firmware to detect the PCIe bus being unresponsive (Intel datasheets put this at single-digit seconds) — would produce exactly this signature.

## How this changes the hypothesis space

The plan-0013 framing has a "26-minute cascade" hypothesis where k8s-3's failure stresses k8s-1. This evidence introduces a **third node with a precursor symptom**: k8s-2, the held node, had a brief CPU/NIC glitch **41 seconds before k8s-3's verified reboot**.

Three readings, in order of strength:

1. **The same Raptor Lake / Vmin / C-state glitch hit k8s-2 first (briefly), then k8s-3 (severely), then k8s-1 (severely 26 min later).** k8s-2 got lucky — its glitch was short enough that the kernel recovered before any watchdog tripped. This connects directly to the "passes stress, fails at idle" signature in `evidence-2026-04-30-web-research.md`. The 19:06Z event was at idle on a held node, which is exactly when the Raptor Lake Vmin failure mode is supposed to express. **If correct, this is the first observed precursor to a silent-reboot event in the entire investigation.**

2. **k8s-2's NIC card had an isolated firmware glitch, and k8s-3's reboot 41 seconds later was an unrelated coincidence.** Hard to falsify directly, but priors are against it: the cluster has run for ~190 days; both the NIC flap and the reboot are individually rare; their conjunction within a minute on a 3-node cluster is not flat-prior coincidence.

3. **A power-rail event hit the rack briefly.** Plan 0013 demoted the shared-power hypothesis after the 26-min gap landed, but this NIC-flap evidence reopens it for the k8s-2/k8s-3 segment. A brownout severe enough to flap both PHYs on one card but not crash the kernel could plausibly also push k8s-3 over the edge if k8s-3 was already near a Vmin/C-state threshold. The 26-min gap to k8s-1 is then unrelated and needs its own explanation.

Reading (1) is the most parsimonious because it explains *all three* nodes' state on 2026-05-05 with a single mechanism (per-node Vmin/C-state susceptibility, expressed differently by chance), aligns with the "fails at idle" web-research signature, and doesn't require any new mechanism beyond what's already in the candidate set.

## What to verify before acting

This is a single observation. Before committing it as the leading hypothesis:

1. **Search the Vector kernel sink archive** for prior `i40e ... Link is Down` events on any held node within ±60 seconds of past silent reboots (R0–R8 on k8s-2, where some other node was held). The Vector sink was live `2026-04-22 → 2026-05-04 02:00Z`. If even one of R1, R2, R3, R4, R5, R6 (all in the kernel-sink-live window) shows a precursor i40e flap on the *held* nodes (k8s-1 / k8s-3 at the time), this hypothesis becomes load-bearing. If none do, the 2026-05-05 event is anomalous and reading (2) gains weight. The sink data lives in `kubectl -n observability exec talos-log-sink-vector-0 -c rotator -- ls /vector-data-dir/`.

2. **Pull `node_network_up` from the betty off-cluster TSDB** for the 19:00–19:10Z window of 2026-05-05 to see whether *all* held-node observers (k8s-2 was the only one in-cluster, but betty was scraping externally) saw the same simultaneous bilateral flap. Plan 0014 is in-progress; this is a real first use case for it. Endpoint: `100.119.71.22:8428` per `~/.claude/projects/-home-wcygan-anton/memory/reference_betty_access.md`.

3. **Add a PrometheusRule on `up{job="node-exporter"}` flips and on `node_network_up{device=~"enp2s0f.*"}` flapping**. A rule at "any node-exporter target reports 0 for ≥5s" would have caught this 41-second-early signal in real time. Plan 0013 acceptance criterion 1 wants the kernel sink to capture the next event; this would catch a very different signature.

## Discriminating test

**With the kernel sink now restored, a controlled idle-stress run on k8s-1 (or any node) that watches for the bilateral i40e flap signature is the cheapest reproducer.** Specifically: cordon a node, drain it to idle, run no workload on it for 24+ hours, watch its dmesg for any short bilateral i40e link flap. If we see one without a follow-on reboot, we have a reproducer of the precursor signal — at which point we can apply `intel_idle.max_cstate=1` and re-run to see if the flap stops.

This is a far cheaper test than plan 0013 Phase 3's "controlled `talosctl reboot` of k8s-3 to test cascade hypothesis" because it doesn't require a destructive action.

## What this does not claim

- Not claiming reading (1) is proven — it's the strongest single reading among three, with N=1 observation.
- Not claiming this displaces the */30 cron-tick alignment from iteration #1 (`evidence-2026-05-06-half-hour-tick-alignment.md`). They could be independent, or the cron-tick alignment could be spurious. This NIC-flap evidence is far stronger.
- Not claiming the 26-minute gap to k8s-1's reboot is now explained. That's still open under reading (1) — the same Vmin glitch hit k8s-1 26 minutes later by chance, with no causal link to k8s-3's failure.

## Cross-references

- `evidence-2026-04-30-web-research.md` — "passes stress, fails at idle" Raptor Lake Vmin signature; this evidence note is direct supporting field data
- `evidence-2026-05-05-dual-silent-reboot.md` — the postmortem-side write-up of the 2026-05-05 event; should be amended to include the precursor NIC flap on k8s-2
- Plan 0013 Phase 2 (`Retrospective gap analysis on k8s-1 across the 19:07Z → 19:33Z window`) — this evidence reframes the gap analysis: instead of looking for what *propagated* from k8s-3 to k8s-1, look for whether k8s-1 had its own k8s-2-style precursor flap before its 19:33Z reboot (it might be in betty TSDB even though k8s-1's local ring buffer is gone)
- ADR 0009 — SFP+ full-mesh DAC topology; explains why bilateral flap implies k8s-2-local origin
- Personal memory `feedback_node_reboot_timestamps.md` — reboot timestamps must come from live `/proc/uptime`, not recovery-time dmesg; this evidence uses the verified 19:07:13Z k8s-3 boot ID

## Verification trail

```
$ talosctl --endpoints k8s-2 -n k8s-2 dmesg | grep -E '2026-05-05T19:0[6-7]'
... (lines listed in the timeline table above)

$ kubectl get node k8s-2 -o jsonpath='{.status.nodeInfo.bootID}'
28688229-2d15-4216-b028-8b558a5530fe
# Confirms k8s-2 has been on the same boot since the 2026-05-04T01:47Z BIOS-flash boot,
# so 2026-05-05T19:06:32Z dmesg lines are from a held node observing the precursor

$ talosctl --endpoints k8s-2 -n k8s-2 get machinestatus
NODE    NAMESPACE   TYPE            ID        VERSION   STAGE     READY
k8s-2   runtime     MachineStatus   machine   21        running   true
```
