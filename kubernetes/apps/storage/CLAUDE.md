# kubernetes/apps/storage/

The storage namespace owns Longhorn (replicated block storage CSI, ADR 0005) plus the Multus secondary-network wiring that puts replica + iSCSI traffic on the SFP+ mesh.

## Contents

- `longhorn/` — the chart itself. `defaultSettings.storageNetwork: storage/longhorn-storage` is set here; replica count, data locality, and the metrics ServiceMonitor live alongside.
- `longhorn-config/` — the `NetworkAttachmentDefinition` named `longhorn-storage`. Kept as a sibling Flux app rather than inside `longhorn/` so chart upgrades stay atomic and future `RecurringJob` / `BackingImage` / `BackupTarget` resources have a natural home (same chart-vs-config split as `cert-manager` / `cert-manager-issuers`).

## Storage network — the load-bearing piece

The `longhorn-storage` NAD attaches Longhorn instance-manager pods' `lhnet1` interface to the `vxlan-storage` overlay (provisioned by the `storage-vxlan` DaemonSet under `kubernetes/apps/network/storage-vxlan/`). Plugin is **macvlan / mode bridge**, MTU 8950, IPAM via Whereabouts on `10.100.1.0/24` with `10.100.1.0/28` excluded for per-node host-shim addresses.

**Critical wiring:** the `storage-vxlan` DaemonSet creates a peer macvlan-bridge child of `vxlan-storage` called `lhnet1-host` and migrates the host's per-node 10.100.1.X address onto it. This is what makes Longhorn v1 iSCSI work — the kernel iSCSI initiator runs in the host netns and must reach the IM pod's iSCSI target on `lhnet1`. macvlan-bridge isolates parent↔child but allows child↔child without traversing the parent's egress (which, for a vxlan parent, would encapsulate to remote VTEPs and never reach a same-host pod). Both bare-NAD-on-parent attempts (macvlan and ipvlan L2) failed exactly this gate — see plan 0004 Log 2026-04-19. Don't change the NAD plugin without re-reading that diagnosis first.

## Usage

Use the Longhorn skill pack for operations:

- `longhorn-volume-ops` — per-volume PVC work (create, resize, clone, replica/locality overrides)
- `longhorn-node-ops` — disk add/remove, replica eviction, disk-routing fixes, replaced-node integration
- `longhorn-backup-dr` — backup target wiring, RecurringJobs, restore/DR flows

For new manifests in this namespace, follow the 3-file Flux pattern (`ks.yaml` + `app/kustomization.yaml` + resources). The `longhorn` HelmRelease is the upstream chart (no OCI variant; uses `helmrepository.yaml`); `longhorn-config` is plain raw manifests. Copy the shape of either depending on need.
