---
status: Accepted
date: 2026-04-19
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0018 — install-cni init container for Multus reference CNI plugins

> Install the upstream CNI reference plugins (macvlan, ipvlan, vlan, tuning) onto Talos nodes via a `ghcr.io/siderolabs/install-cni` init container on the Multus DaemonSet, per the official Sidero guidance.

## Status

`Accepted`

## Context

ADR 0017 adopted Multus as a meta-CNI chained to Cilium, and plan 0004 Phase 4d landed a `NetworkAttachmentDefinition` named `longhorn-storage` using `type: macvlan, master: vxlan-storage`. The first smoke test on 2026-04-19 failed immediately at CNI ADD with `failed to find plugin "macvlan" in path [/opt/cni/bin]`.

Inventory of what Talos v1.12.6 actually ships in `/opt/cni/bin` (verified via `talosctl list /opt/cni/bin` on k8s-1):

| Source | Plugins present |
|---|---|
| Talos bundled | `bridge`, `cilium-cni`, `firewall`, `flannel`, `host-local`, `loopback`, `passthru`, `portmap` |
| DaemonSet-dropped (plan 0004 Phase 1 / 4a) | `multus-shim` (via Multus thick-mode install container), `whereabouts` (via Whereabouts DS) |
| **Missing** | **`macvlan`**, `ipvlan`, `vlan`, `tuning`, `ptp`, `dhcp`, `sbr`, `vrf`, `bandwidth` |

Three install paths were evaluated on 2026-04-19:

1. **Talos `siderolabs/cni-plugins` system extension** — a declarative factory-schematic add. Chosen first by the original Phase 4d plan. Executed by `talos-operator` and **proven non-viable** at runtime: the factory POST accepted the schematic (it does not validate extension names at create time), but every subsequent installer pull returned HTTP 400 `official extension "siderolabs/cni-plugins" is not available for Talos version v1.12.6`. Cross-checked against `factory.talos.dev/version/v1.12.6/extensions/official` (80+ entries, zero `cni*` match) and `github.com/siderolabs/extensions/tree/release-1.12/network/` (no `cni-plugins` directory). The extension existed in older Talos releases and was removed from the catalog before 1.12; siderolabs has pivoted to letting CNI consumers ship their own plugin binaries via DaemonSets.
2. **Custom in-cluster DaemonSet** unpacking the `containernetworking/plugins` release tarball into `/opt/cni/bin`. Workable and matches the same pattern Multus and Whereabouts already use for their own shims, but DIY — we'd own the plugin version, the tarball fetch, and the copy script.
3. **`ghcr.io/siderolabs/install-cni` init container on the existing Multus DaemonSet**, per the official Sidero documentation at <https://docs.siderolabs.com/kubernetes-guides/cni/multus> ("Cilium does not ship the CNI reference plugins, which most multus setups are expecting (e.g. macvlan)"). The image is Sidero-maintained, pinned to Talos releases, and the doc prescribes this exact init-container shape verbatim. Upstream's `deployments/multus-daemonset-thick.yml` v4.2.4 already ships the `cnibin` hostPath volume the init container mounts.

## Decision

We will add a `ghcr.io/siderolabs/install-cni:v1.7.0` init container to the Multus DaemonSet by extending the existing `spec.patches` list in `kubernetes/apps/network/multus/app/flux-kustomization.yaml`. The init container will mount the Multus-provided `cnibin` hostPath volume with `mountPropagation: Bidirectional` and run `/install-cni.sh`, dropping the reference plugin set into `/opt/cni/bin` on every node. The Renovate annotation on the image string pins version drift to the standard `datasource=docker` cadence. No new Flux app, no Talos-layer change, no reboot.

The authoritative source for this decision and for the init-container shape is <https://docs.siderolabs.com/kubernetes-guides/cni/multus>; any future change to the install-cni pattern tracks that document.

## Alternatives considered

- **Do nothing** — leaves `longhorn-storage` NAD unusable and plan 0004 Phase 4d permanently blocked. Not acceptable; the NAD is the linchpin of the ADR 0009 storage-network promise.
- **Option A — Talos `siderolabs/cni-plugins` system extension** — not in the Talos v1.12.6 factory catalog. Mechanically cannot be used. Rejected on fact.
- **Option B — custom in-cluster DaemonSet** dropping `containernetworking/plugins` tarball binaries — strictly larger footprint than Option C (new DS + manifests + versioning responsibility) with no advantage. Rejected as over-engineered relative to the official Sidero pattern.

## Consequences

### Accepted costs

- **+1 init container** on the existing Multus DaemonSet — runs once per pod start, exits quickly. No long-running footprint.
- **+1 privileged container** — `install-cni` runs as `privileged: true` to write into `/host/opt/cni/bin`. Matches Multus's own `install-multus-binary` init container which is also privileged; scope is bounded to the `/opt/cni/bin` mount.
- **+1 Renovate cadence** — `ghcr.io/siderolabs/install-cni` joins the monthly PR queue under `datasource=docker`.
- **Coupling to the Sidero image's plugin set** — the list of plugins dropped is whatever the `install-cni` image ships. If a future NAD needs a plugin not in that set, the fix lands in a new ADR (not this one).
- **Deprecated-but-maintained** — the Sidero doc labels `install-cni` as deprecated in the narrow sense that Talos v1.8+ bundles the "essential" plugins so most users no longer need it. For users who need `macvlan` (which anton does), the image remains the documented path and there is no alternative being promoted.

### Expected outcome

Plan 0004 Phase 4d smoke test — two netshoot pods on k8s-1 and k8s-2 annotated `k8s.v1.cni.cncf.io/networks: longhorn-storage` — unblocks. Each pod draws a `10.100.1.x` address from the whereabouts pool on its `net1` macvlan interface, and pod-to-pod ping across the VXLAN overlay succeeds at sub-ms RTT (same profile as the Phase 4c host-level baseline).

## Re-adoption guidance

N/A — status is `Accepted`, not `Reverted`.

## Follow-ups

- [ ] Append the init-container patch to `kubernetes/apps/network/multus/app/flux-kustomization.yaml`, commit as `feat(network): …`, reconcile.
- [ ] Verify `macvlan` on all three nodes via `talosctl -n <ip> list /opt/cni/bin`.
- [ ] Re-run the Phase 4d NAD smoke test and tick plan 0004's Phase 4d acceptance boxes.
- [ ] Revisit this decision only if the Sidero doc deprecates `install-cni` in favor of a concrete alternative, or if a future Talos release bundles the full reference plugin set by default (at which point this init container becomes a no-op and can be removed).
