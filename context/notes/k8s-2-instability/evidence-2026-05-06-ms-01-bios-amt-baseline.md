# 2026-05-06 MS-01 BIOS and AMT baseline

## Summary

Remote BIOS version reads work through Talos DMI, but Intel AMT/KVM was not reachable from the LAN bastion (`gertrude`) during this check. BIOS settings cannot be changed remotely through AMT until AMT is provisioned/enabled or a reachable AMT management path is identified.

## Vantage point

- Bastion: `gertrude`
- Bastion location: same LAN as the MS-01 management interfaces
- Route to MS-01 LAN: direct LAN route confirmed
- Nodes scanned: `192.168.1.98`, `192.168.1.99`, `192.168.1.100`

## BIOS version read via Talos DMI

| Node | LAN IP | BIOS version | BIOS date |
|---|---:|---:|---:|
| k8s-1 | `192.168.1.98` | `1.26` | `10/14/2024` |
| k8s-2 | `192.168.1.99` | `1.27` | `04/03/2025` |
| k8s-3 | `192.168.1.100` | `1.27` | `04/03/2025` |

Commands:

```sh
talosctl --talosconfig ./talos/clusterconfig/talosconfig -e <node-tailnet-ip> -n <node-tailnet-ip> read /sys/class/dmi/id/bios_version
talosctl --talosconfig ./talos/clusterconfig/talosconfig -e <node-tailnet-ip> -n <node-tailnet-ip> read /sys/class/dmi/id/bios_date
```

## AMT/KVM reachability from gertrude

Targeted AMT/KVM reachability check from `gertrude` to each node's Talos LAN IP:

Result: no reachable AMT/KVM endpoint was found from this bastion during the check.

## Interpretation

- BIOS version and date are remotely observable through Talos.
- BIOS setup and BIOS settings are not currently remotely controllable through AMT/KVM from `gertrude`.
- The most likely states are: AMT disabled, AMT not provisioned, KVM redirection disabled, or AMT using a network path not reachable from this bastion.
- Any BIOS setting changes from plan 0015 currently require physical access or a one-time physical pass to enable/provision AMT.
