---
status: Blocked
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

- [ ] Multus thick-plugin mode deployed under `kubernetes/apps/network/multus/` via the 3-file Flux pattern; Flux `Kustomization` reports `Ready` and the Multus DaemonSet has 3/3 pods Running.
- [ ] All three nodes have `/31` static addresses configured on their SFP+ interfaces via Talos `networkInterfaces`, each node reaches every mesh peer over that address, and `talosctl get links` shows `LINK STATE=true` on all 6 ports.
- [ ] `iperf3 -P 4` between any two mesh peers (jumbo frames enabled, MTU 9000) achieves **≥9 Gbit/s** sustained.
- [ ] A `NetworkAttachmentDefinition` named `longhorn-storage` exists in the `longhorn-system` namespace and Longhorn's `defaultSettings.storageNetwork` references it.
- [ ] A test Longhorn volume under write load shows SFP+ interface `node_network_transmit_bytes_total` counters moving on the source node, and the `enp87s0` management interface counter stays flat for replica traffic.

## Tasks

### Phase 1 — Multus install (depends on ADR 0017)

- [ ] Use `flux-app-author` / `add-flux-app` to scaffold `kubernetes/apps/network/multus/` (3-file pattern: `GitRepository` pointing at `k8snetworkplumbingwg/multus-cni` pinned to a thick-mode release tag, Flux `Kustomization`, and an `app/` overlay rendering `deployments/multus-daemonset-thick.yml`).
- [ ] Apply kustomize patches: override namespace to `network` on the DaemonSet, ServiceAccount, ConfigMap, and ClusterRoleBinding subject; pin the image to the matching `ghcr.io/k8snetworkplumbingwg/multus-cni:<tag>-thick`. **Note:** thick-mode ships `multus-daemon-config` with `"multusConfigFile": "auto"`, which auto-discovers Cilium via `/host/etc/cni/net.d`; no explicit `clusterNetwork: cilium` patch is needed (that was a thin-mode concept).
- [ ] Commit, `task reconcile`, verify the Flux `Kustomization` reports `Ready` and the Multus DaemonSet has 3/3 pods Running.
- [ ] Confirm no Cilium regression — `cilium status` stays green and existing pod networking is unaffected.

### Phase 2 — Talos `/31` rolling config

The per-node `/31` assignments (from the DAC topology discovered 2026-04-18, recorded in `context/hardware.md`):

| DAC | Node A iface | Node A addr | Node B iface | Node B addr |
|---|---|---|---|---|
| DAC #1 | k8s-1 `enp2s0f0np0` | `10.100.0.0/31` | k8s-2 `enp2s0f1np1` | `10.100.0.1/31` |
| DAC #2 | k8s-1 `enp2s0f1np1` | `10.100.0.2/31` | k8s-3 `enp2s0f1np1` | `10.100.0.3/31` |
| DAC #3 | k8s-2 `enp2s0f0np0` | `10.100.0.4/31` | k8s-3 `enp2s0f0np0` | `10.100.0.5/31` |

- [ ] Edit `talos/talconfig.yaml` to add the two SFP+ `networkInterfaces` entries on each node (MAC-selector + `/31` address + `mtu: 9000`). Keep `dhcp: false`, no default route (storage-only fabric).
- [ ] `task talos:generate-config` and review the diff on each rendered node config.
- [ ] Hand off to `talos-operator` to apply rolling, one node at a time: `task talos:apply-node IP=… MODE=auto` with etcd-quorum checks between nodes.
- [ ] Verify on each node: `talosctl -n <ip> get addresses` shows the two new `/31` entries; `talosctl -n <ip> get links` shows all 6 SFP+ ports still `LINK STATE=true`.
- [ ] Ping across each DAC from each side (6 directions total) to confirm bidirectional reachability.

### Phase 3 — iperf3 baseline (gate: ≥9 Gbit/s)

- [ ] Deploy an `iperf3` server + client as short-lived `hostNetwork: true` pods pinned to specific nodes (or run via `talosctl`-accessible debug tooling if available).
- [ ] Run `iperf3 -P 4 -t 30` in both directions across each DAC. Record results in the Log.
- [ ] **Gate check**: all 6 directions ≥9 Gbit/s sustained with MTU 9000. If any link misses, stop and diagnose (MTU mismatch, flow control, pause frames, CPU IRQ affinity) before proceeding.
- [ ] Tear down the iperf3 pods.

### Phase 4 — NetworkAttachmentDefinition

- [ ] Author `kubernetes/apps/storage/longhorn-config/app/networkattachment.yaml` — `NetworkAttachmentDefinition` named `longhorn-storage` in the `longhorn-system` namespace, CNI type `macvlan` (or `ipvlan`, TBD from Multus + Cilium interaction testing) on the SFP+ device.
- [ ] Choose IPAM mode: static per-node via `whereabouts` ranged on `10.100.0.0/29`, **or** host-device passthrough. Decide and log. Prefer whereabouts for replica-count scalability.
- [ ] Add the NAD to the relevant `app/kustomization.yaml`, commit, `task reconcile`, verify the NAD exists via `kubectl -n longhorn-system get net-attach-def`.

### Phase 5 — Longhorn storageNetwork + verify

- [ ] Edit the Longhorn `HelmRelease` to set `defaultSettings.storageNetwork: longhorn-system/longhorn-storage`.
- [ ] Drain replica traffic safely: scale the workload causing writes down first (if any), or let Longhorn rebuild replicas under the new network post-setting.
- [ ] Commit, `task reconcile`, wait for Longhorn pods to cycle.
- [ ] Create a test PVC + pod that writes ~10 GiB. While the write runs, query `sum by (instance) (rate(node_network_transmit_bytes_total{device=~"enp2s0f.np."}[30s]))` in Prometheus — expect it to light up. Query the same rate for `device="enp87s0"` — expect it to stay near baseline for replica bytes.
- [ ] Record the observed replica throughput in the Log; compare to the Phase 3 iperf3 number (Longhorn will be meaningfully below raw due to protocol overhead, but should be well above the 2.5 GbE ceiling).
- [ ] Tear down the test workload.

## Log

- 2026-04-18: Opened from ADR 0017 (Multus adoption) which is itself a follow-up to ADR 0009 (SFP+ mesh). Prerequisites landed earlier today: mesh cabled and link-up on all 6 ports, per-port MAC mapping discovered via ARP-probe + node-exporter RX counter deltas (recorded in `context/hardware.md`), symmetric 2+2+2 Longhorn topology achieved via k8s-2 `longhorn-2` userVolume (plan 0001 follow-up completed).
- 2026-04-18: Phase 1 install mechanism pivoted from `HelmRelease` + OCI HelmRepository to `GitRepository` + Flux `Kustomization` + kustomize overlay. Driver: no usable Helm chart exists for Multus v4 thick-plugin mode (evidence in next entry).
- 2026-04-18: Chart landscape as researched today. (a) Official `k8snetworkplumbingwg/helm-charts/multus` is Chart v0.1.2 / appVersion 0.1.0, image `v3.8` thin-mode only, last meaningful commit 2022; the chart template has no thick-plugin knobs and hardcodes `kube-system`. (b) Bitnami `multus-cni` chart v2.2.22 / appVersion 4.2.2 is OCI-distributed at `oci://registry-1.docker.io/bitnamicharts/multus-cni` but depends on `docker.io/bitnami/multus-cni` which Broadcom paywalled on 2025-08-28 (images moved to `docker.io/bitnamilegacy`, frozen with no CVE fixes unless $50K–$72K/yr BSI subscription); the chart also ships a single-DaemonSet wrapper, not the upstream daemon+shim thick-mode shape. (c) Upstream's supported thick-mode install is `deployments/multus-daemonset-thick.yml` on `k8snetworkplumbingwg/multus-cni`, tagged per release (v4.2.4, Feb 2025). Option chosen: `GitRepository` at that repo + kustomize overlay. Fits anton's 3-file pattern structurally (source + ks + `app/`), keeps Renovate on the git tag.
- 2026-04-18: ADR 0017's body still reads "installed via its official Helm chart" and a follow-up bullet says "OCI HelmRepository + thick-mode values". Those sentences pre-date this research and are factually incorrect. The ADR's **decision** (adopt Multus thick-plugin chained to Cilium, Longhorn sole consumer, under `kubernetes/apps/network/multus/`) is unchanged, so ADR 0017 is not being superseded. This Log entry is the durable correction pointer per the ADR-vs-plan split: ADRs record *why*, plans record *how / what's next*.
- 2026-04-18: Phase 1 scaffolded via `flux-app-author`. Files: `kubernetes/apps/network/multus/{ks.yaml,app/kustomization.yaml,app/gitrepository.yaml,app/flux-kustomization.yaml}`. `GitRepository` pinned to `v4.2.4` with Renovate `github-releases` datasource; image pinned to `ghcr.io/k8snetworkplumbingwg/multus-cni:v4.2.4-thick` (HTTP 200 verified). Inner Flux `Kustomization` `multus-upstream` renders `deployments/multus-daemonset-thick.yml` with four namespace-move patches (DS `kube-multus-ds`, SA `multus`, CM `multus-daemon-config`, CRB `multus` subject[0]). Dual-Kustomization shape is intentional — Flux `Kustomization.spec.patches` is the only way to patch external `GitRepository` content; plain kustomize cannot consume a Flux source. Upstream thick-mode `multus-daemon-config` uses `"multusConfigFile": "auto"` (verified against the v4.2.4 YAML), so the originally planned `clusterNetwork: cilium` patch was dropped as a no-op; auto-discovery picks up Cilium's CNI config at `/host/etc/cni/net.d`. Phase 1 task 2 wording updated to match.
- 2026-04-18: **Blocked.** Running `task configure` after scaffolding surfaced ~34 files of template drift — the Multus registration added to `kubernetes/apps/network/kustomization.yaml` was silently stripped by the template render, and unrelated hand-edits (Cilium `devices: enp+`, resource limits, Hubble relay config, envoy-gateway, cloudflare-tunnel, spegel, talconfig truncation, a re-materialized `echo-two/`) reverted to their template-rendered shape. Root cause: anton was bootstrapped from the onedr0p cluster-template but `task template:tidy` was never run, so `templates/` remains authoritative and any direct edit under `kubernetes/` that isn't mirrored back into `templates/` is overwritten on the next `task configure`. Scaffolding further Flux apps through the current toolchain (which mandates `task configure` per root CLAUDE.md) will keep clobbering hand-edits. **Unblock condition:** (1) run `task template:tidy` to archive the template machinery to `.private/`; (2) update root CLAUDE.md and `.taskfiles/CLAUDE.md` to drop the "always run `task configure` before commit" rule in favour of direct `kubernetes/` edits; (3) re-scaffold Phase 1 Multus files fresh. Until then, pausing all Phase 1–5 execution. Multus design decisions above remain valid and do not need re-deciding post-tidy.

## References

- Related ADRs: 0009 (SFP+ full-mesh fabric), 0017 (Multus adoption)
- Related plans: 0001 (Longhorn adoption — Phase 3 fio baseline established the 2.5 GbE ceiling this plan lifts)
- Hardware inventory: `context/hardware.md` — per-DAC MAC + port mapping and the ARP-probe discovery method
- Talos config: `talos/talconfig.yaml` — where the Phase 2 `networkInterfaces` edits land
- Cluster checks: `kubectl -n longhorn-system get net-attach-def`, `talosctl get links`, `talosctl get addresses`
- Multus upstream: https://github.com/k8snetworkplumbingwg/multus-cni
