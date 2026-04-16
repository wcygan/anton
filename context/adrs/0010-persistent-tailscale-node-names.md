---
status: Accepted
date: 2026-04-15
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
---

# 0010 — Persist Tailscale node identity to disk for stable names

> The `siderolabs/tailscale` extension writes its state to `/var/lib/tailscale/` (persistent EPHEMERAL partition) with `TS_AUTH_ONCE=true`, so `k8s-1`, `k8s-2`, `k8s-3` keep their names and tailnet IPs across reboots instead of re-registering as `k8s-N-M`.

## Status

Accepted

## Context

Talos nodes run the `siderolabs/tailscale` system extension so that `kubectl`, `talosctl`, and the Tailscale operator proxy remain reachable off-LAN. The extension runs `containerboot`, which honours `TS_STATE_DIR` to decide where tailscaled stores its machine key, node key, and login profile.

Anton shipped with `TS_STATE_DIR=mem:` — tailscaled state in RAM. Rationale captured in the patch comment: a prior attempt at `TS_STATE_DIR=/var/lib/tailscale` left a stuck ghost nodekey on the Tailscale control plane that couldn't be cleared from the admin console. `mem:` sidestepped that by re-registering on every boot.

The cost of `mem:` became unacceptable as reboots accumulated (k8s-2 alone rebooted 32 times in 61 days per talos-operator memory). Every reboot registered a new device. Tailscale appends `-1`, `-2`, `-3` suffixes to disambiguate. The tailnet filled with stale offline records (`k8s-1-1`, `k8s-2-3`, `k8s-3-1`, …), `talosctl -n k8s-3` via MagicDNS pointed at dead devices, and operator muscle memory broke.

The prior ghost-nodekey incident that drove us to `mem:` happened on the old tailnet control plane, pre-rebuild. The cluster reset (ADR 0001, 2026-04-10) plus the tailnet migration (2026-04) gave us a fresh control plane where that scar tissue does not apply. Talos 1.8+ preserves `/var` across `talosctl upgrade` (only `talosctl reset --system-labels-to-wipe EPHEMERAL` or a fresh install wipes it), so persistent state survives every operation that actually happens in the normal lifecycle.

## Decision

Anton commits to **persistent on-disk Tailscale state**:

- `TS_STATE_DIR=/var/lib/tailscale` — tailscaled persists machine key, node key, and profile across reboots.
- `TS_AUTH_ONCE=true` — containerboot only runs `tailscale up --authkey=…` when the state dir is empty, preventing re-auth storms that create duplicate devices on extension restart.
- `TS_AUTHKEY` — a reusable, preauthorized, tagged (`tag:k8s`) key in `talos/talenv.sops.yaml`. Only consulted on first boot (empty state) or after a `/var` wipe.

The canonical config lives at `talos/patches/global/tailscale.yaml` and is applied to all three nodes via `talconfig.yaml`'s global patches.

## Alternatives considered

- **Do nothing (keep `mem:`)** — rejected. Reboots are rare in theory but accumulate in practice; the tailnet has been polluted with 7+ stale device records in 61 days, and the admin-console rename workflow is operator toil that doesn't scale.
- **Ephemeral auth keys + fixed `TS_HOSTNAME`** — Tailscale would GC offline ephemeral devices in ~5 min so names recycle. Rejected: the 5-min GC window after a reboot means the *just-rebooted* node re-registers as `k8s-N-1` until the old record expires. With MagicDNS-based `talosctl` access, that window breaks remote operations. Ephemeral devices also can't be stable subnet routers.
- **Scripted cleanup via Tailscale API before/after reboot** — effective but fragile; requires an API token on every node, error paths are hard to make idempotent, and reboots through `talosctl` don't hook cleanly into a pre-reboot step.
- **Dedicated Talos user volume for `/var/lib/tailscale`** — survives more operations than the EPHEMERAL partition. Rejected: Talos 1.8+ preserves EPHEMERAL across reboot and upgrade, which covers 100% of real-world operations; a user volume adds `talconfig.yaml` complexity for zero observed benefit.

## Consequences

### Accepted costs

- **One-shot operator toil to break out of `mem:`.** Three pre-existing nodes had stale `tailscaled.state` files from the Apr 3 tailnet migration (same ghost-nodekey shape). Resolved by a temporary `machine.files: - op: overwrite` entry that wrote `{}` to `tailscaled.state` on a single boot per node, then removed. New nodes onboarded after this ADR start with an empty state dir and don't need this dance.
- **Stale device cleanup obligation on authkey rotation.** When `TAILSCALE_AUTHKEY` rotates and a node re-auths (only happens if `/var` is wiped), the old admin-console device record must be deleted first or the new registration will collide on hostname and get a `-N` suffix.
- **Renovate-PR tax for the `tailscale` extension** — unchanged from the existing posture; the system extension was already part of the cluster.

### What this enables

- `talosctl -n k8s-N` via MagicDNS works reliably — names survive reboots.
- Tailscale admin console stays clean; no more accumulating `k8s-N-M` records.
- Post-reboot connectivity is effectively instant (no re-auth round-trip).
- The `anton-remote-access` skill's guidance is now load-bearing rather than aspirational.

## Debug guidance — if naming regresses in the future

### Symptom A — node comes back as `k8s-N-1` after a reboot

Someone restored `mem:` or `/var` was wiped. Check order:

1. `grep TS_STATE_DIR talos/patches/global/tailscale.yaml` — should be `/var/lib/tailscale`.
2. `talosctl -n <lan-ip> list /var/lib/tailscale/ -l` — `tailscaled.state` should exist and be non-empty. If it's missing, the EPHEMERAL partition was wiped (`talosctl reset`, reinstall, or a rare upgrade failure).
3. `talosctl -n <lan-ip> logs ext-tailscale --tail 50` — look for `Startup complete` without preceding `tailscale up --authkey=…` chatter. With `TS_AUTH_ONCE=true` and valid state, there should be no authkey invocation on restart.
4. If `TS_AUTH_ONCE=true` is missing from the patch and state is empty, containerboot re-auths on every extension restart and creates a duplicate device — exactly the `mem:` symptom.

### Symptom B — node in a login loop with `register request: http 400: node nodekey:… already exists`

The state file on disk has a nodekey that the Tailscale control plane is rejecting. Two common causes:

1. A device with that nodekey exists in the admin console (possibly under a different name than expected) — find it with `tailscale status | rg <node-ip>` from the admin API or the admin console, delete it, wait 30s for the node to retry.
2. The state file is stale from a pre-migration tailnet (the Apr 2026 failure mode). Fix: the one-shot state-wipe pattern.

One-shot state wipe (destructive to the node's current identity — it will re-register with a new nodekey):

a. In `talos/patches/global/machine-files.yaml`, add:

```yaml
- op: overwrite
  path: /var/lib/tailscale/tailscaled.state
  permissions: 0o600
  content: "{}"
```

b. `task talos:generate-config` then `talosctl apply-config --mode=auto` to the affected node only (the change triggers a reboot). Proxy through a healthy node via `-e <healthy-tailnet-ip> --nodes=<affected-lan-ip>`.

c. After the node comes back and registers cleanly, **remove the `machine.files` entry and re-apply** — otherwise every subsequent boot wipes state again and defeats the whole point of this ADR. This is the trap that caused the `k8s-N-1` suffix during the 2026-04-15 rollout.

d. Delete any `k8s-N` devices that were orphaned by the wipe from the admin console, in case their nodekey got rejected as already-registered.

### Symptom C — nodes drop off tailnet after a Talos upgrade

Should not happen on Talos 1.8+ (EPHEMERAL persists). If it does: confirm the upgrade didn't pass `--system-labels-to-wipe EPHEMERAL` (only `talosctl reset` does that by default in anton; `task talos:upgrade-node` uses `talhelper gencommand upgrade` with no wipe flags). If the partition really was wiped, the mitigation is identical to onboarding a fresh node — empty state dir + `TS_AUTHKEY` re-registers it cleanly, assuming no duplicate on the admin side.

### Reaching an offline node

If the node's tailnet extension is down but another cluster node is up, proxy talosctl through the healthy node:

```sh
TALOSCONFIG=./clusterconfig/talosconfig talosctl \
  -e <healthy-node-tailnet-ip> \
  -n <broken-node-lan-ip> \
  <subcommand>
```

The `-e` endpoint must be on the tailnet; the `-n` target can be a LAN IP because the endpoint node proxies the Talos API call over 192.168.1.0/24. Anton's bastion `gertrude` is also on the LAN and can proxy via SSH if zero cluster nodes are on tailnet.

## Follow-ups

- [ ] Monitor for a month. If no naming regressions by 2026-05-15, this ADR is fully validated and the debug guidance becomes preventative rather than load-bearing.
- [ ] Consider adding a cluster-triage check that asserts `TS_STATE_DIR=/var/lib/tailscale` and `TS_AUTH_ONCE=true` are in the generated Talos config for each node. Prevents silent regression from a typo or merge conflict.
- [ ] When rotating `TAILSCALE_AUTHKEY` (90-day cap), remember it's only consulted on empty state — a rotation does not by itself re-register nodes.
