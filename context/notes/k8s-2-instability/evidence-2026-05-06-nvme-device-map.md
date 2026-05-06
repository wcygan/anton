# 2026-05-06 NVMe device → model → serial → slot map

## TL;DR for the onsite person

**Linux `/dev/nvmeN` numbers are NOT stable across reboots.** They depend on PCIe enumeration order, which can shuffle. A drive that is `nvme0` today may be `nvme2` after a reboot — observed multiple times today.

**PCIe addresses ARE stable.** The PCIe address `0000:NN:00.0` corresponds 1:1 to a specific physical M.2 slot on the MS-01 board.

**Drive serial numbers are stable AND physically printed on the drive label.** When working onsite, identify drives by serial number off the sticker, not by `/dev/nvmeN`.

The hot drive on k8s-2 (the one driving the high-temp readings throughout 2026-05-06) is the SN7100 with serial **`251021802221`** — top M.2 slot (PCIe `0000:01:00.0`).

## Per-node mapping (captured 2026-05-06 via privileged Job)

### k8s-2 (the failing-fan node — focus for the visit)

| PCIe address | Linux device today | Model | Serial | FW | Likely slot | Role |
|---|---|---|---|---|---|---|
| `0000:01:00.0` | `nvme2` | WD_BLACK SN7100 1TB | **`251021802221`** | 7615M0WD | M.2 slot 1 (top, Gen4 ×4, near CPU) | **HOT drive** — Longhorn data |
| `0000:58:00.0` | `nvme1` | WD_BLACK SN7100 1TB | `251021801877` | 7615M0WD | M.2 slot 2 (middle, Gen3 ×4) | Longhorn data (`longhorn-2`) |
| `0000:59:00.0` | `nvme0` | CT500P3SSD8 | `24304A23D2F0` | P9CR313 | M.2 slot 3 (bottom, Gen3 ×2) | Boot / install disk |

### k8s-1

| PCIe address | Linux device today | Model | Serial | FW | Likely slot | Role |
|---|---|---|---|---|---|---|
| `0000:01:00.0` | `nvme0` | WD_BLACK SN7100 1TB | `251021802190` | 7615M0WD | M.2 slot 1 (top) | Longhorn data (`longhorn-2`) |
| `0000:58:00.0` | `nvme2` | WD_BLACK SN7100 1TB | `251021802186` | 7615M0WD | M.2 slot 2 (middle) | Longhorn data (`longhorn-1`) |
| `0000:59:00.0` | `nvme1` | CT500P3SSD8 | `24304A343650` | P9CR313 | M.2 slot 3 (bottom) | Boot / install disk |

### k8s-3

| PCIe address | Linux device today | Model | Serial | FW | Likely slot | Role |
|---|---|---|---|---|---|---|
| `0000:01:00.0` | `nvme2` | WD_BLACK SN7100 1TB | `251021801882` | 7615M0WD | M.2 slot 1 (top) | Longhorn data |
| `0000:58:00.0` | `nvme1` | WD_BLACK SN7100 1TB | `251021800405` | 7615M0WD | M.2 slot 2 (middle) | Longhorn data |
| `0000:59:00.0` | `nvme0` | CT500P3SSD8 | `24304A23705F` | P9CR313 | M.2 slot 3 (bottom) | Boot / install disk |

## Cluster-wide pattern (the stable truth)

Across **all 3 nodes**, the PCIe→model layout is identical:

| PCIe address | Always | Why |
|---|---|---|
| `0000:01:00.0` | WD_BLACK SN7100 1TB (1 of 2) | Fastest slot — Longhorn replica |
| `0000:58:00.0` | WD_BLACK SN7100 1TB (2 of 2) | Second-fastest slot — Longhorn replica |
| `0000:59:00.0` | Crucial CT500P3SSD8 500GB | Slowest slot — boot/install disk (intentionally placed there; boot doesn't need bandwidth) |

The Linux `/dev/nvmeN` numbering is the only thing that shuffles. Use PCIe addresses for any durable code or runbooks; use serials for physical work.

## Why the top-slot drive runs hottest on k8s-2

The drive at `0000:01:00.0` (top M.2 slot) is closest to the CPU heatsink and the CPU fan. With fan1 intermittently stalling on k8s-2 (see [`evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md`](evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md)), the area immediately around the CPU loses airflow first — including the top M.2 slot. Throughout 2026-05-06 the hot drive on k8s-2 was consistently the one in the top slot, regardless of which Linux device number it had after each reboot:

- 10:11 CDT (pre-iter-15-retraction): `nvme0` was hottest at 94 °C — that was the SN7100 at `0000:01:00.0`
- After two rolling reboots: `nvme2` is at 93 °C controller hot-spot — same SN7100 at `0000:01:00.0`, just renumbered

**The drive identity is stable. The Linux number is not.**

## How to verify any of this onsite

1. Power off the node, open the chassis.
2. Read the serial number off each M.2 drive's label (typically white sticker on top of the drive).
3. Cross-reference against the table above — that tells you which physical M.2 slot you are looking at.
4. The slot containing **serial `251021802221`** on k8s-2 is the one whose drive has been running 90+ °C controller hot-spot. That slot's airflow is the most affected by fan1's failure.

## How to verify any of this remotely

```sh
# privileged DaemonSet pod or one-shot Job with /dev and /sys mounted, alpine + nvme-cli
nvme list                                       # current Linux device → model → serial
ls -la /sys/class/nvme/                        # nvmeN → PCIe symlink

# OR via node-exporter pod sysfs read:
for d in /host/sys/class/nvme/nvme*; do
  dev=$(basename "$d")
  echo "$dev model=$(cat $d/model | tr -d ' ') serial=$(cat $d/serial | tr -d ' ') pcie=$(readlink -f $d/device | sed 's|.*/||')"
done
```

## Open follow-up: surface this as a metric

The information in this note is currently a one-shot snapshot. To make it durable and dashboard-able, extend `nvme-power-collector` to emit:

```
node_nvme_info{device="nvme0",model="WD_BLACK SN7100 1TB",serial="...",pcie="0000:01:00.0",fw="7615M0WD"} 1
```

That lets us join temp metrics with stable identifiers (model+serial+PCIe) instead of unstable `nvme_nvmeN` chip labels. ~10-line change in the existing collector script, no new infrastructure. **Not done in this commit** — proposed as a follow-up.

## References

- Source data: privileged Job `nvme-list-snapshot` run 2026-05-06 in `kube-system` namespace; logs captured in this note.
- Related notes:
  - [`evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md`](evidence-2026-05-06-k8s-2-fan1-intermittent-failure.md) — fan1 failure context
  - [`evidence-2026-05-06-k8s-2-turbo-lockout.md`](evidence-2026-05-06-k8s-2-turbo-lockout.md) — broader k8s-2 thermal investigation
- Talconfig install-disk serials cross-referenced (`talos/talconfig.yaml`):
  - k8s-1: `24304A343650` (Crucial, slot 3)
  - k8s-2: `24304A23D2F0` (Crucial, slot 3)
  - k8s-3: `24304A23705F` (Crucial, slot 3)
- Longhorn data-disk serials cross-referenced (`talos/talconfig.yaml`):
  - k8s-1 longhorn-1: `251021802186`; longhorn-2: `251021802190`
  - k8s-2 longhorn-1: `251021802221`; longhorn-2: `251021801877`
  - k8s-3: not labelled, both SN7100s present in the talconfig
