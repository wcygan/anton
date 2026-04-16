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
- [ ] All three nodes reinstalled on the **same Talos version as baseline**, with the **pre-existing extension set preserved**, plus `iscsi-tools` + `util-linux-tools` added (strictly additive, no substitutions, no drive-by Talos bump), and declared Longhorn disks mounted
- [ ] Smoke test — scratch-namespace PVC, write/read, controlled node reboot with replica failover — captured as baseline in `docs/`
- [ ] Asymmetric 2+1+2 topology documented in `context/hardware.md` with the 6th-drive-followup tracked
- [ ] ADR 0007's install gate cleared — kps rollout plan can open

## Tasks

### Phase 1 — Talos image rebuild + rolling reinstall

> **Authoritative reference for all Phase 1 Talos-specific steps**: [Longhorn 1.11.1 — Talos Linux Support](https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/). Every extension, mount, and kubelet tweak below derives from this page — cross-check against it before applying, since Longhorn ships Talos-specific changes release-to-release.

> **Do-no-harm constraint**: the new installer image must be **strictly additive** — same Talos version, every pre-existing system extension preserved, plus `iscsi-tools` and `util-linux-tools`. Never drop an existing extension during the schematic rebuild, and do **not** bundle a drive-by Talos version bump into this change (Talos upgrades are a separate lifecycle owned by the `upgrade-talos-or-k8s` skill). Record the before/after schematic IDs in the Log so any regression is traceable. Talos references: [System Extensions guide](https://docs.siderolabs.com/talos/v1.12/build-and-extend-talos/custom-images-and-development/system-extensions), [Image Factory docs](https://docs.siderolabs.com/talos/v1.12/learn-more/image-factory).

- [x] Re-verify upstream Longhorn status at install time — known issues longhorn#10181, longhorn#10429, siderolabs/talos#11740 per ADR 0005
- [x] **Preflight — capture baseline**: record the current Talos version (from `talenv.yaml`) and the current factory schematic ID in the Log. On each node, run `talosctl --nodes <ip> get extensions` and list every extension currently installed. This is the baseline the new image must preserve.
- [x] **Preflight — compute target schematic**: target schematic = baseline extensions ∪ {`siderolabs/iscsi-tools`, `siderolabs/util-linux-tools`}, **same Talos version** (no drive-by upgrade). Submit to factory.talos.dev; record the new schematic ID in the Log next to the baseline ID. Per-extension sources: [iscsi-tools](https://github.com/siderolabs/extensions/tree/main/storage/iscsi-tools), [util-linux-tools](https://github.com/siderolabs/extensions/tree/main/tools/util-linux).
- [x] Update `talenv.yaml` with the new installer image URL built from the target schematic ID
- [x] Declare the 5× 1 TB SSDs in `talconfig.yaml` (2 on k8s-1, 1 on k8s-2, 2 on k8s-3) via `hardwareAddr`/serial selectors drawn from `context/hardware.md`; mount at `/var/mnt/longhorn/disk1` and `/var/mnt/longhorn/disk2` (omit `disk2` on k8s-2) — *landed as per-node `userVolumes` with CEL `disk.serial` selectors; mount paths are `/var/mnt/longhorn-1` and `/var/mnt/longhorn-2` due to Talos `UserVolumeConfig`'s flat `/var/mnt/<name>` convention (see Log)*
- [x] Add kubelet `extraMount` for `/var/lib/longhorn` with `rshared` propagation per the [Longhorn Talos docs → Machine Config](https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/) — *landed as per-node inline `patches:` binding each `/var/mnt/longhorn-N` with `[bind, rshared, rw]` (doc-accurate path; plan's `/var/lib/longhorn` wording was a typo — see Log)*
- [ ] `task configure` → commit → push
- [ ] Hand off to the `talos-operator` subagent for rolling reinstall, one node at a time, etcd-quorum-gated
- [ ] **Post-node verification** (gate before touching the next node): (a) Talos version matches baseline, (b) every baseline extension still present in `talosctl get extensions`, (c) `iscsi-tools` + `util-linux-tools` present, (d) `talosctl get disks` shows the declared Longhorn disks. Any regression → stop, diagnose, and roll back that node before proceeding to the next one.

### Phase 2 — Flux app scaffold + install

- [ ] Hand off to the `flux-app-author` subagent for the 3-file pattern under `kubernetes/apps/storage/longhorn/`
- [ ] Pin Helm chart to current stable at scaffold time — ADR 0005 framework is not locked to a specific patch; re-verify against upstream
- [ ] HelmRelease values: `defaultSettings.defaultReplicaCount: 2`, `defaultDataLocality: best-effort`, `staleReplicaTimeout: 2880`
- [ ] Disable `preUpgradeChecker` job per the Andrei Vasiliu Talos + Longhorn writeup (known Talos friction; cross-check against the [Longhorn 1.11.1 Talos docs](https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/) for any version-specific Helm values)
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
- 2026-04-16: Longhorn 1.11.1 Talos support docs pinned as the authoritative Phase 1 reference — `https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/`. Every Talos-specific step cross-checks against this page.
- 2026-04-16: Do-no-harm constraint added to Phase 1 — strictly additive schematic rebuild: same Talos version, preserve every pre-existing extension, add only `iscsi-tools` + `util-linux-tools`. Enforced by a preflight pair (capture baseline → compute target schematic) and a post-node verification gate. Sidero references pinned: System Extensions guide, Image Factory docs, and the two extension sources on GitHub.
- 2026-04-16: Phase 1 Task 1 done — upstream triage. All three ADR 0005 blockers are **CLOSED** upstream: longhorn/longhorn#10181 (closed 2025-01-13, v1.7→1.8 upgrade backup error), longhorn/longhorn#10429 (closed 2025-02-18, v1.8.0 upgrade from v1.7.1), siderolabs/talos#11740 (closed 2025-11-05, `ext-iscsid` healthcheck / missing `iscsid.conf`). No active blocker against Phase 1 install.
- 2026-04-16: Phase 1 Task 2 done — baseline captured. Talos version **v1.12.6** (`talos/talenv.yaml`). Current factory schematic ID **`08086db1d88ea52b2e873f0b0c64562af7ae98f6ed83da5ee478871bbe52abd6`** (pinned in all three `talosImageURL` entries in `talos/talconfig.yaml`). Per-node `talosctl get extensions` on k8s-1/k8s-2/k8s-3 all identical — extension set: `{siderolabs/i915 @ 20260309-v1.12.6, siderolabs/intel-ucode @ 20260227, siderolabs/tailscale @ 1.94.2}`, kernel `6.18.18-talos`. This is the set the new image must preserve unchanged.
- 2026-04-16: Phase 1 Task 3 done — target schematic computed. Posted to factory.talos.dev with baseline ∪ {`siderolabs/iscsi-tools`, `siderolabs/util-linux-tools`}, **same Talos v1.12.6, no version bump**. Target schematic ID **`445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece`**. Target installer URL: `factory.talos.dev/installer/445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece`. Schematic diff: +2 extensions, 0 removed, 0 version changes — strictly additive as the do-no-harm constraint requires.
- 2026-04-16: Phase 1 Task 4 done — installer image URL bumped. Edited `talos/talconfig.yaml` (not `talenv.yaml` — the URL lives in `talconfig.yaml` per-node `talosImageURL`; `talenv.yaml` only holds `talosVersion` / `kubernetesVersion`). All three node entries now pin `factory.talos.dev/installer/445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece`. `talosVersion: v1.12.6` in `talenv.yaml` is unchanged. File validated with `mise exec -- yq eval` (the in-repo `validate_yaml.py` hook emits a false positive on this path — known bug, memory `project_validate_yaml_hook_bug.md`). Disk declarations (task 5) and kubelet `extraMount` patch (task 6) not yet applied — deferring to next tick for deliberate review of asymmetric 2+1+2 topology.
- 2026-04-16: Disk inventory verified live via `talosctl get disks` — matches `context/hardware.md`: k8s-1 has WD_BLACK serials `251021802186` + `251021802190`; k8s-2 has `251021802221` only (2nd slot absent, as flagged in hardware.md); k8s-3 has `251021800405` + `251021801882`. Serials are ready to drop into `machineDisks` selectors when task 5 lands.
- 2026-04-16: Task 5/6 design research — open questions for operator review before editing:
  - **Resource choice**: Talhelper's `machineDisks` is **deprecated** upstream (schema says "use `userVolumes` instead"). Talos v1.12 ships `UserVolumeConfig` (`apiVersion: v1alpha1`, `kind: UserVolumeConfig`) as the supported replacement. Recommend switching task 5 to `userVolumes` in talconfig.yaml.
  - **Mount path convention clash**: `UserVolumeConfig` auto-mounts at `/var/mnt/<name>` — a flat single-level path, not nested. The plan's intended `/var/mnt/longhorn/disk1` / `/var/mnt/longhorn/disk2` is not directly expressible; the closest equivalents are `name: longhorn-disk1` → `/var/mnt/longhorn-disk1`, or `name: longhorn1` → `/var/mnt/longhorn1`. Longhorn is indifferent to the exact path (set via `nodes.longhorn.io` at Phase 2); the plan language just needs to be reconciled.
  - **Kubelet mount path clash**: Plan task 6 says `/var/lib/longhorn` but the Longhorn 1.11.1 Talos docs prescribe `/var/mnt/longhorn` bind-mounted with `[bind, rshared, rw]`. `/var/lib/longhorn` is Longhorn's default metadata dir (dataPath); `/var/mnt/longhorn` is what kubelet needs visibility into to see the data disks. Recommend following the docs — `/var/mnt/longhorn` — since kubelet already has `/var/lib` visibility by default.
  - **Serial-based selector syntax**: `diskSelector.match` uses CEL; upstream docs show `disk.transport == "nvme"` as the canonical example but do not enumerate whether `disk.serial` is an exposed attribute. Needs a quick in-cluster test (`talosctl get disks -o yaml` to inspect available fields) before committing to a serial match. Fallback: match by WWID or by `disk.model` + `disk.size`, which on this fleet uniquely identifies the WD_BLACK SN7100 1TB units vs the Crucial P3 500GB system disk.
  - Holding task 5/6 edits this tick — the name/path/selector decisions change the shape of the patch and deserve user review. Next tick can land the patch once these are resolved.
- 2026-04-16: Phase 1 Tasks 5+6 done — per-node `userVolumes` + kubelet `extraMounts` landed in `talos/talconfig.yaml`. Decisions taken:
  - **Resource**: `userVolumes` (not deprecated `machineDisks`). Selector uses CEL `disk.serial == "<N>"` — confirmed live on k8s-1 that `disk.serial` is a first-class attribute on `Disks.block.talos.dev` (verified via `talosctl get disk nvme0n1 -o yaml`).
  - **Per-node layout**: k8s-1 → `longhorn-1` (251021802186) + `longhorn-2` (251021802190); k8s-2 → `longhorn-1` (251021802221); k8s-3 → `longhorn-1` (251021800405) + `longhorn-2` (251021801882). Filesystem ext4, `grow: true` to fill each 1 TB NVMe.
  - **Mount paths**: `/var/mnt/longhorn-1` and `/var/mnt/longhorn-2` — forced by `UserVolumeConfig`'s auto-mount convention `/var/mnt/<name>`. The plan's original intent of `/var/mnt/longhorn/disk{1,2}` (nested) is not expressible in `UserVolumeConfig` without extra indirection. Longhorn is indifferent to the exact path (configured at Phase 2 on `nodes.longhorn.io`).
  - **Kubelet mounts**: per-node inline `patches:` bind each `/var/mnt/longhorn-N` with `[bind, rshared, rw]`. Path follows Longhorn 1.11.1 Talos docs (per-disk under `/var/mnt`), not the plan's `/var/lib/longhorn` wording — `/var/lib/longhorn` is Longhorn's metadata dir (dataPath), which kubelet already has visibility into by default; the bind-mount need is specifically for the data-disk paths.
  - **Validation**: `mise exec -- yq eval '.'` passes; `talhelper validate talconfig` returns "Your talhelper config file is looking great!" (with `${talosVersion}`/`${kubernetesVersion}` env pre-set). Per-disk sanity check across all nodes confirms name/serial alignment matches `context/hardware.md`.
  - **Not run**: `task configure`, `git commit`, `talosctl apply-config`. Tasks 7+8 remain pending — deliberate handoff point before the rolling reinstall begins.
- 2026-04-16: Pre-task-7 clarification — `task configure` is **not** a cluster-mutating step. Inspecting `.taskfiles/template/Taskfile.yaml` shows `:configure:` runs `validate-schemas → render-configs (makejinja) → encrypt-secrets → validate-kubernetes-config → validate-talos-config`. It renders `kubernetes/` + `talos/clusterconfig/`, encrypts `*.sops.*` files in place, and validates — no `git commit`, no `git push`, no `talosctl apply-config`. The actual cluster touch happens in task 8 via `task talos:apply-node IP=<ip>` (the `talos-operator` subagent's domain). Task 7's "`task configure` → commit → push" is three distinct sub-steps; running `task configure` alone is safe and reversible (rendered output is rebuildable from source). The `:configure:` task has a `prompt:` gate — "Any conflicting files in the kubernetes directory will be overwritten" — which requires interactive confirmation.
- 2026-04-16: **Pre-reinstall rollback sanity check — flagged, not cleared.** Per plan's important-context note ("if a node fails to boot post-reinstall, recovery depends on `talosctl rollback` working — user is not onsite"), inspected rollback state on all three nodes: `talosctl get meta` shows `MetaKey 0x09` (UpgradeInfo) = **null** on k8s-1, k8s-2, k8s-3. `talosctl rollback --help` says "Rollback a node to the previous installation" — implying a previous install must exist. `talosctl get volumestatus` shows no BOOT-A/BOOT-B secondary boot partition, only `EPHEMERAL`. Interpretation: the nodes have never been upgraded since initial bootstrap, so there is **no prior installer image to roll back to**. After the first new-schematic apply lands, Talos *should* populate 0x09 with the baseline schematic as the rollback target — but that only helps if the new boot succeeds far enough to populate meta, then later fails. If the very first boot on the new installer hangs before meta is written, rollback is unavailable and recovery requires out-of-band access (USB/IPMI), which the operator has flagged as unavailable. **Recommendation before task 8**: (a) pick the least-load-bearing node first (likely non-leader k8s-3 or k8s-2; check `etcd members` leader before first apply); (b) have the `talos-operator` subagent verify rollback availability *after* the first node's apply but *before* touching the second node; (c) if feasible, do a deliberate small-config no-op apply first to prime meta 0x09, then the schematic apply. Holding task 7/8 for operator review.
- 2026-04-16: **Rollback concern re-framed and closed.** Operator push-back: "do we really need rollback?" Re-examined the change profile: strictly additive (same Talos v1.12.6, two userspace-only extensions `iscsi-tools` + `util-linux-tools`), no kernel or boot-path changes. Realistic failure modes — bad image fetch, extension bug, wrong disk selector, bad kubelet bind — all leave `talosctl` reachable and are remotely fixable via config iteration. Only a total first-boot hang needs rollback, and Talos' staged A/B upgrade (`talosctl upgrade --image=...`) auto-rolls-back on boot failure. **Verified**: `task talos:upgrade-node` in `.taskfiles/talos/Taskfile.yaml` reads `talosImageURL` from `talconfig.yaml` via `yq`, appends `:${TALOS_VERSION}` from `talenv.yaml`, and invokes `talhelper gencommand upgrade --extra-flags "--image='<url>:<ver>' --timeout=10m"` — i.e., the staged A/B path. No wiring changes needed; the installer URL bump already landed in `talconfig.yaml` is plumbed through. Operator also confirmed physical fallback (can drive to nodes within hours/days), so the residual "A/B auto-rollback fails too" edge case is a known inconvenience, not a disaster.
- 2026-04-16: **Interview-driven Phase 1 execution decisions (six)**:
  1. **OOB fallback**: operator can drive to the nodes — acceptable risk, not disaster-tier.
  2. **Apply mechanism**: staged A/B via `task talos:upgrade-node` (auto-rollback on boot failure). Not `apply-node` for the image swap.
  3. **Canary pick**: first non-etcd-leader, determined at run time via `talosctl etcd members`. k8s-2 acceptable as non-leader given its weaker 1-disk topology, but leader status takes precedence.
  4. **Per-node order**: `task talos:upgrade-node IP=<ip>` first (bump schematic, A/B-protected), then `task talos:apply-node IP=<ip> MODE=auto` (land userVolumes + kubelet extraMounts on a known-good install). Cleanest failure isolation: if the image is bad, we never reach the config step.
  5. **Commit shape**: one squashed Phase 1 commit covering installer URL + userVolumes + kubelet extraMounts, after `task configure` renders + encrypts. Matches the plan's logical unit.
  6. **Selector robustness**: keep `disk.serial == "<N>"` serial-only. A drive swap should cause a deliberate config update, not silent adoption of a replacement.
- 2026-04-16: Next concrete steps (deferred to operator, not yet run): (a) `task configure` to render the per-node clusterconfig and eyeball the rendered userVolumes + extraMounts; (b) commit; (c) `talosctl etcd members` to name the canary; (d) hand off to `talos-operator` subagent for the rolling sequence with the per-node verification gate already specified in Phase 1 task "Post-node verification". No cluster-mutating operations have been run this session.
- 2026-04-16: Phase 1 render pass — correction and success. (1) `task configure` is **not available in this repo** — the templating system was tidied (no `cluster.yaml`/`nodes.yaml` at root; `.taskfiles/template/` is still present but its precondition fails). For Talos-only changes, the relevant entry point is `task talos:generate-config` (talhelper genconfig). (2) First `talhelper genconfig` failed with `min size or max size is required` — Talos `UserVolumeConfig.provisioning` requires `minSize` or `maxSize` even when `grow: true`. Added `minSize: 100GB` to all five userVolumes as a disk-size sanity gate (WD_BLACK SN7100 are 1 TB; 100 GB is well below any plausible replacement). (3) Re-ran `talhelper validate talconfig` → "Your talhelper config file is looking great!"; `task talos:generate-config` → renders `kubernetes-k8s-{1,2,3}.yaml` cleanly. (4) Eyeballed all three: installer URL `445a99db…:v1.12.6` on all nodes; `UserVolumeConfig` kinds emitted for longhorn-1/longhorn-2 (longhorn-1 only on k8s-2); kubelet `extraMounts` bind `/var/mnt/longhorn-N` with `[bind, rshared, rw]`. Rendered clusterconfig files are gitignored — commit will be talconfig.yaml + plan log only.

## References

- Related ADRs: 0004 (storage framework), 0005 (Longhorn decision), 0007 (kps — the install-gate consumer), 0009 (SFP+ mesh — future sibling plan covers Multus + `storageNetwork`)
- **Longhorn Talos support docs (authoritative for Phase 1)**: https://longhorn.io/docs/1.11.1/advanced-resources/os-distro-specific/talos-linux-support/
- **Talos / Sidero references for the schematic rebuild**:
  - System Extensions guide: https://docs.siderolabs.com/talos/v1.12/build-and-extend-talos/custom-images-and-development/system-extensions
  - Image Factory docs: https://docs.siderolabs.com/talos/v1.12/learn-more/image-factory
  - `iscsi-tools` extension source: https://github.com/siderolabs/extensions/tree/main/storage/iscsi-tools
  - `util-linux-tools` extension source: https://github.com/siderolabs/extensions/tree/main/tools/util-linux
- Hardware inventory: `context/hardware.md`
- Known upstream issues (per ADR 0005): longhorn/longhorn#10181, longhorn/longhorn#10429, siderolabs/talos#11740
- Flux kustomization (post-scaffold): `storage/longhorn`
- Cluster checks (post-install): `kubectl get sc`, `kubectl get hr -n storage`, `kubectl get nodes.longhorn.io -n longhorn-system`
- Subagent handoffs: `talos-operator` (Phase 1), `flux-app-author` (Phase 2), `conventions-linter` (Phase 2 pre-commit)
