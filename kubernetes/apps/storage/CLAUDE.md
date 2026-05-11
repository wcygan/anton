# kubernetes/apps/storage/

The storage namespace owns Longhorn (replicated block storage CSI, ADR 0005) plus the Multus secondary-network wiring that puts replica + iSCSI traffic on the SFP+ mesh, and SeaweedFS (internal-only S3 object storage, ADR 0019) layered on top of Longhorn PVCs.

## Contents

- `longhorn/` — the chart itself. `defaultSettings.storageNetwork: storage/longhorn-storage` is set here; replica count, data locality, and the metrics ServiceMonitor live alongside.
- `longhorn-config/` — the `NetworkAttachmentDefinition` named `longhorn-storage`. Kept as a sibling Flux app rather than inside `longhorn/` so chart upgrades stay atomic and future `RecurringJob` / `BackingImage` / `BackupTarget` resources have a natural home (same chart-vs-config split as `cert-manager` / `cert-manager-issuers`).
- `seaweedfs/` — the seaweedfs-operator HelmRelease (chart 0.1.14 / app 1.0.12), its `HelmRepository` (upstream does not publish an OCI chart), and `rbac-supplement.yaml` — a supplemental ClusterRole + binding that grants the operator SA `apps/deployments` and `monitoring.coreos.com/servicemonitors`, both missing from chart 0.1.14's bundled `manager-role`. Same chart-only shape as `longhorn/`.
- `seaweedfs-config/` — the `Seaweed` CR (master 3, volume 3 one-per-node via `spec.volume.affinity.podAntiAffinity`, filer 2, standalone S3 Deployment 2, `spec.s3.iam: false`, `master.defaultReplication: "000"` because Longhorn owns durability), an `ExternalSecret` pulling admin S3 creds from 1Password vault `anton` / item `seaweedfs-harbor`, and the `envoy-internal/https` HTTPRoute at `s3.${SECRET_DOMAIN}`. `ks.yaml` carries `dependsOn: [{name: seaweedfs}]` + `wait: true` so the CR never races the CRD / operator / webhook-cert.

## Storage network — the load-bearing piece

The `longhorn-storage` NAD attaches Longhorn instance-manager pods' `lhnet1` interface to the `vxlan-storage` overlay (provisioned by the `storage-vxlan` DaemonSet under `kubernetes/apps/network/storage-vxlan/`). Plugin is **macvlan / mode bridge**, MTU 8950, IPAM via Whereabouts on `10.100.1.0/24` with `10.100.1.0/28` excluded for per-node host-shim addresses.

**Critical wiring:** the `storage-vxlan` DaemonSet creates a peer macvlan-bridge child of `vxlan-storage` called `lhnet1-host` and migrates the host's per-node 10.100.1.X address onto it. This is what makes Longhorn v1 iSCSI work — the kernel iSCSI initiator runs in the host netns and must reach the IM pod's iSCSI target on `lhnet1`. macvlan-bridge isolates parent↔child but allows child↔child without traversing the parent's egress (which, for a vxlan parent, would encapsulate to remote VTEPs and never reach a same-host pod). Both bare-NAD-on-parent attempts (macvlan and ipvlan L2) failed exactly this gate — see plan 0004 Log 2026-04-19. Don't change the NAD plugin without re-reading that diagnosis first.

## SeaweedFS S3 — endpoint shape and the chart-bug tax

**Endpoint:** in-cluster consumers (future Harbor) target `http://seaweedfs-s3.storage.svc.cluster.local:8333` — plain HTTP, no envoy hop, no TLS cost. Off-cluster clients on the LAN hit `https://s3.${SECRET_DOMAIN}` via `envoy-internal`. Internal-only per ADR 0019; no Cloudflare tunnel, no `envoy-external`. Admin creds are assembled by ESO from 1Password `seaweedfs-harbor` into the `seaweedfs-s3-config` Secret's `s3.json` (SeaweedFS `identities[]` shape); the operator mounts that and invokes `weed s3 -config=/etc/sw/s3.json`. AWS S3 clients cannot follow 80→443 redirects (SigV4 dies on redirect) — target `https://` directly.

**Three chart-0.1.14-era bugs we ship workarounds for**, all documented in `docs/docs/notes/seaweedfs-baseline-2026-04-19.md`. Don't touch any without reading the note first:

- `rbac-supplement.yaml` grants `apps/deployments` + `monitoring.coreos.com/servicemonitors` — both missing from the chart's `manager-role` despite the controller needing them (PR #200 shipped without regenerating helm RBAC; SM reflector runs unconditionally). **Remove only when chart ≥ 0.1.15 has both rules in `deploy/helm/templates/rbac/role.yaml`** — verify via `helm pull` + grep before deleting. The supplement is its own ClusterRole rather than an in-place patch so helm 4 SSA doesn't fight it on every HelmRelease reconcile.
- The CRD does not expose `topologySpreadConstraints` on any component. Use `spec.<component>.affinity.podAntiAffinity` with the operator's pod labels (`app.kubernetes.io/name=seaweedfs`, `/component=<master|volume|filer|s3>`, `/instance=<cr-name>`) instead. Labels verified from `controller_volume.go::labelsForVolumeServer` at tag 1.0.12.
- Spurious `VolumeClaimTemplatesMismatch` Warning event on chart < 0.1.19 — upstream [issue #224](https://github.com/seaweedfs/seaweedfs-operator/issues/224) / fix [PR #226](https://github.com/seaweedfs/seaweedfs-operator/pull/226). Operator's desired VCT has `volumeMode: nil`; apiserver defaults it to `Filesystem` on Create; `Semantic.DeepEqual` reports drift every reconcile. **Cluster-side delete-and-recreate does NOT help** — the apiserver re-defaults on every Create. Fix is the chart bump (Renovate ships it; verify the merge unsticks the warning). Baseline note §6 has the full diagnosis.

**Don't revert to `FilerSpec.S3`.** ADR 0019 supersedes 0016; canonical path is top-level `spec.s3` (standalone Deployment). The validating webhook rejects CRs setting both `spec.s3` and `filer.s3.enabled` with `vseaweed.kb.io`.

## Usage

Use the Longhorn skill pack for block-storage operations:

- `longhorn-volume-ops` — per-volume PVC work (create, resize, clone, replica/locality overrides)
- `longhorn-node-ops` — disk add/remove, replica eviction, disk-routing fixes, replaced-node integration
- `longhorn-backup-dr` — backup target wiring, RecurringJobs, restore/DR flows

Use the `seaweedfs-docs` skill for upstream SeaweedFS / operator questions (architecture, `weed shell`, S3 API coverage, CRD schema, release triage). Anton-specific consumption — endpoint URLs, credential retrieval, smoke test, chart-bug workarounds — lives in `docs/docs/notes/seaweedfs-baseline-2026-04-19.md`.

For new manifests in this namespace, follow the 3-file Flux pattern (`ks.yaml` + `app/kustomization.yaml` + resources). Longhorn and SeaweedFS both use `helmrepository.yaml` (no OCI charts upstream); config siblings (`longhorn-config`, `seaweedfs-config`) are plain raw manifests. Copy the shape of either depending on need.
