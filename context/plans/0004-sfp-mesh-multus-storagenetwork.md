---
status: In-progress
opened: 2026-04-18
closed: null
affects: networking, storage
intent: concrete-need
related-adrs: [0009, 0017]
review-by: null
---

# 0004 — SFP+ mesh + Multus + Longhorn storage network

> Route Longhorn replica traffic onto the 10 Gbit SFP+ full mesh via Multus-provisioned NADs, unlocking the ADR 0009 fabric that is physically cabled but still unused.

## Goal

Longhorn replica traffic flows end-to-end over the three DAC links — not the 2.5 GbE management interface — on all three nodes. The SFP+ fabric (cabled and link-up as of 2026-04-18, per `context/hardware.md`) becomes the load-bearing storage network that ADR 0009 was written to justify. Done means an `iperf3` run between any two mesh peers clears the ≥9 Gbit/s gate and Longhorn's own replica-byte counters (node-exporter `node_network_transmit_bytes_total` on the SFP+ devices) demonstrably move during a volume write.

## Acceptance criteria

- [x] Multus thick-plugin mode deployed under `kubernetes/apps/network/multus/` via the 3-file Flux pattern; Flux `Kustomization` reports `Ready` and the Multus DaemonSet has 3/3 pods Running.
- [x] All three nodes have `/31` static addresses configured on their SFP+ interfaces via Talos `networkInterfaces`, each node reaches every mesh peer over that address, and `talosctl get links` shows `LINK STATE=true` on all 6 ports.
- [x] `iperf3 -P 4` between any two mesh peers (jumbo frames enabled, MTU 9000) achieves **≥9 Gbit/s** sustained.
- [ ] A `NetworkAttachmentDefinition` named `longhorn-storage` exists in the **`storage`** namespace (where the Longhorn HelmRelease actually runs; the original plan said `longhorn-system`, which the 2026-04-19 verification corrected) and Longhorn's `defaultSettings.storageNetwork` is set to `storage/longhorn-storage`.
- [ ] A test Longhorn volume under write load shows SFP+ interface `node_network_transmit_bytes_total` counters moving on the source node, and the `enp87s0` management interface counter stays flat for replica traffic.

## Tasks

### Phase 1 — Multus install (depends on ADR 0017)

- [x] Use `flux-app-author` / `add-flux-app` to scaffold `kubernetes/apps/network/multus/` (3-file pattern: `GitRepository` pointing at `k8snetworkplumbingwg/multus-cni` pinned to a thick-mode release tag, Flux `Kustomization`, and an `app/` overlay rendering `deployments/multus-daemonset-thick.yml`).
- [x] Apply kustomize patches: override namespace to `network` on the DaemonSet, ServiceAccount, ConfigMap, and ClusterRoleBinding subject; pin the image to the matching `ghcr.io/k8snetworkplumbingwg/multus-cni:<tag>-thick`. **Note:** thick-mode ships `multus-daemon-config` with `"multusConfigFile": "auto"`, which auto-discovers Cilium via `/host/etc/cni/net.d`; no explicit `clusterNetwork: cilium` patch is needed (that was a thin-mode concept).
- [x] Commit, `task reconcile`, verify the Flux `Kustomization` reports `Ready` and the Multus DaemonSet has 3/3 pods Running.
- [x] Confirm no Cilium regression — `cilium status` stays green and existing pod networking is unaffected.

### Phase 2 — Talos `/31` rolling config

The per-node `/31` assignments (from the DAC topology discovered 2026-04-18, recorded in `context/hardware.md`):

| DAC | Node A iface | Node A addr | Node B iface | Node B addr |
|---|---|---|---|---|
| DAC #1 | k8s-1 `enp2s0f0np0` | `10.100.0.0/31` | k8s-2 `enp2s0f1np1` | `10.100.0.1/31` |
| DAC #2 | k8s-1 `enp2s0f1np1` | `10.100.0.2/31` | k8s-3 `enp2s0f1np1` | `10.100.0.3/31` |
| DAC #3 | k8s-2 `enp2s0f0np0` | `10.100.0.4/31` | k8s-3 `enp2s0f0np0` | `10.100.0.5/31` |

- [x] Edit `talos/talconfig.yaml` to add the two SFP+ `networkInterfaces` entries on each node (MAC-selector + `/31` address + `mtu: 9000`). Keep `dhcp: false`, no default route (storage-only fabric).
- [x] `task talos:generate-config` and review the diff on each rendered node config.
- [x] Hand off to `talos-operator` to apply rolling, one node at a time: `task talos:apply-node IP=… MODE=auto` with etcd-quorum checks between nodes.
- [x] Verify on each node: `talosctl -n <ip> get addresses` shows the two new `/31` entries; `talosctl -n <ip> get links` shows all 6 SFP+ ports still `LINK STATE=true`.
- [x] Ping across each DAC from each side (6 directions total) to confirm bidirectional reachability.

### Phase 3 — iperf3 baseline (gate: ≥9 Gbit/s)

- [x] Deploy an `iperf3` server + client as short-lived `hostNetwork: true` pods pinned to specific nodes (or run via `talosctl`-accessible debug tooling if available).
- [x] Run `iperf3 -P 4 -t 30` in both directions across each DAC. Record results in the Log.
- [x] **Gate check**: all 6 directions ≥9 Gbit/s sustained with MTU 9000. If any link misses, stop and diagnose (MTU mismatch, flow control, pause frames, CPU IRQ affinity) before proceeding.
- [x] Tear down the iperf3 pods.

### Phase 4 — VXLAN adapter + whereabouts + NetworkAttachmentDefinition

**Scope expanded 2026-04-19** — see the Log entry of the same date. The original Phase 4 was a one-file NAD; reality is that the point-to-point `/31` mesh from Phase 2 has no shared L2 domain, which Longhorn's single-NAD storage-network model requires. The chosen adapter is a **VXLAN overlay** (VNI 100) layered on top of the three `/31` DACs, presenting a shared `10.100.1.0/24` segment that macvlan + whereabouts can consume unchanged. IPAM decision is locked to **whereabouts** (needed for dynamic IM/BIM pod respawns). Failure mode is locked to **fail-hard** for now — single-path per peer, no redundancy, revisit only if Phase 5 reveals a real problem.

Sub-phases land in order; each is independently committed and reconciled.

#### Phase 4a — whereabouts IPAM install

- [ ] Scaffold a new Flux app at `kubernetes/apps/network/whereabouts/` using the same `GitRepository` + Flux inner `Kustomization` + `spec.patches` pattern pioneered for Multus in Phase 1 (no Helm chart ships a thick-mode-equivalent for whereabouts v0.x either). Source: `github.com/k8snetworkplumbingwg/whereabouts`, pinned tag via Renovate `github-releases`. Render `doc/crds/whereabouts.cni.cncf.io_ippools.yaml` + `doc/crds/whereabouts.cni.cncf.io_overlappingrangeipreservations.yaml` + `doc/crds/daemonset-install.yaml`, patching the DaemonSet + ServiceAccount + CRB into the `network` namespace (same namespace move pattern as Multus).
- [ ] Verify post-reconcile: `kubectl get crd | rg whereabouts` shows both CRDs; `kubectl -n network get ds whereabouts` reports 3/3 Running; no Cilium or Multus regression.

#### Phase 4b — per-node VTEP loopbacks + static routes (Talos rolling apply)

- [ ] Edit `talos/talconfig.yaml`: add one `dummy: true` `networkInterfaces` entry per node with a `/32` VTEP address, and add two `routes:` entries on each node's existing SFP+ `/31` interfaces pointing at peer VTEPs. Addressing:
  - k8s-1 VTEP `10.100.100.1/32` on dummy; routes `10.100.100.2/32 via 10.100.0.1` (DAC #1) and `10.100.100.3/32 via 10.100.0.3` (DAC #2).
  - k8s-2 VTEP `10.100.100.2/32`; routes `10.100.100.1/32 via 10.100.0.0` and `10.100.100.3/32 via 10.100.0.5`.
  - k8s-3 VTEP `10.100.100.3/32`; routes `10.100.100.1/32 via 10.100.0.2` and `10.100.100.2/32 via 10.100.0.4`.
- [ ] `task talos:generate-config`, review the rendered diff on each node (expect one `LinkConfig` for the dummy + two `RouteConfig` entries per SFP+ interface).
- [ ] Hand off to `talos-operator` for rolling apply (same pattern as Phase 2). Adding a dummy + routes is additive and should resolve to `MODE=auto` → no-reboot on all three nodes; if it doesn't, STOP and surface.
- [ ] Verify on each node: `talosctl -n <ip> get addresses` shows the `/32` VTEP; `talosctl -n <ip> get routes` shows the two peer-VTEP routes; ping each peer's VTEP from the local VTEP (3 × 2 = 6 pings) via host-network netshoot pods, 0 % loss.

#### Phase 4c — VXLAN overlay DaemonSet

Talos `talconfig.yaml` cannot natively declare a VXLAN interface (no `kind: vxlan` in `machine.network.interfaces` on Talos v1.12). The overlay is provisioned by a small Flux-managed DaemonSet under `kubernetes/apps/network/storage-vxlan/`.

- [ ] Scaffold a new Flux app at `kubernetes/apps/network/storage-vxlan/` (3-file pattern + raw resources — no chart, just a DaemonSet + RBAC + ConfigMap). DaemonSet spec:
  - `hostNetwork: true`, `hostPID: false`, tolerates control-plane taint, pinned one-per-node via the default DaemonSet behavior.
  - Single container, image `nicolaka/netshoot` (or a smaller purpose-built image — TBD during authoring), `securityContext.capabilities.add: [NET_ADMIN]`, no other privileges.
  - Command reads the node name via downward-API env `NODE_NAME`, looks up the per-node VTEP IP and the two peer VTEP IPs in a ConfigMap mounted as env vars (so the same image runs on every node), then executes idempotently:
    ```
    ip link show vxlan-storage || ip link add vxlan-storage type vxlan id 100 \
        local $NODE_VTEP dstport 4789 nolearning
    ip link set vxlan-storage mtu 8950 up
    ip addr replace $NODE_OVERLAY_IP/24 dev vxlan-storage
    bridge fdb replace 00:00:00:00:00:00 dev vxlan-storage dst $PEER1_VTEP self
    bridge fdb append 00:00:00:00:00:00 dev vxlan-storage dst $PEER2_VTEP self
    ```
  - After setup, the container sleeps indefinitely (tail -f /dev/null style) so that `kubectl` / Flux see it as Ready; on restart it re-applies (the `||` + `replace` make it idempotent).
  - Overlay-side addressing: k8s-1 `10.100.1.1/24`, k8s-2 `10.100.1.2/24`, k8s-3 `10.100.1.3/24` on `vxlan-storage`.
  - MTU accounting: underlay 9000 − (VXLAN 8 + UDP 8 + IPv4 20 + Ethernet 14) = 8950 overlay MTU. Set on both the vxlan interface and in the NAD's `mtu` field.
- [ ] Verify post-reconcile: `kubectl -n network get ds storage-vxlan` 3/3 Running; on each node, `nsenter` (or another netshoot pod) confirms `vxlan-storage` interface exists with the expected IP and MTU. Ping `10.100.1.2` and `10.100.1.3` from `10.100.1.1` (and bidirectional from the other two nodes) via host-network pods — expect 0 % loss across the overlay.

#### Phase 4d — NetworkAttachmentDefinition + smoke test

- [ ] Author `kubernetes/apps/storage/longhorn-config/app/networkattachment.yaml` — `NetworkAttachmentDefinition` named `longhorn-storage` in the **`storage`** namespace (NOT `longhorn-system` — plan text corrected today). Spec:
  ```
  type: macvlan, mode: bridge, master: vxlan-storage, mtu: 8950
  ipam: whereabouts, range: 10.100.1.0/24, exclude: 10.100.1.0/28
  ```
  The `/28` exclusion reserves `.1-.3` (the node-side VTEP overlay IPs) plus a small buffer; pods will draw from `.16-.254`.
- [ ] Wire the NAD into `kubernetes/apps/storage/longhorn-config/app/kustomization.yaml` (create the `longhorn-config` app if it doesn't yet exist; if the longhorn HelmRelease app itself is the natural home, prefer adding the NAD as a sibling resource there instead of creating a new app).
- [ ] Commit, `task reconcile`, verify `kubectl -n storage get net-attach-def longhorn-storage` exists.
- [ ] Smoke test: run a netshoot pod with annotation `k8s.v1.cni.cncf.io/networks: longhorn-storage` pinned to k8s-1, and another on k8s-2 with the same annotation. Confirm each pod gets a `10.100.1.x` address via whereabouts, and that pod-to-pod ping across the overlay succeeds. Tear the test pods down.

### Phase 5 — Longhorn storageNetwork + verify

- [ ] Edit the Longhorn `HelmRelease` values at `kubernetes/apps/storage/longhorn/app/helmrelease.yaml` to set `defaultSettings.storageNetwork: storage/longhorn-storage` (namespace corrected from the original `longhorn-system/…`).
- [ ] Drain replica traffic safely: scale the workload causing writes down first (if any), or let Longhorn rebuild replicas under the new network post-setting.
- [ ] Commit, `task reconcile`, wait for Longhorn pods to cycle. Verify `kubectl -n storage get pods -o yaml | rg 'k8s.v1.cni.cncf.io/networks'` shows IM / BIM / replica pods annotated with `storage/longhorn-storage`, and each has a `10.100.1.x` address in its pod status.
- [ ] Create a test PVC + pod that writes ~10 GiB. While the write runs, query `sum by (instance) (rate(node_network_transmit_bytes_total{device=~"enp2s0f.np."}[30s]))` in Prometheus — expect it to light up. Query the same rate for `device="enp87s0"` — expect it to stay near baseline for replica bytes.
- [ ] Record the observed replica throughput in the Log; compare to the Phase 3 iperf3 number. Expect meaningful headroom shrinkage from the 9.76–9.90 Gbit/s raw baseline due to Longhorn protocol overhead *plus* VXLAN encap (~50 B/packet, minor for large replica blocks); should still be well above the 2.5 GbE management-network ceiling.
- [ ] Tear down the test workload.

## Log

- 2026-04-18: Opened from ADR 0017 (Multus adoption) which is itself a follow-up to ADR 0009 (SFP+ mesh). Prerequisites landed earlier today: mesh cabled and link-up on all 6 ports, per-port MAC mapping discovered via ARP-probe + node-exporter RX counter deltas (recorded in `context/hardware.md`), symmetric 2+2+2 Longhorn topology achieved via k8s-2 `longhorn-2` userVolume (plan 0001 follow-up completed).
- 2026-04-18: Phase 1 install mechanism pivoted from `HelmRelease` + OCI HelmRepository to `GitRepository` + Flux `Kustomization` + kustomize overlay. Driver: no usable Helm chart exists for Multus v4 thick-plugin mode (evidence in next entry).
- 2026-04-18: Chart landscape as researched today. (a) Official `k8snetworkplumbingwg/helm-charts/multus` is Chart v0.1.2 / appVersion 0.1.0, image `v3.8` thin-mode only, last meaningful commit 2022; the chart template has no thick-plugin knobs and hardcodes `kube-system`. (b) Bitnami `multus-cni` chart v2.2.22 / appVersion 4.2.2 is OCI-distributed at `oci://registry-1.docker.io/bitnamicharts/multus-cni` but depends on `docker.io/bitnami/multus-cni` which Broadcom paywalled on 2025-08-28 (images moved to `docker.io/bitnamilegacy`, frozen with no CVE fixes unless $50K–$72K/yr BSI subscription); the chart also ships a single-DaemonSet wrapper, not the upstream daemon+shim thick-mode shape. (c) Upstream's supported thick-mode install is `deployments/multus-daemonset-thick.yml` on `k8snetworkplumbingwg/multus-cni`, tagged per release (v4.2.4, Feb 2025). Option chosen: `GitRepository` at that repo + kustomize overlay. Fits anton's 3-file pattern structurally (source + ks + `app/`), keeps Renovate on the git tag.
- 2026-04-18: ADR 0017's body still reads "installed via its official Helm chart" and a follow-up bullet says "OCI HelmRepository + thick-mode values". Those sentences pre-date this research and are factually incorrect. The ADR's **decision** (adopt Multus thick-plugin chained to Cilium, Longhorn sole consumer, under `kubernetes/apps/network/multus/`) is unchanged, so ADR 0017 is not being superseded. This Log entry is the durable correction pointer per the ADR-vs-plan split: ADRs record *why*, plans record *how / what's next*.
- 2026-04-18: Phase 1 scaffolded via `flux-app-author`. Files: `kubernetes/apps/network/multus/{ks.yaml,app/kustomization.yaml,app/gitrepository.yaml,app/flux-kustomization.yaml}`. `GitRepository` pinned to `v4.2.4` with Renovate `github-releases` datasource; image pinned to `ghcr.io/k8snetworkplumbingwg/multus-cni:v4.2.4-thick` (HTTP 200 verified). Inner Flux `Kustomization` `multus-upstream` renders `deployments/multus-daemonset-thick.yml` with four namespace-move patches (DS `kube-multus-ds`, SA `multus`, CM `multus-daemon-config`, CRB `multus` subject[0]). Dual-Kustomization shape is intentional — Flux `Kustomization.spec.patches` is the only way to patch external `GitRepository` content; plain kustomize cannot consume a Flux source. Upstream thick-mode `multus-daemon-config` uses `"multusConfigFile": "auto"` (verified against the v4.2.4 YAML), so the originally planned `clusterNetwork: cilium` patch was dropped as a no-op; auto-discovery picks up Cilium's CNI config at `/host/etc/cni/net.d`. Phase 1 task 2 wording updated to match.
- 2026-04-18: **Blocked.** Running `task configure` after scaffolding surfaced ~34 files of template drift — the Multus registration added to `kubernetes/apps/network/kustomization.yaml` was silently stripped by the template render, and unrelated hand-edits (Cilium `devices: enp+`, resource limits, Hubble relay config, envoy-gateway, cloudflare-tunnel, spegel, talconfig truncation, a re-materialized `echo-two/`) reverted to their template-rendered shape. Root cause: anton was bootstrapped from the onedr0p cluster-template but `task template:tidy` was never run, so `templates/` remains authoritative and any direct edit under `kubernetes/` that isn't mirrored back into `templates/` is overwritten on the next `task configure`. Scaffolding further Flux apps through the current toolchain (which mandates `task configure` per root CLAUDE.md) will keep clobbering hand-edits. **Unblock condition:** (1) run `task template:tidy` to archive the template machinery to `.private/`; (2) update root CLAUDE.md and `.taskfiles/CLAUDE.md` to drop the "always run `task configure` before commit" rule in favour of direct `kubernetes/` edits; (3) re-scaffold Phase 1 Multus files fresh. Until then, pausing all Phase 1–5 execution. Multus design decisions above remain valid and do not need re-deciding post-tidy.
- 2026-04-19: **Unblocked → In-progress.** `task template:tidy` landed, root / .taskfiles / agents / skills / hooks were scrubbed of stale `task configure` and `task template:reset` references, and SOPS round-trip was re-verified. Phase 1 re-scaffolded fresh via `flux-app-author` and committed as `c4d4c937` (`feat(network): scaffold Multus v4.2.4 thick-plugin`). Files: `kubernetes/apps/network/multus/{ks.yaml,app/kustomization.yaml,app/gitrepository.yaml,app/flux-kustomization.yaml}` + registration line in `kubernetes/apps/network/kustomization.yaml`. Post-push `task reconcile` applied revision `c4d4c937`; `flux get ks -n network` reports `multus` Ready=True and `multus-upstream` Ready=True at `v4.2.4@sha1:705a59ea`; `kubectl -n network get ds kube-multus-ds` shows 3/3 Running on k8s-1/2/3; `cilium status` green, 64/64 pods managed by Cilium — no CNI regression. Phase 1 acceptance criterion met. Next: Phase 2 Talos `/31` rolling config.
- 2026-04-19: **Phase 2 complete.** SFP+ `/31` addressing committed as `da63955e` (`feat(talos): add SFP+ /31 networkInterfaces`) — six new `networkInterfaces` entries across the three nodes (k8s-1 a0/a1, k8s-2 b9/b8, k8s-3 a9/a8), mgmt interfaces untouched. `task talos:generate-config` rendered the expected `ethSel1`/`ethSel2` `LinkConfig` blocks per node with `mtu: 9000`. Rolling apply via `talos-operator` — `MODE=auto` resolved to **no-reboot** on all three nodes (purely additive link config, kernel hot-add). Rolled k8s-1 → k8s-2 → k8s-3 with etcd quorum re-verified between each (3/3 healthy throughout). All 6 `/31` addresses present in `talosctl get addresses`; all 6 SFP+ ports `LINK STATE=true`; mgmt `192.168.1.x/24` + VIP `192.168.1.101` on k8s-3 intact. All 6 bidirectional pings succeeded via host-network netshoot pods (talosctl has no remote ping subcommand) — RTT 0.26–0.36 ms across every DAC pair, 0 % loss. Cilium 3/3, nodes Ready, no membership change. Phase 2 acceptance criterion met. Next: Phase 3 `iperf3` baseline (≥9 Gbit/s gate).
- 2026-04-19: **Phase 3 complete.** iperf3 baseline ran against three ephemeral `hostNetwork: true` pods (one per node, `nicolaka/netshoot` image with `iperf3 -s`, pinned via `nodeSelector`). Pre-flight jumbo-frame check (`ping -M do -s 8972`) passed 0 % loss across all six directions, confirming MTU 9000 is end-to-end clean (no path-MTU black hole, no silent fragmentation). Full `iperf3 -c <peer-/31> -B <local-/31> -P 4 -t 30 -f g` results: **DAC #1 k8s-1→k8s-2 9.90 Gbit/s / k8s-2→k8s-1 9.81 Gbit/s; DAC #2 k8s-1→k8s-3 9.90 / k8s-3→k8s-1 9.76; DAC #3 k8s-2→k8s-3 9.90 / k8s-3→k8s-2 9.90.** All six directions clear the ≥9 Gbit/s gate — fabric fully matches ADR 0009's capacity promise. Pattern noted (not blocking): traffic *into* k8s-1 shows elevated TCP retries (DAC #1 rev 346, DAC #2 rev 588) vs the 70–100 range everywhere else; probably IRQ-affinity / RSS-queue asymmetry on the i9-13900H P/E-core split, revisit only if Phase 5 replica bytes expose it as a real ceiling. Pods torn down, manifest at `/tmp/iperf3-phase3.yaml` removed. Phase 3 acceptance criterion met. Next: Phase 4 `NetworkAttachmentDefinition` (IPAM mode TBD — whereabouts preferred for replica-count scalability).
- 2026-04-19: Status confirmed `In-progress` (no-op flip — plan was already In-progress after Phase 1 unblock). Fixed a lingering `longhorn-system` → `storage` reference in the References section. Active sub-phase is **4a — whereabouts install**.
- 2026-04-19: **Phase 4 scope expanded; direction locked.** Interview with operator surfaced two gaps the original Phase 4 glossed over. (a) *Namespace error* — the plan text and Phase 5 all referred to `longhorn-system`, but Longhorn is actually Helm-released into `storage` (verified via `kubectl -n storage get hr longhorn`, chart v1.11.1). Top-level acceptance criterion + Phase 4 + Phase 5 text corrected to use `storage/longhorn-storage`. (b) *Topology-adapter gap* — the three point-to-point `/31` DAC links from Phase 2 are three separate L2 domains, so a single macvlan-on-SFP+ NAD cannot span them (a pod attached via macvlan-on-enp2s0f0np0 on k8s-1 can only reach k8s-2, not k8s-3). No central switch exists (full-mesh DAC cabling). Decision: layer a **VXLAN overlay (VNI 100)** on top of the three `/31`s to present a shared `10.100.1.0/24` segment; NAD is then plain macvlan on `vxlan-storage` with whereabouts IPAM — the pattern Longhorn's docs assume. Alternatives considered and rejected: ipvlan L3 + per-node sub-pools (non-standard, fragments the single-NAD model, requires nodeSliceSize whereabouts config); buying a 10G switch and redoing Phase 2 with a shared `/24` star (invalidates Phases 2+3 work, multi-week hardware lead). **Failure mode deferred** — pick fail-hard (Longhorn rebuilds on DAC failure, same as node failure), revisit after Phase 5 proves the baseline. Phase 4 re-decomposed into 4a (whereabouts install via `GitRepository` + spec.patches pattern), 4b (Talos /32 loopback VTEPs + peer routes via rolling apply), 4c (VXLAN overlay DaemonSet under `kubernetes/apps/network/storage-vxlan/`, since Talos `machine.network.interfaces` doesn't expose a `vxlan` kind), 4d (NAD + smoke test). Talos v1.12 pre-check: whereabouts CRDs not yet installed (confirmed via `kubectl get crd`).

## References

- Related ADRs: 0009 (SFP+ full-mesh fabric), 0017 (Multus adoption)
- Related plans: 0001 (Longhorn adoption — Phase 3 fio baseline established the 2.5 GbE ceiling this plan lifts)
- Hardware inventory: `context/hardware.md` — per-DAC MAC + port mapping and the ARP-probe discovery method
- Talos config: `talos/talconfig.yaml` — where the Phase 2 `networkInterfaces` edits land
- Cluster checks: `kubectl -n storage get net-attach-def`, `talosctl get links`, `talosctl get addresses`
- Multus upstream: https://github.com/k8snetworkplumbingwg/multus-cni
