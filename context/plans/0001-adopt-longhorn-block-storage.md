---
status: In-progress
opened: 2026-04-16
closed: null
affects: storage
intent: concrete-need
related-adrs: [0004, 0005, 0007, 0009]
review-by: null
---

# 0001 — Adopt Longhorn as replicated block storage

> Execute ADR 0005 — install Longhorn on 2.5 GbE with an asymmetric 2+1+2 disk layout, ending at a smoke-tested `longhorn` default StorageClass that clears ADR 0007's install gate.

## Goal

Bring Longhorn online as the cluster's default block CSI per ADR 0005, with 2-replica + `dataLocality: best-effort` backed by the 5× 1 TB SSDs currently installed (k8s-1: 2, k8s-2: 1, k8s-3: 2). Install runs on the existing 2.5 GbE network; ADR 0009's 10 Gbit SFP+ mesh and the Multus / `storageNetwork` binding are explicitly out of scope for this plan and tracked against a future sibling plan. Plan closes when smoke tests pass and the `longhorn` StorageClass is claimable cluster-wide — formally clearing ADR 0007's install gate so the kube-prometheus-stack rollout can begin as plan 0002.

## Acceptance criteria

- [ ] `longhorn` StorageClass is the cluster default, with `numberOfReplicas: 2` and `dataLocality: best-effort`
- [ ] All three nodes reinstalled with `iscsi-tools` + `util-linux-tools` system extensions and declared Longhorn disks mounted
- [ ] Smoke test — scratch-namespace PVC, write/read, controlled node reboot with replica failover — captured as baseline in `docs/`
- [ ] Asymmetric 2+1+2 topology documented in `context/hardware.md` with the 6th-drive-followup tracked
- [ ] ADR 0007's install gate cleared — kps rollout plan can open

## Tasks

### Phase 1 — Talos image rebuild + rolling reinstall

- [ ] Re-verify upstream Longhorn status at install time — known issues longhorn#10181, longhorn#10429, siderolabs/talos#11740 per ADR 0005
- [ ] Generate the factory.talos.dev installer image URL with `siderolabs/iscsi-tools` + `siderolabs/util-linux-tools` extensions for the current pinned Talos version
- [ ] Update `talenv.yaml` with the new installer image URL
- [ ] Declare the 5× 1 TB SSDs in `talconfig.yaml` (2 on k8s-1, 1 on k8s-2, 2 on k8s-3) via `hardwareAddr`/serial selectors drawn from `context/hardware.md`; mount at `/var/mnt/longhorn/disk1` and `/var/mnt/longhorn/disk2` (omit `disk2` on k8s-2)
- [ ] Add kubelet `extraMount` for `/var/lib/longhorn` with `rshared` propagation per Longhorn Talos docs
- [ ] `task configure` → commit → push
- [ ] Hand off to the `talos-operator` subagent for rolling reinstall, one node at a time, etcd-quorum-gated
- [ ] Verify each node rejoins the cluster and `talosctl get disks` shows the declared Longhorn disks mounted before proceeding to the next node

### Phase 2 — Flux app scaffold + install

- [ ] Hand off to the `flux-app-author` subagent for the 3-file pattern under `kubernetes/apps/storage/longhorn/`
- [ ] Pin Helm chart to current stable at scaffold time — ADR 0005 framework is not locked to a specific patch; re-verify against upstream
- [ ] HelmRelease values: `defaultSettings.defaultReplicaCount: 2`, `defaultDataLocality: best-effort`, `staleReplicaTimeout: 2880`
- [ ] Disable `preUpgradeChecker` job per the Andrei Vasiliu Talos + Longhorn writeup (known Talos friction)
- [ ] Declare `longhorn` as the cluster default StorageClass
- [ ] Note the interim asymmetric topology (2+1+2) in the scaffold PR description with a pointer to this plan
- [ ] Update `context/hardware.md` — record current 2+1+2 topology, flag k8s-2's missing 2nd NVMe as a tracked-for-later item, not a blocker
- [ ] Run `conventions-linter` on the manifests before commit

### Phase 3 — Smoke test + baseline

- [ ] Create a scratch namespace with a throwaway PVC on the `longhorn` StorageClass
- [ ] Run write/read from a test pod; verify replicas materialise on 2 of 3 nodes via the Longhorn UI
- [ ] Controlled reboot of a non-quorum-critical node; capture replica failover timing
- [ ] Capture baseline rebuild throughput on 2.5 GbE — this is the reference measurement the future ADR 0009 cutover must improve against
- [ ] Document smoke test results + 2.5 GbE baseline throughput under `docs/`
- [ ] Close this plan; open plan 0002 for the kps rollout

## Log

- 2026-04-16: Plan opened — k8s-2 reboot storm RCA'd to Talos 1.12.6 (see memory `project_k8s-2_reboot_rca.md`), unblocking ADR 0005. Chose move-fast path: install on 2.5 GbE, defer ADR 0009 SFP+ bundling to a future sibling plan. Committed to asymmetric 2+1+2 install since operator is not onsite and k8s-2's 2nd NVMe slot cannot be reseated remotely. Scope boundary ends at Longhorn green + smoke test; kps rollout will be plan 0002.
- 2026-04-16: Version gap flagged — ADR 0005 cites v1.8.x but user referenced Longhorn 1.11.1 docs. No conflict: ADR 0005 explicitly defers patch selection to scaffold time. Re-verify upstream status and pin to then-current stable when Phase 2 starts.

## References

- Related ADRs: 0004 (storage framework), 0005 (Longhorn decision), 0007 (kps — the install-gate consumer), 0009 (SFP+ mesh — future sibling plan covers Multus + `storageNetwork`)
- Longhorn Talos support docs: https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/
- Hardware inventory: `context/hardware.md`
- Known upstream issues (per ADR 0005): longhorn/longhorn#10181, longhorn/longhorn#10429, siderolabs/talos#11740
- Flux kustomization (post-scaffold): `storage/longhorn`
- Cluster checks (post-install): `kubectl get sc`, `kubectl get hr -n storage`, `kubectl get nodes.longhorn.io -n longhorn-system`
- Subagent handoffs: `talos-operator` (Phase 1), `flux-app-author` (Phase 2), `conventions-linter` (Phase 2 pre-commit)
