---
title: Talos and node health
---

# Talos and node health

Talos nodes are immutable and managed only through their API. This guide covers read-only node investigation and how to choose a target safely. Upgrades, node replacement, and any config apply have their own high-risk procedures.

## Where node configuration comes from

The source of truth is `talos/talconfig.yaml`, `talos/talenv.yaml`, and the files in `talos/patches/`. Talhelper generates the machine configuration from them; never edit the generated files by hand. After changing a source file, regenerate and review the diff:

```sh
mise exec -- task talos:generate-config
```

Generating and reviewing config does not apply it. Applying is a separate, separately approved step.

`talosVersion` selects the installed OS image. `talosConfigVersion` selects the configuration format used by Talhelper. Keep the latter at `v1.13.12` while using Talhelper 3.1.17: its final release cannot combine Talos 1.14's new document defaults with Anton's existing patches. Talos 1.14 still supports this older format. The global installer patch uses `talosVersion`, so generated node configurations retain the intended OS image. Validate every generated node configuration with the target Talos client before a rollout.

## Choose a target

`scripts/cluster-targets.py` resolves which node a command talks to. The Talos task wrappers and safety checks all use it. The public inventory holds logical node names only; exact fallback endpoints come from ignored private operator configuration.

Inspect the redacted selection before any operation:

```sh
mise exec -- task talos:targets
```

Check which source the target came from and that the membership matches the cluster you expect. If private fallback configuration is missing, you have an access limitation. Do not guess node addresses or copy discovered ones into guides or scripts.

## Investigate a node

Fix the Talos context, the target node, and the time window before you start. Then:

```sh
mise exec -- talosctl health
mise exec -- talosctl get members
mise exec -- talosctl get services
mise exec -- talosctl get disks
```

Start with node readiness and etcd membership. Then look for the earliest relevant evidence in the OS, network interfaces, disks, or services. Line evidence up by node and time rather than by symptom. Avoid broad log dumps, and redact credentials and machine identifiers before sharing.

## Changing a node

Every Talos apply, reboot, reset, upgrade, or replacement needs:

1. The matching high-risk skill's preconditions.
2. An etcd quorum check.
3. A rollback plan.
4. Explicit operator approval.

For Kubernetes API access during this work, prefer the Tailscale operator context. Use the documented administrator fallback only after confirming which identity it uses.
