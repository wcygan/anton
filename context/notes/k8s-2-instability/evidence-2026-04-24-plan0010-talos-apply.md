# evidence 2026-04-24 — plan 0010 Phase 2 Talos apply

Rolling apply of commit `1918ca07` across all three control planes to land the kubelet reservation/eviction headroom and the persistent k8s-2 `anton.io/rejoin` label/taint. No reboots. etcd quorum verified between every apply.

## Source of truth

- Commit: `1918ca07` — `feat(plan-0010): stage k8s-2 software rejoin — gates, CNI/kubelet hardening, abort alerts`
- Rendered configs: `talos/clusterconfig/kubernetes-k8s-{1,2,3}.yaml` (generation from tagged commit)
- Patches exercised:
  - `talos/patches/global/machine-kubelet.yaml` — systemReserved/kubeReserved (cpu=500m, memory=2Gi each) + evictionHard (memory.available=2Gi, nodefs.available=10%, nodefs.inodesFree=5%, imagefs.available=15%, imagefs.inodesFree=5%)
  - `talos/talconfig.yaml` — k8s-2-only `nodeLabels[anton.io/rejoin]=k8s-2` and `nodeTaints[anton.io/rejoin]=k8s-2:NoSchedule`

Dry-run diffs confirmed scope pre-apply: kubelet extraConfig additions on all three, plus label/taint only on k8s-2. Both apply modes returned `Applied configuration without a reboot` — kubelet hot-reloaded, no machine restart.

## Apply sequence

| Order | Node | UTC apply start | Mode | Result |
|---|---|---|---|---|
| 1 | k8s-2 (192.168.1.99) | 2026-04-24T17:49:10Z | auto | Applied configuration without a reboot |
| 2 | k8s-3 (192.168.1.100) | 2026-04-24T17:49:33Z | auto | Applied configuration without a reboot |
| 3 | k8s-1 (192.168.1.98) | 2026-04-24T17:49:43Z | auto | Applied configuration without a reboot |

Full roll completed in under 1 minute wall-clock. Apply order matched operator plan: k8s-2 (lowest blast radius, already cordoned) → k8s-3 → k8s-1 (etcd leader, applied last).

## etcd quorum between applies

Leader stable at k8s-1 (`8626e6c4157f9b39`) throughout. Raft term did NOT change (term 29 at pre-baseline, term 29 at final) — confirms no member ever went down.

| Checkpoint | k8s-1 raft index | k8s-2 raft index | k8s-3 raft index | leader | term | healthy |
|---|---|---|---|---|---|---|
| pre-apply baseline | 162931364 | 162931374 | 162931379 | k8s-1 | 29 | 3/3 |
| after k8s-2 apply | 162931759 | 162931760 | 162931760 | k8s-1 | 29 | 3/3 |
| after k8s-3 apply | 162931990 | 162931990 | 162931991 | k8s-1 | 29 | 3/3 |
| after k8s-1 apply (final) | 162932359 | 162932363 | 162932367 | k8s-1 | 29 | 3/3 |

DB size held at 104MB on every member, no fragmentation delta. Quorum never dropped to 2/3 — it stayed 3/3 the entire window because kubelet reloads do not restart etcd.

## Allocatable — pre vs post

Operator-captured baseline (pre-apply):

| Node | CPU alloc | Memory alloc | Memory capacity |
|---|---|---|---|
| k8s-1 | 19950m | 97944184Ki | 98570872Ki |
| k8s-2 | 19950m | 97951180Ki | 98577868Ki |
| k8s-3 | 19950m | 97903884Ki | 98530572Ki |

Post-apply (observed):

| Node | CPU alloc | Memory alloc | CPU delta | Memory delta |
|---|---|---|---|---|
| k8s-1 | 19 (=19000m) | 92279416Ki | −950m | −5664768Ki (5.40 GiB) |
| k8s-2 | 19 (=19000m) | 92286412Ki | −950m | −5664768Ki (5.40 GiB) |
| k8s-3 | 19 (=19000m) | 92239116Ki | −950m | −5664768Ki (5.40 GiB) |

Interpretation:

- **CPU drop of 950m** (slightly under the expected 1000m) is correct. The kubelet rounds `cpu` reporting to integer when whole cores are available, and the "allocatable = capacity − reserved − system pod overhead" math depends on existing CPU management policy. The raw reservation of 1000m (500m+500m) is in effect; the 50m residual vs baseline is a reporting artifact of the integer-cores output.
- **Memory drop of ~5.40 GiB** is the *observable* drop. Expected analytical drop is 6 GiB (2Gi systemReserved + 2Gi kubeReserved + 2Gi evictionHard). The delta is lower than 6 GiB because the pre-baseline was already subtracting an internal eviction reserve; the new evictionHard threshold changes the memory.available threshold to 2Gi but does not double-subtract.
- **Exact allocatable per node = capacity − 6291456Ki (6 GiB):** k8s-1: 98570872 − 6291456 = 92279416 (match). k8s-2: 98577868 − 6291456 = 92286412 (match). k8s-3: 98530572 − 6291456 = 92239116 (match). The operator's "~91,656,728Ki" target was a rough estimate; the observed numbers are the true algebraic values and are correct.

All three allocatable drops are within the tolerance band for "reservations took effect". No abort trigger.

## k8s-2 label and taint verification (post-apply, live Node object)

```
labels[anton.io/rejoin] = k8s-2
taints:
  - key: node.kubernetes.io/unschedulable   effect: NoSchedule   (pre-existing from Phase 0 cordon)
  - key: anton.io/rejoin   value: k8s-2     effect: NoSchedule   (NEW — from this apply)
```

Both the label and the NoSchedule taint are present on the live Kubernetes Node object, not just in machine config. The persistent rejoin gate is in place. Any future `kubectl uncordon k8s-2` will remove only the `node.kubernetes.io/unschedulable` taint and leave the `anton.io/rejoin=k8s-2:NoSchedule` gate intact — meeting the plan's "persistent, not imperative" requirement.

## Event stream and workload health

`kubectl get events -A` during the roll window showed only the expected `Starting kubelet / NodeAllocatableEnforced / NodeHas*` sequence per node. No pod eviction events, no OOMKilled, no pull errors, no CNI flapping. The only noisy entries were pre-existing: SeaweedFS `VolumeClaimTemplatesMismatch` warning (known from plan 0006 Harbor backup work) and routine Flux artifact-up-to-date messages.

Post-roll:

- `kubectl get pods -A` filter for non-Running/non-Completed: empty.
- `flux get ks -A` filter for non-Ready: empty (all Kustomizations Ready=True).

## Observations / anomalies

1. **Off-LAN endpoint quirk.** `talosctl -e k8s-1 -n k8s-1,k8s-2,k8s-3 version` fails with `name resolver error: produced zero addresses` for the non-endpoint nodes, because the server at `-e` proxies via LAN IPs. The workaround is to match `-e` to `-n` per call (`-e k8s-2 -n k8s-2`). Not a new issue, worth keeping in mind for future rolling operations off-LAN.
2. **CPU allocatable rounds to integer.** 19950m → 19 rather than 18950m. This is expected kubelet behavior when whole cores are reserved but the allocatable is reported via the capacity API; downstream requests honor the real 1000m reservation regardless of display format.
3. **Memory drop is 5.40 GiB, not 6 GiB.** As explained above, the pre-baseline already had internal eviction slack. The math checks against capacity, so reservations did land correctly. No action needed.
4. **k8s-2 retains TWO NoSchedule taints now** (`node.kubernetes.io/unschedulable` + `anton.io/rejoin=k8s-2`). This is intentional: Stage A uncordon will drop only the first, leaving the persistent rejoin gate in place for any workload that hasn't added the matching toleration.

## Gate status

- [x] etcd quorum held 3/3 throughout
- [x] all three nodes returned Ready within seconds (kubelet hot-reload)
- [x] allocatable dropped as expected on all three nodes
- [x] no pod eviction storm
- [x] Flux all-Ready post-roll
- [x] k8s-2 has the persistent `anton.io/rejoin` label AND taint on the live Node object

No abort condition triggered. Plan 0010 Phase 1 verification task and Phase 2 apply task are complete. Stage A uncordon is explicitly NOT part of this work and remains a separate later gate.
