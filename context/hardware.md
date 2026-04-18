# Hardware inventory

Node hardware reference for anton's three control planes.

**Chassis:** Minisforum MS-01 workstation — <https://store.minisforum.com/products/minisforum-ms-01-workstation>

**CPU:** Intel® Core™ i9-13900H (13th Gen, 14 cores / 20 threads, 5.4 GHz max) — same on all three nodes.

**OS:** Talos Linux (immutable, API-driven; machine configs in `talos/`).

**Last verified:** 2026-04-18

## RAM

All nodes ship 2× 48 GiB DDR5 SODIMMs (one per memory controller) for 96 GiB total. k8s-2 runs at a lower speed (Mushkin vs Crucial on the other two).

| Node (tailnet IP) | Used / Total (MiB) | Modules | Manufacturer | Part | Speed |
|---|---|---|---|---|---|
| k8s-1-1 (100.90.7.128) | 4,345 / 96,260 | 2× 48 GiB | Crucial Technology | CT48G56C46S5.M16B1 | 5600 MT/s |
| k8s-2-3 (100.123.134.70) | 3,642 / 96,224 | 2× 48 GiB | Mushkin | MRA5S520HHHD48G | 5200 MT/s |
| k8s-3-1 (100.89.247.4) | 3,090 / 96,221 | 2× 48 GiB | Crucial Technology | CT48G56C46S5.M16B1 | 5600 MT/s |

## Storage

All nodes install Talos to the Crucial P3 500 GB. Each node has 2× WD_BLACK SN7100 1 TB data NVMes reserved for replicated block storage (Longhorn, ADR 0005).

| Node | System disk (500 GB) | Data NVMe #1 (1 TB) | Data NVMe #2 (1 TB) |
|---|---|---|---|
| k8s-1-1 | Crucial CT500P3 — `24304A343650` | WD_BLACK SN7100 — `251021802190` | WD_BLACK SN7100 — `251021802186` |
| k8s-2-3 | Crucial CT500P3 — `24304A23D2F0` | WD_BLACK SN7100 — `251021802221` | WD_BLACK SN7100 — `251021801877` |
| k8s-3-1 | Crucial CT500P3 — `24304A23705F` | WD_BLACK SN7100 — `251021801882` | WD_BLACK SN7100 — `251021800405` |

System disks are pinned by serial in `talos/talconfig.yaml` via `installDiskSelector`. Data NVMes are declared as Talos `UserVolumeConfig` resources with CEL `disk.serial` selectors and mount at `/var/mnt/longhorn-1` / `/var/mnt/longhorn-2` (see plan 0001 Phase 1 Log for why the mount paths are flat, not nested).

### Longhorn OSD topology (as of 2026-04-18)

| Node | Longhorn-eligible disks | Notes |
|---|---|---|
| k8s-1 | 2× WD_BLACK (`251021802186`, `251021802190`) | `/var/mnt/longhorn-1`, `/var/mnt/longhorn-2` |
| k8s-2 | 2× WD_BLACK (`251021802221`, `251021801877`) — pending `longhorn-2` userVolume | `/var/mnt/longhorn-1` registered; `longhorn-2` declaration pending plan 0001 follow-up |
| k8s-3 | 2× WD_BLACK (`251021800405`, `251021801882`) | `/var/mnt/longhorn-1`, `/var/mnt/longhorn-2` |

**Physical state: symmetric 2+2+2 (6 disks).** **Longhorn-registered state: asymmetric 2+1+2 (5 disks)** pending a `UserVolumeConfig` + kubelet `extraMount` addition for k8s-2 `longhorn-2` in `talos/talconfig.yaml`. plan 0002-series deploys Longhorn with `defaultReplicaCount: 2` + `dataLocality: best-effort`; replica placement on a 2-replica default will continue to skew toward k8s-1 + k8s-3 until the `longhorn-2` userVolume lands. Acceptable for install + smoke test; revisit replica policy before committing production workloads that depend on symmetric capacity.

> **k8s-2 second-NVMe status (2026-04-18).** Both data NVMes now enumerate at POST after a physical reseat — root cause was seating / standoff, not a dead slot or drive. Serial `251021801877` captured for the first time during that visit. Remaining work is the `longhorn-2` userVolume declaration on k8s-2 (plan 0001 follow-up). See `.claude/agent-memory/talos-operator/project_k8s_2_hardware_state.md` for the prior disappearance timeline, now historical.

## Networking

Each MS-01 ships 2× 2.5 GbE RJ45 + 2× 10G SFP+ (Intel X710-DA2) ports. Today management traffic uses RJ45 port 1 (`enp87s0`) on the `192.168.1.0/24` subnet. SFP+ ports form a dedicated 10 Gbit full-mesh storage overlay per ADR 0009 — **physically cabled and link-up on all 6 ports as of 2026-04-18**; L3 addressing, Multus, and Longhorn `storageNetwork` are pending follow-ups (new plan, TBD).

### Interface map (per node)

The SFP+ interface names follow the kernel `enp<bus>s<slot>f<func>np<port>` convention for the X710 at PCIe `02:00`; ports 0 and 1 are the two physical SFP+ cages on the card.

| Node | Mgmt RJ45 `enp87s0` (carries node IP) | Unused RJ45 `enp90s0` | SFP+ port 1 `enp2s0f0np0` | SFP+ port 2 `enp2s0f1np1` |
|---|---|---|---|---|
| k8s-1 | `58:47:ca:79:7c:a2` (`192.168.1.98`) | `58:47:ca:79:7c:a3` | `58:47:ca:79:7c:a0` | `58:47:ca:79:7c:a1` |
| k8s-2 | `58:47:ca:79:78:ba` (`192.168.1.99`) | `58:47:ca:79:78:bb` | `58:47:ca:79:78:b8` | `58:47:ca:79:78:b9` |
| k8s-3 | `58:47:ca:7a:54:aa` (`192.168.1.100`) | `58:47:ca:7a:54:ab` | `58:47:ca:7a:54:a8` | `58:47:ca:7a:54:a9` |

### SFP+ full-mesh topology (ADR 0009)

Three Cable Matters 10GBASE-CU 1m passive DAC cables form a full mesh:
- k8s-1 ↔ k8s-2
- k8s-1 ↔ k8s-3
- k8s-2 ↔ k8s-3

All six SFP+ ports show `OPER STATE=up, LINK STATE=true` in `talosctl get links`. Per-cable port-to-port mapping (which `enp2s0fN` on one node terminates on which `enp2s0fN` on the other) was not recorded during cabling on 2026-04-18 — discover via LLDP or iterative ping when the ADR 0009 follow-up plan assigns the three `/31` subnets.
