---
status: Active
opened: 2026-05-05T19:54Z
detected-at: 2026-05-05T19:54Z (T+41h watch tick caught boot-ID diff)
event-at: 2026-05-05T19:07Z (k8s-3) and ~19:33Z (k8s-1) — sequential, not simultaneous; corrected 2026-05-05 evening
severity: SEV-2 (public services unreachable; cluster control plane healthy; data plane intact)
related-plans: [0009]
related-postmortem: ../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md
---

# 2026-05-05 — k8s-1 + k8s-3 sequential silent reboot

> Sequential silent reboot of k8s-3 (~19:07Z) and k8s-1 (~19:33Z) — **~26 min apart, not simultaneous as originally framed** — while k8s-2 held cleanly. Public ingress dropped because cloudflare-tunnel and envoy-external pods were stuck as `Unknown` ghosts on k8s-1 with no replacement scheduling.

## ⚠ Correction — 2026-05-05 evening

The original timeline below claimed a **simultaneous within ~28 s** dual reboot at 19:33:54Z (k8s-3) → 19:34:22Z (k8s-1). Cross-verification on the live cluster shows this is **wrong** by ~26 minutes for k8s-3:

| Node | Original claim | Verified boot time | Method |
|---|---|---|---|
| k8s-3 | 2026-05-05T19:33:54Z | **2026-05-05T19:07:13Z** | live `/proc/uptime` via cilium-agent privileged exec; boot ID `e55639d4…` matches the watch-loop record |
| k8s-1 (silent reboot) | 2026-05-05T19:34:22Z | ~19:33Z (not independently verifiable; overwritten by 20:29Z graceful reboot) | original dmesg-based estimate retained |
| k8s-1 (graceful reboot) | 2026-05-05T20:29Z | **2026-05-05T20:29:07Z** | live `/proc/uptime` confirms |
| k8s-2 | did not reboot | **did not reboot** (boot 2026-05-04T01:47:06Z) | confirmed via `/proc/uptime`; consistent with `Node.Ready.lastTransitionTime` 2026-05-04T01:47:18Z |

**Corroborating evidence found post-correction**:
- k8s-2 dmesg shows both SFP+ NICs dropping at 19:06:32Z (≈40 s before k8s-3's 19:07:13Z boot — consistent with k8s-3 going down then booting back)
- k8s-3 mass container exit=255 at 19:07:25Z (kubelet rebuilding post-boot)
- KCM + scheduler leadership transferred to k8s-2 at 19:07:36Z (k8s-3 had been holding leases)
- k8s-3 whereabouts `i/o timeout to 10.43.0.1:443` at 19:08:01Z (still recovering)

**Why the original claim was wrong**: the postmortem's "earliest post-reboot dmesg" timestamps for both nodes were collected during recovery (~T+50 min). The k8s-3 dmesg at that time started at 19:33:54Z because the node had cycled through its full Talos boot sequence and the early dmesg lines had aged out of the ring buffer by the time recovery began. The boot-ID watch loop had captured the actual reboot earlier but the timestamp was not cross-referenced.

**What this implies for plan 0009**:

- The "simultaneous within ~28s" pattern is *not real*. The actual pattern is **sequential, ~26 min apart, with k8s-3 going first**.
- The "cluster-wide trigger that takes 2 nodes down at once" hypothesis is **weaker** than it looked — sequential failures with a multi-minute gap are more consistent with cascade (one node's failure stresses the cluster, and that stress eventually breaks a second node) than with a simultaneous external trigger.
- Hypotheses needing re-examination in light of this correction:
  - The "k8s-1 ↔ k8s-3 SFP+ DAC #2 simultaneous failure" hypothesis (cf. evidence-note candidate #2) — if k8s-3 failed alone first and k8s-1 failed 26 min later, a *single* DAC failure cannot explain both
  - The "shared power topology" hypothesis (postmortem candidate 2) — same reasoning; sequential failures don't fit a power event unless the events are independent
  - The "cluster-wide kernel-level mechanism" hypothesis (evidence-note candidate #1) — *strengthened*; a kernel mechanism that takes time to propagate or to fire on a second node fits a 26-min gap well

The analysis sections below were written under the simultaneous-within-28s framing and have **not been rewritten**. Treat conclusions in those sections that depend on the simultaneity claim with skepticism.

---

## Impact

- `<public-site-A>` — unreachable
- `<public-site-B>` — unreachable
- Other public-facing HTTPRoutes via the shared cloudflare-tunnel — unreachable
- Tailscale operator API proxy — unreachable, so remote `kubectl` via the normal `tailscale-operator.<tailnet>.ts.net` context fails (worked around with a direct kubeconfig generated via `talosctl kubeconfig`, server pinned to k8s-1 Tailscale IP)
- Cluster control plane: **healthy** (etcd 3/3, k8s-2 leader at term 32, all three nodes Ready)
- Storage data plane: not yet verified end-to-end

## Detection

- `loop` cron job `1762a4f1` running an off-cluster bastion-side BIOS-flash watch fired at T+41h (post-flash baseline `2026-05-04T01:46Z` k8s-2 boot ID `28688229…`)
- Boot-ID baseline diff at the watch tick:
  - k8s-1 `374d7bdd-530f-4e88-8194-8f66554b9ca8` → `3d007d1c-735f-46b3-baaa-84bef1525851` **CHANGED**
  - k8s-2 `28688229-2d15-4216-b028-8b558a5530fe` **UNCHANGED** (the node under watch held)
  - k8s-3 `7cc9ced8-a46a-459f-b860-674df340d23b` → `e55639d4-9be7-4d73-a31d-0279a99abffe` **CHANGED**
- Loop escalated, CronDelete'd, PushNotification sent, plan 0009 Log appended.

## Why this is significant

This is a **net-new failure mode** for the silent-reboot investigation:

1. **k8s-1 silently rebooted for the first time in the entire investigation.** k8s-1 had been the rock since the April 2026 cluster reset (uptime weeks; no recorded silent reboots in plan 0007/0009/0010 history).
2. **Cross-node cascade reboot (k8s-3 then k8s-1, ~26 min apart), k8s-2 held** — *inverse* of every prior incident, where k8s-2 was always the affected node. (Originally framed as "two-node simultaneous reboot"; corrected in the banner above.)
3. **BIOS version not predictive — and likely not the right axis under the cascade framing.** k8s-1 is on **1.26** (untouched), k8s-3 is on **1.27** (post-flash 2026-05-04), k8s-2 is on **1.27** (post-flash 2026-05-04). The two rebooted nodes span both BIOS versions; the held node shares a BIOS version with one of the rebooted nodes. Under the corrected sequential-cascade hypothesis (k8s-3's failure triggered k8s-1 ~26 min later), the trigger node and the cascade target are on *different* BIOS versions — so even if BIOS were a stability factor for the trigger, it isn't protective for the cascade victim. The observation that BIOS isn't predictive is reinforced; the more relevant axes are now whatever propagates between nodes (network, etcd, Cilium, kubelet/API recovery dynamics).
4. **No kernel-side trace captured.** The Vector kernel sink was torn down at T+14h post-flash (commit `4037deec`, plan 0007 Phase 5 file-side teardown), as documented in plan 0009 Log entry 2026-05-04 T+14h checkpoint with the explicit trade-off note. Going forward the only forensic surface is Prometheus + ring buffers on the surviving node (k8s-2).

## Initial state at T+0 of recovery (2026-05-05T19:54Z)

- Etcd: 3/3 healthy, k8s-2 (`192.168.1.99`) leader, RAFT term 32, all members same applied index
- Nodes: 3/3 Ready (k8s-1 + k8s-3 kubelets healthy 48 m post-reboot, k8s-2 kubelet healthy 42 h)
- Ghost pods on k8s-1 (visible via direct kubeconfig):
  - `network/cloudflare-tunnel-84956569f7-ffm64` 0/1 Unknown 4d15h
  - `network/envoy-external-ff96479-2h2j7` 0/2 Unknown 4d2h
  - `network/envoy-external-ff96479-dvqdk` 0/2 Unknown 42h
  - `network/envoy-gateway-cdcdf85b9-2td67` 0/1 Unknown 42h
  - `network/envoy-internal-76c7d867fd-d5gtd` 0/2 Unknown 4d2h (one fresh replica `…-z7hs8` is up 1/2 Running)
  - `tailscale/operator-5799fd8f6c-z5kfc` 0/1 Unknown 4d15h
  - `tailscale/ts-kube-prometheus-stack-grafana-8t55d-0` 0/1 Unknown 4d14h
  - Plus many others (cert-manager, coredns terminating, hubble, metrics-server, reloader, csgoplant app/db, harbor, prometheus, grafana, external-secrets, dragonfly-operator, cnpg) — all on k8s-1
- Harbor: `harbor-core` in CrashLoopBackOff (post-reboot recovery in progress)
- Public ingress: down because both cloudflare-tunnel and envoy-external have 0 ready replicas

## Mechanism (high-confidence read)

Same post-reboot containerd ghost-pod recovery deadlock pattern documented in plan 0007 day-1 Log (2026-04-20). The Unknown pods predate today's reboot — they have been running on k8s-1's containerd for days while marked `Unknown` in the API server (kubelet stopped reporting on them at some point ~4d15h ago, but the actual containers stayed alive). When k8s-1 rebooted, containerd reset and the actual containers died, but the API-server records remain `Unknown` so the ReplicaSets won't create replacements.

Recovery: force-delete the ghost pods so ReplicaSets can re-create them and the scheduler can place fresh pods on healthy nodes (k8s-2 or k8s-3).

## Timeline

> Corrected 2026-05-05 evening — see Correction section above. Original simultaneous-within-28s framing struck through; verified timestamps marked ✓.

- ✓ **T-0 (2026-05-05T19:07:13Z)** — k8s-3 silent-reboot boot completes (boot ID `e55639d4…`, verified via live `/proc/uptime`). k8s-2 dmesg shows SFP+ NICs dropping at 19:06:32Z (~40 s earlier).
- ✓ **T+0:12 (2026-05-05T19:07:25Z)** — k8s-3 kubelet rebuilds containers (mass exit=255 cascade)
- ✓ **T+0:23 (2026-05-05T19:07:36Z)** — KCM + scheduler leadership transfers to k8s-2 (k8s-3 had been holding leases)
- ✓ **T+0:48 (2026-05-05T19:08:01Z)** — k8s-3 whereabouts `i/o timeout to 10.43.0.1:443`; node still unstable
- ~~**T+0:28 (2026-05-05T19:34:22Z)** — k8s-1 boots~~ — **corrected**: this was the original "k8s-1 boots" claim from recovery dmesg; the actual silent-reboot moment is ~19:33Z (cannot independently verify from current state since the 20:29Z graceful reboot overwrote `/proc/uptime`)
- **T+~26 min (2026-05-05T~19:33Z)** — k8s-1 silent-rebooted (postmortem timestamp; not independently verifiable)
- **T+~21 min from k8s-3 (2026-05-05T19:54Z)** — bastion watch loop tick detects 2-of-3 boot-ID diff (loop's cadence is 30 min, so this is the next tick after both reboots); loop escalates and stops
- **T+~77 min (2026-05-05T20:24Z)** — operator triages; identifies ghost-pod recovery deadlock; authorizes force-delete recovery and incident-file authoring
- ✓ **2026-05-05T20:29:07Z** — k8s-1 graceful reboot completes (boot ID `65fc58fd…`, verified via live `/proc/uptime`)

## Recovery actions (will append as executed)

### Batch 1: ingress + Tailscale operator (2026-05-05T20:01Z)

Force-deleted ghost pods to unblock public ingress and the Tailscale operator API proxy:
```
kubectl delete pod -n network \
  cloudflare-tunnel-84956569f7-ffm64 \
  envoy-external-ff96479-2h2j7 envoy-external-ff96479-dvqdk \
  envoy-gateway-cdcdf85b9-65q87 \
  --force --grace-period=0
kubectl delete pod -n tailscale operator-5799fd8f6c-z5kfc --force --grace-period=0
```
Outcome (44s after delete):
- `cloudflare-tunnel-…txj4k` 1/1 Running on k8s-3, all 4 tunnel connections registered to Cloudflare edge (ord12 + ord16)
- `envoy-external-…8l2ps` 2/2 Running on k8s-3; second replica `…dmngp` ContainerCreating on k8s-2
- `envoy-gateway-…65q87` 1/1 Running on k8s-3
- `tailscale operator-…f6sdj` 1/1 Running on k8s-3 — `kubectl` via the standard Tailscale-operator kubeconfig works again

Public site verification:
- `<public-site-B>` → **200 OK** ✓
- `<public-site-A>` → **503** (backend csgoplant ghosts still present at this point)

### Batch 2: bulk force-delete of remaining `Unknown` ghosts on k8s-1 (2026-05-05T20:05Z)

Used a single `xargs -L1 -P5` parallel sweep against `kubectl get pods -A` filtered to phase=`Unknown`. Scope: every namespace including network/cloudflare-dns + envoy-internal old replica, kube-system (hubble, metrics-server, reloader, terminating coredns), cert-manager, external-secrets, default (echo + homepage), csgoplant (app x2 + dragonfly + postgres-1), databases (cnpg + dragonfly-operator), observability (prometheus + grafana + kps-operator), registries (harbor jobservice/nginx/portal x2/postgres x3/redis x3/registry), storage (csi-attacher x2 / csi-provisioner x3 / csi-resizer x2 / csi-snapshotter x3 / engine-image / longhorn-driver-deployer / longhorn-manager / longhorn-ui x2 / seaweedfs-filer-1 / seaweedfs-master-0,1,2 / seaweedfs-volume-1,2), tailscale (ts-grafana statefulset pod).

All Unknown pods cleared from the API. ReplicaSets / StatefulSets / DaemonSets actively re-creating replacements; scheduler placing them on k8s-2 and k8s-3 (with some still binding on k8s-1 as it stabilizes).

### Settling phase

Watchlist after batch 2:
- `harbor-core-746ff7bdd6-dghsv` and `-s7j9z` (both on k8s-1, pre-existing) in `CrashLoopBackOff` — expected to clear once SeaweedFS masters reach quorum
- `seaweedfs-filer-0` (k8s-1, pre-existing) in `CrashLoopBackOff` — same upstream dependency
- `harbor-exporter` on k8s-1 in `CrashLoopBackOff` — SeaweedFS dependency
- `csgoplant-app` × 2 ContainerCreating on k8s-2 + k8s-3 — pulling image from Harbor at `192.168.1.106`; Harbor recovery is the gating dependency
- `longhorn-manager-swvxg` (k8s-1) and `seaweedfs-master-0` (k8s-1) in ContainerCreating — should converge once their PVCs / config bind

### Batch 3: cordon k8s-1 + reschedule stuck pods (2026-05-05T20:09Z)

Diagnosis: pods that the scheduler placed on k8s-1 after the reboot were stuck in `Init:0/1` / `ContainerCreating` for several minutes with **no kubelet events after `Scheduled`** — same pattern as plan 0007 day-1 Log (containerd sandbox-name saturation; kubelet `FailedKillPod` with `DeadlineExceeded` against its own containerd while trying to clean up the force-deleted ghost pods). Also visible in events:
```
FailedKillPod  pod/cloudflare-tunnel-…ffm64  error killing pod: KillPodSandboxError: rpc error: code = DeadlineExceeded
FailedKillPod  pod/envoy-external-…2h2j7   error killing pod: KillPodSandboxError: rpc error: code = DeadlineExceeded
FailedKillPod  pod/envoy-external-…dvqdk   error killing pod: KillPodSandboxError: rpc error: code = DeadlineExceeded
```
Talos-level `containerd` service reports STATE=Running HEALTH=OK, matching the plan-0007 finding that Talos's service-layer view doesn't catch this kind of internal containerd state corruption.

Action: `kubectl cordon k8s-1` to stop new scheduling there, then force-delete the movable pods that were stuck on k8s-1 so they reschedule onto k8s-2 / k8s-3:
```
kubectl cordon k8s-1
kubectl delete pod -n csgoplant csgoplant-app-…7nw6x csgoplant-postgres-1 --force --grace-period=0
kubectl delete pod -n observability kube-prometheus-stack-operator-…fwlkb --force --grace-period=0
kubectl delete pod -n registries harbor-nginx-…mwrxb harbor-portal-…pdxbw harbor-postgres-2 harbor-redis-1 --force --grace-period=0
kubectl delete pod -n storage seaweedfs-master-0 seaweedfs-volume-2 csi-provisioner-…8fn5t csi-snapshotter-…lzv27 longhorn-ui-…prsdk --force --grace-period=0
kubectl delete pod -n tailscale ts-kube-prometheus-stack-grafana-8t55d-0 --force --grace-period=0
```
DaemonSet pods on k8s-1 (engine-image-ei-…hrpbf, longhorn-manager-swvxg, longhorn-driver-deployer-…ht4mj) deliberately left alone — they're per-node and will retry as k8s-1's kubelet works through its cleanup queue.

### Public-site recovery confirmed (2026-05-05T20:13Z)

```
$ curl -L https://<public-site-B>/   → 200 OK
$ curl -L https://<public-site-A>/       → 200 OK (resolves via /strategies redirect)
```

Tailscale-operator-backed `kubectl` works again via the standard `~/.config/sops/age.key` + `kubeconfig` path; the `/tmp/anton-direct-kubeconfig` workaround is no longer required for routine access.

### Remaining work (in flight, watching)

- 16 pods still recovering as of 20:14Z, mostly on k8s-2 / k8s-3 in normal Init / ContainerCreating states, ~1 min old
- 3 pods stuck on k8s-1 (DaemonSet members): engine-image-ei, longhorn-manager, longhorn-driver-deployer — gated on k8s-1 kubelet/containerd recovery
- Harbor stack still bringing up redis-1 + postgres-2 on healthy nodes
- Prometheus + Grafana initializing on k8s-2
- `seaweedfs-volume-2` Pending — likely PVC pinned to k8s-1; will need attention separately

### Open question: how to recover k8s-1's wedged kubelet/containerd

Two paths matching plan 0007 history:
1. **`talosctl reboot --mode=default` on k8s-1** — etcd 3/3 healthy so quorum is fine; produces another boot ID transition (cosmetically muddies the boot-ID watch baseline more than it already is); ~2-3 min disruption.
2. **Wait it out** — kubelet eventually drains its KillPodSandbox queue, but plan 0007 day-1 history suggests this can take hours and may never complete cleanly without intervention.

### Batch 4: graceful reboot of k8s-1 (2026-05-05T20:29Z)

Operator chose option 1. Executed:
```
talosctl --talosconfig ./talos/clusterconfig/talosconfig \
         --endpoints 100.87.89.3 --nodes 100.75.61.79 \
         reboot --mode=default
```
Used **k8s-2 (etcd leader)** as the API endpoint so the in-flight talosctl call would survive k8s-1 going down. Reboot sequence completed cleanly:
- `task: stopAllPods action: STOP`
- `phase: cleanup action: STOP`
- `phase: stopServices action: START`
- (transient `transport: ENHANCE_YOUR_CALM` retry — benign)
- `sequence: initialize action: START` → `phase: systemRequirements action: START` → kubelet ready

Post-reboot state on k8s-1:
- Boot ID: `65fc58fd-26bb-44fe-91a3-f44eb5d421a5` (was `3d007d1c-735f-46b3-baaa-84bef1525851`)
- Uptime: 46 s at first check, kubelet healthy
- kube-apiserver-k8s-1 1/1 Running 27 s after kubelet up
- cilium-zkfx9 1/1 Running on k8s-1
- Etcd 3/3 healthy at term 32, k8s-2 still leader, all members same applied index `177226274`

### Batch 5: post-reboot pod refresh + uncordon (2026-05-05T20:30Z)

```
kubectl uncordon k8s-1
kubectl delete pod -n storage \
  engine-image-ei-…hrpbf longhorn-driver-deployer-…ht4mj longhorn-manager-swvxg \
  --force --grace-period=0
kubectl delete pod -n bakery-site bakery-server-75d74bdf57-sh2d9 --force --grace-period=0
kubectl delete pod -n registries \
  harbor-core-…dghsv harbor-core-…s7j9z harbor-exporter-…f78cg harbor-registry-…rr4d8 \
  --force --grace-period=0
kubectl delete pod -n observability kube-prometheus-stack-kube-state-metrics-…dfpgp --force --grace-period=0
kubectl delete pod -n storage \
  csi-attacher-…msfdv csi-resizer-…gtsf4 longhorn-csi-plugin-h2s8m \
  --force --grace-period=0
```
Reason: pods that were `Error` / `Completed` / `Init:0/1` from before the reboot needed force-replace so DaemonSets / ReplicaSets create fresh pods against the new k8s-1 kubelet/containerd. The `bakery-server` pod had exited cleanly (`exitCode 0` at `2026-05-05T20:27:37Z`) during the reboot's stopAllPods phase but the kubelet didn't restart it (state-loss during reboot); replacing the pod brings the bakery back.

### Public-site recovery confirmed (2026-05-05T20:32Z, post-reboot)

```
$ curl -L https://<public-site-A>/        → 200 OK
$ curl -L https://<public-site-B>/    → 200 OK
$ kubectl get nodes                            → all 3 Ready
```

### Remaining work (in flight, expected to settle within a few minutes)

- 12 pods still in `ContainerCreating` / `CrashLoopBackOff`, mostly Harbor stack recovering (`harbor-core`, `harbor-exporter`, `harbor-jobservice`, `harbor-registry`) and the freshly-recreated DaemonSet pods on k8s-1 (csi-attacher, csi-resizer, longhorn-csi-plugin, instance-manager-…)
- `csgoplant-app-…tk42v` ImagePullBackOff on k8s-2 — waiting on Harbor at `192.168.1.106` to come back so the image pull can complete; the other replica `…55rj4` on k8s-3 is already serving traffic (`<public-site-A>` returns 200)
- `seaweedfs-volume-1` still ContainerCreating after 3 min — needs PVC re-attach; will revisit if it doesn't converge
- Boot-ID watch baseline for k8s-1 is now `65fc58fd-26bb-44fe-91a3-f44eb5d421a5` (the original baseline from the BIOS-flash watch, `374d7bdd…`, is two reboots stale and the loop is no longer running anyway)

### Status @ 2026-05-05T20:32Z: PUBLIC IMPACT MITIGATED

- ✅ `<public-site-B>` 200
- ✅ `<public-site-A>` 200
- ✅ All 3 nodes Ready, etcd 3/3 healthy
- ✅ Tailscale-operator API proxy back, standard `kubectl` works
- ⏳ Harbor + observability stack still re-converging on healthy nodes
- ⏳ One Longhorn volume (`seaweedfs-volume-1`) and one CNPG instance (`csgoplant-postgres-1`) still in late-stage Init — being watched
- ⏳ Postmortem to be authored once cluster is fully steady-state

### Status @ 2026-05-05T20:35Z: STEADY STATE

- ✅ All 3 nodes Ready, etcd 3/3 healthy with k8s-2 leader, all members at same applied index `177230477`
- ✅ `<public-site-B>` 200, `<public-site-A>` 200
- ✅ Harbor full stack 1/1 across the board (core ×2, exporter, postgres ×3, redis ×3, portal ×2, nginx, registry)
- ✅ Longhorn full stack 3/3 nodes (csi-plugin, manager, instance-manager) — all 3 CSINodes registered with `driver.longhorn.io`
- ✅ csgoplant-app-…55rj4 1/1 Running on k8s-3, csgoplant-postgres-1 1/1 Running on k8s-3, csgoplant-dragonfly-0 1/1 Running on k8s-2 — backing the recovered <public-site-A>
- ✅ bakery-server-…hzzzl 1/1 Running on k8s-3 — backing the recovered <public-site-B>
- ⏳ Two pods still finishing their initial Run after force-replace at 20:34Z: `harbor-jobservice-…zn9n4` and `seaweedfs-volume-1` (both ContainerCreating, <30 s old, expected to settle within a minute)

### Recovery summary

| Phase | When | Action | Outcome |
|---|---|---|---|
| Detect | 20:54Z (T+41h) | Bastion watch loop catches boot-ID diff, escalates and stops | ESCALATE entry in plan 0009 Log; PushNotification (suppressed by terminal focus) |
| Triage | 19:55-20:00Z | Generate direct kubeconfig (Tailscale operator pod was a ghost), confirm 3-way etcd health, identify ghost-pod recovery deadlock | Direct kubeconfig at `/tmp/anton-direct-kubeconfig`; root cause classified |
| Mitigate batch 1 | 20:01Z | Force-delete ingress + Tailscale-operator ghost pods | `<public-site-B>` 200 within 60 s; standard `kubectl` works |
| Mitigate batch 2 | 20:05Z | Bulk force-delete of all remaining `Unknown` ghosts | ~50 pods cleared; storage / Harbor / observability stacks begin re-converging |
| Mitigate batch 3 | 20:09Z | Cordon k8s-1 + force-delete pods stuck on k8s-1 to reschedule onto k8s-2/k8s-3 | csgoplant + harbor + seaweedfs StatefulSets escape k8s-1 kubelet wedge; `<public-site-A>` 200 |
| Repair k8s-1 | 20:29Z | Graceful reboot of k8s-1 via `talosctl reboot --mode=default` | New boot ID `65fc58fd…`; kubelet healthy; etcd term unchanged at 32 |
| Mitigate batch 5 | 20:30Z | Uncordon k8s-1, force-replace stale `Error` / `Completed` pods (bakery-server, harbor-core, harbor-exporter, harbor-registry, kube-state-metrics, csi-attacher, csi-resizer, longhorn-csi-plugin) so DaemonSets/ReplicaSets create fresh pods against the new kubelet | Cluster fully recovers |
| Steady state | 20:35Z | Final verification | 2 pods left in ContainerCreating (Harbor jobservice + seaweedfs-volume-1), both freshly recreated; everything else Running |

### Hypothesis update for plan 0009

This incident is a **structural blow** to the BIOS-fix narrative:

1. **k8s-1 silently rebooted for the first time in the entire investigation.** k8s-1 had been the rock since the April 2026 cluster reset (190 days uptime by the node-AGE column). It is on **BIOS 1.26** (untouched by the 2026-05-04 flash). Either 1.26 is also susceptible to the underlying mechanism, or BIOS version is not the determining variable.
2. **Two-node simultaneous reboot, k8s-2 (the historically-fragile node) held cleanly.** This is the *inverse* of every prior silent-reboot incident in plan 0007 / 0009 / 0010. The 04-23 "two-node cascade" was retracted as operator-initiated; **this one is genuinely organic**, demonstrating the cascade pattern does exist.
3. **No kernel-side trace was captured.** The Vector kernel sink was torn down at T+14h post-flash (commit `4037deec`, plan 0007 Phase 5). The trade-off documented in plan 0009 Log entry 2026-05-04 T+14h checkpoint just came due. Going forward the only forensic surface for the next event is Prometheus + the surviving node's ring buffer.
4. **k8s-1 still on BIOS 1.26 with original Mushkin DDR5 config.** Whatever just hit k8s-1 + k8s-3 simultaneously is not k8s-2-chassis-specific.

The original plan 0009 hypothesis ranking (with k8s-2 hardware defect at #1) needs to be re-cut. New leading candidates given today's signature:
- **Cluster-wide trigger** (network event, kernel bug exposed by recent workload, distributed pod-churn cascade) that hits >1 node simultaneously
- **Power glitch / electrical** affecting two of three Mini PCs but not the third (PSU difference? UPS topology?)
- **Concurrent failure that propagated via the data plane** (e.g. a Cilium / BPF event that took k8s-1 + k8s-3's kernel down but k8s-2 absorbed it)

Plan 0009 reopening + a new evidence note to be authored alongside the postmortem.

### Action items pending postmortem

- [ ] Re-stand up Vector kernel sink (or equivalent) so the next event has trace coverage; this was the explicit forensic-surface trade-off documented in plan 0009 Log
- [ ] Decide on plan 0009 status: keep open, reopen with revised scope, or fork a new plan for "dual-node simultaneous silent reboot"
- [ ] Ghost-pod accumulation pattern (Unknown pods 4d15h old surviving on containerd while marked Unknown in API) — file a separate hardening task; this is the second time it has caused a public outage (first was during plan 0007 day-1)
- [ ] Consider an automated cluster-health alert on `kube_pod_status_phase{phase="Unknown"} > 0 for 10m` so we catch ghost accumulation BEFORE the next reboot exposes it
- [ ] Verify the `seaweedfs-volume-1` PVC is properly attached after this final force-delete (pinned to k8s-1 historically — may need to detach / re-attach)
- [ ] Postmortem authoring at `../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`



## References

- Plan 0009 (k8s-2 silent-reboot followup): `../plans/0009-k8s-2-k8s-3-silent-reboot-followup.md`
- Plan 0007 (k8s-2 remote diagnostic rollout — original ghost-pod recovery deadlock pattern documented in day-1 Log): `../plans/0007-k8s-2-remote-diagnostic-rollout.md`
- BIOS-flash evidence (k8s-2 + k8s-3): `../notes/k8s-2-instability/evidence-2026-05-04-bios-1.27-flash.md`
- Postmortem (to be filled in after mitigation): `../postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`
- Direct kubeconfig in use during this incident: `/tmp/anton-direct-kubeconfig` (talosctl kubeconfig, server URL pinned to `https://100.75.61.79:6443`, `--insecure-skip-tls-verify=true` due to Tailscale IP not in cert SAN)
