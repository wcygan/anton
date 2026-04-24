# 2026-04-24 — CNI-layer restart counts across the 04-23 window

## One-line

All three nodes' CNI-plumbing DaemonSets (kube-multus, whereabouts,
storage-vxlan) show container restarts clustered ~18h before 2026-04-24
15:02Z — i.e., ~2026-04-23 ~20:00-21:00Z — matching the re-admission +
reboot-cascade window. k8s-1 did NOT hard-reboot but its multus still
restarted 5 times in the same window. The stability difference between
k8s-1 and k8s-2/k8s-3 is therefore **not** "k8s-1 escaped the trigger"
— it's "k8s-1 survived the trigger without escalating to node-level
reset."

## Live data (captured 2026-04-24 15:02Z)

| Pod                    | Node  | RESTARTS   | Age   | Memory limit |
|------------------------|-------|-----------:|-------|-------------:|
| `whereabouts-6chbl`    | k8s-2 | **10** (18h ago) | 5d1h  | 200 MiB |
| `kube-multus-ds-vmz29` | k8s-1 | **5**  (18h ago) | 5d1h  | 256 MiB |
| `storage-vxlan-5dtmz`  | k8s-2 | **5**  (18h ago) | 4d19h | 64 MiB  |
| `kube-multus-ds-5r6zx` | k8s-2 | 2 (18h ago)      | 3d    | 256 MiB |
| `whereabouts-r47l6`    | k8s-3 | 1 (18h ago)      | 18h   | 200 MiB |
| `kube-multus-ds-hpt2m` | k8s-3 | 0 (post-reboot fresh) | 18h   | 256 MiB |
| `whereabouts-dqbzs`    | k8s-1 | 0                | 5d1h  | 200 MiB |
| `storage-vxlan-9lxwt`  | k8s-1 | 0                | 4d19h | 64 MiB  |

Source: `kubectl -n network get pods -o wide` at 2026-04-24 15:02Z.
The "18h ago" relative timestamps map to ~2026-04-23 21:00Z ±1h — i.e.
the re-admission + cascade window.

## What the pattern fits

**Pod-churn burst at 20:30-20:47Z on 2026-04-23 exercised the Multus +
Whereabouts + VXLAN IPAM path hard enough to OOMKill those containers
at their current (undersized) limits.** Same mechanism hit all three
nodes at the same wall-clock time:

- k8s-1: 5 multus restarts — survived because no hard-reboot signal
  escalated
- k8s-2: 10 whereabouts + 5 vxlan + 2 multus restarts — hard-rebooted
  at 20:47Z
- k8s-3: 1 whereabouts restart + hard-rebooted at 20:45Z

The asymmetry between node responses is most parsimoniously explained
by the BIOS/microcode split: k8s-1 on BIOS 1.26 (microcode 0x12B+)
tolerated the stress; k8s-2 and k8s-3 on BIOS 1.22 escalated to silent
reset (Intel Raptor Lake Vmin-shift "crashes under light-to-moderate
load" is a documented trigger in this microcode window).

## Current memory limits vs upstream guidance

| DaemonSet        | Current | Upstream guidance                              |
|------------------|--------:|------------------------------------------------|
| `kube-multus-ds` | 256 MiB | Broadcom KB 325399 recommends ≥ 512 MiB request, 150 MiB floor on very small clusters |
| `whereabouts`    | 200 MiB | No strong upstream recommendation; worth raising proportionally |
| `storage-vxlan`  | 64 MiB  | Homelab-local DS; re-evaluate if it's OOM-adjacent |

The 256 MiB Multus limit matches the Broadcom KB-flagged undersize
pattern. Recommended action (plan 0009 Phase 4b): bump kube-multus-ds
limit 256 → 512 MiB; evaluate whereabouts and storage-vxlan from
post-bump metrics.

## How this reframes the hypothesis ranking

Before this data: "distributed trigger on re-admission pod churn" was
the #1 hypothesis but the mediating mechanism was unknown ("CSI
registration? Multus? Longhorn engine?"). After this data: the
mediating mechanism is **specifically the Multus + Whereabouts + VXLAN
IPAM path**, with k8s-1's 5 restarts as the "smoking gun that something
is OOMing under pod-creation burst even on the 'stable' node."

Updated hypothesis framing: **CNI-layer OOMKills under pod-creation
burst, interacting with BIOS-1.22 microcode on k8s-2 and k8s-3 to
escalate into silent node reset**. Two layers, one trigger, two
independent fixes (Multus limit bump + BIOS flash).

## What's still unverified

- The precise time-of-restart for each DaemonSet pod isn't captured
  by `RESTARTS (18h ago)` beyond the ~1h window. The Vector sink or
  `kubectl describe pod` on each can pin the exact second; not done
  here.
- Whether `whereabouts-6chbl`'s 10 restarts happened in one acute burst
  or trickled across the window. If burst, it indicates a restart
  cycle (OOMKill → restart → OOMKilled again on the same churn) —
  this is the cilium-pattern from 04-20 one layer down.
- Whether k8s-1's 5 multus restarts were over the 04-23 ~20Z window
  specifically, or were earlier-week noise that happened to settle at
  the same relative timestamp. Verifiable via pod event timeline.
- The 04-21 20:34Z solo k8s-2 reboot — did it have the same CNI-layer
  restart fingerprint? We don't have the data because Phase 3 Vector
  sink wasn't active yet. This gap is structural.

## Related

- `evidence-2026-04-23-cluster-reboot.md` — full cascade timeline; this
  file is the CNI-layer zoom-in
- `../README.md` — hypothesis ranking (updated 2026-04-24)
- Plan 0009 Phase 4b — Multus limit bump task driven by this data
- Plan 0009 Phase 5 — BIOS flash task that pairs with the above

---

## Addendum — 2026-04-24 (later) peer-agent falsifications

An independent read-only review of this file surfaced four corrections.
**Keep the body above as the initial hypothesis; treat these as what
actually happened.**

### 1. Whereabouts restarts are NOT OOMKills

The "10 whereabouts OOMKills" framing was inferred from the restart
count; it was never verified against the termination reason. Actual
state (`kubectl -n network get pod whereabouts-6chbl -o yaml`):

- `restartCount: 10`
- `lastState.terminated.reason: Error`
- `lastState.terminated.exitCode: 1` (NOT 137 / OOMKilled)
- `finishedAt: 2026-04-23T20:47:57Z`, `startedAt: 2026-04-23T20:47:25Z`

Exit 1 = generic error, NOT OOM. Kubernetes only preserves the LAST
termination reason, so we can't say whether the 9 earlier restarts
were the same cause — but we have zero evidence they were OOM. The
"layer 1 = CNI OOMKills on all three nodes" framing is weakened for
whereabouts specifically. Multus (on k8s-1 and k8s-3) pre-reboot OOM
activity IS real — see #3 below.

### 2. k8s-3 did not silently reboot on 04-23 — it was intentional

Plan 0006 (Harbor adoption) Log 2026-04-23, line 115 records an
operator-initiated controlled-reboot acceptance test on k8s-3:

- 20:35:41Z cordoned k8s-3
- 20:35:57Z drain started
- 20:44:37Z reboot issued via `talosctl -e 100.100.217.100 -n
  100.100.217.100 reboot`
- 20:49:42Z k8s-3 back Ready (~5 min; normal Talos reboot cadence)

The "k8s-3 reboot at 20:45Z" this file treats as cascade evidence is
that operator-initiated reboot. **k8s-3 has never silently rebooted
during the investigation.**

This invalidates the two-node-cascade framing. On 04-23 there was:
- One **intentional** reboot on k8s-3 (operator drain test)
- One **unexplained silent reboot** on k8s-2 at 20:47Z, coincident
  with the Harbor churn fallout from the k8s-3 drain

Back to **single-node silent reboots on k8s-2 only**: 04-21 20:34Z
solo, 04-23 20:47Z during Harbor-induced churn. Two events, not three.

### 3. CNI restart timeline on k8s-2 is POST-reset fallout, not pre-reset cause

Vector sink + Prometheus timeline per peer review:

- 20:36:18Z — Multus OOM on k8s-3 (pre-k8s-3-reboot)
- 20:36:31Z — Multus OOM on k8s-1 (during Harbor churn, k8s-1 survived)
- 20:40:20-41:00Z — final Multus OOM burst on k8s-1
- 20:44:37Z — k8s-3 intentional reboot issued
- 20:47Z — k8s-2 silent reboot (unexplained)
- 20:47:19Z onward — k8s-2 Multus/storage-vxlan restart counts
  increment as pods fail to finalize during the unplanned reboot

The k8s-2 CNI restart counts (Multus=2, storage-vxlan=5 on k8s-2) are
**effects** of k8s-2's reboot, not causes. The genuine pre-reboot CNI
pressure was on k8s-1 and k8s-3 from the Harbor drain churn — and
Plan 0006 Log 2026-04-23 (line 115) already documents this:

> "harbor-redis-2 was stuck ContainerCreating on k8s-1 (Multus daemon
> OOMKilled x4 under the pod-creation burst, same class of symptom as
> the 2026-04-21 entry's 50→256Mi fix but still recurring under
> drain-induced churn)"

### 4. 04-21 k8s-2 solo reboot had NO pre-reboot CNI spike

Prometheus `increase(kube_pod_container_status_restarts_total
{namespace="network"}[5m])` across the 04-21 20:00-21:00Z window on
k8s-2 shows no CNI restart activity until 20:37-20:41Z — **after** the
20:34Z reboot. For 04-21, the CNI restarts are again post-reset
fallout, not pre-reset trigger.

This means the CNI-layer story does NOT explain the 04-21 event. It
may still explain the 04-23 20:47Z event (given the confirmed k8s-1
Multus OOM storm from plan 0006 during the Harbor drain), but 04-21
is back to "unexplained single-node silent reboot, no identifiable
trigger."

### What the two-layer framing should be now

Not "CNI layer 1 × BIOS microcode layer 2 for two-node cascade."
Instead:

- **Layer 1 — CNI OOM under pod-creation burst:** REAL and documented
  on k8s-1 and k8s-3 on 2026-04-23 during Harbor drain (plan 0006 Log)
  and on 2026-04-21 during Harbor deploy (plan 0006 Log). Self-recovers.
  Does not on its own cause node reset. Multus 50→256 Mi bump from plan
  0006 didn't fully contain it; Plan 0009 Phase 4b 256→512 Mi bump is
  still justified.
- **Layer 2 — Silent k8s-2 reboot:** Happens in CNI-churn-adjacent
  windows (04-23) AND without CNI churn (04-21). Trigger unknown.
  k8s-2-specific. BIOS 1.22 is suggestive but microcode is identical
  across all nodes (0x00006134, per peer agent verification), so the
  Intel Vmin-shift microcode story is weaker than stated. Single-unit
  hardware defect hypothesis re-strengthened since k8s-3 never
  silently rebooted.

Plan 0009 and the investigation README hypothesis ranking need updates
reflecting these corrections.
