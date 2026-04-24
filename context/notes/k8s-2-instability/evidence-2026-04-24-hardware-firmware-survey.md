# 2026-04-24 hardware / firmware survey

## Scope

Read-only Talos and Prometheus checks after the current boot. This does not
replace a physical DIMM swap, memtest, BIOS-settings diff, or chassis swap.

## BIOS and microcode

| Node | BIOS | BIOS date | Product | Board | Runtime microcode |
|---|---|---|---|---|---|
| k8s-1 | 1.26 | 2024-10-14 | Venus Series | AHWSA | 0x00006134 |
| k8s-2 | AHWSA.1.22 | 2024-03-12 | Venus Series | AHWSA | 0x00006134 |
| k8s-3 | AHWSA.1.22 | 2024-03-12 | Venus Series | AHWSA | 0x00006134 |

Sources:

```text
talosctl read /sys/class/dmi/id/{bios_version,bios_date,product_name,board_name}
talosctl dmesg | rg -i 'microcode:'
```

The BIOS split remains real, but runtime microcode is not the differentiator.

## EDAC / MCE / kernel error surface

EDAC counters are clean on all three nodes:

| Node | mc0 CE | mc0 UE | mc1 CE | mc1 UE |
|---|---:|---:|---:|---:|
| k8s-1 | 0 | 0 | 0 | 0 |
| k8s-2 | 0 | 0 | 0 | 0 |
| k8s-3 | 0 | 0 | 0 | 0 |

Filtered current-boot dmesg found no MCE, machine-check, panic, oops, lockup,
RCU stall, NVMe reset/timeout, or NIC reset/timeout on k8s-2. Common benign
lines across nodes:

- `EDAC igen6: v2.5.1`
- `caller igen6_probe... mapping multiple BARs`
- `iTCO_wdt ... initialized. heartbeat=30 sec (nowayout=0)`
- `igc ... enp87s0: NIC Link is Up 1000 Mbps Full Duplex`

Source filter:

```text
talosctl dmesg | rg -i 'mce|machine check|edac|ras|aer|pcie|thermal|thrott|watchdog|iTCO|nvme.*(error|reset|timeout|fail|abort|ctrl)|igc.*(error|reset|timeout|hang|tx|rx)|panic|oops|BUG:|lockup|rcu.*stall'
```

## NIC firmware

Talos `LinkStatuses` show no k8s-2-specific NIC firmware split:

| Device class | Driver | Firmware | Notes |
|---|---|---|---|
| Intel X710 SFP+ (`8086:1572`) | `i40e` / 6.18.18-talos | `9.20 0x8000d8c5 0.0.0` | same on all nodes |
| Intel I226-V (`8086:125c`) | `igc` / 6.18.18-talos | `2017:888d` | same on all nodes |
| Intel I226-LM (`8086:125b`) | `igc` / 6.18.18-talos | `2017:888d` | same on all nodes, link down |

Source:

```text
talosctl get links -o yaml
```

## NVMe inventory

All nodes have the same model / firmware pattern:

| Slot class | Model | Firmware |
|---|---|---|
| nvme0 | WD_BLACK SN7100 1TB | 7615M0WD |
| nvme1 | WD_BLACK SN7100 1TB | 7615M0WD |
| nvme2 | CT500P3SSD8 | P9CR313 |

Serials differ by node as expected. Talos `Disks` exposes inventory but not a
SMART error log in this path.

Sources:

```text
talosctl get disks -o yaml
talosctl read /sys/class/nvme/nvme{0,1,2}/firmware_rev
```

## Temperature / memory health snapshot

Current temperatures were ordinary:

| Node | acpitz | x86_pkg_temp |
|---|---:|---:|
| k8s-1 | 27.8 C | 51 C |
| k8s-2 | 27.8 C | 49 C |
| k8s-3 | 27.8 C | 48 C |

`/proc/meminfo` reports `HardwareCorrupted` absent/zero on all three nodes.

## Netconsole / sink readiness

Vector sink is receiving kernel records on 2026-04-24:

| Source host | Kernel records |
|---|---:|
| `10.100.100.1` | 53 |
| `192.168.1.99` | 31 |
| `192.168.1.100` | 54 |

`10.100.100.1` is k8s-1's VXLAN/VTEP source path noted in plan 0009.

Source:

```text
kubectl -n observability exec talos-log-sink-vector-0 -c rotator -- \
  grep '"source":"kernel"' /vector-data-dir/talos-sink-2026-04-24.log
```

## Interpretation

No in-band hardware/firmware check found a k8s-2-only signature. That does not
clear k8s-2 hardware: a marginal DIMM, CPU/board, VRM, or BIOS setting can
still hard reset without EDAC/MCE breadcrumbs. The next decisive test remains
physical: DIMM swap or memtest first, then BIOS/settings normalization.

