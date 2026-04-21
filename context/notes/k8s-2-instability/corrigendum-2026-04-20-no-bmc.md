# 2026-04-20 — Corrigendum: step 2 (BMC SEL pull) is structurally impossible

The synthesis document [`2026-04-20-multi-agent-rca.md`](2026-04-20-multi-agent-rca.md) ranks `ipmitool -I lanplus ... sel list` as a pre-work check (Phase 1 step 2) and elevates it again under devils-advocate's "Tier 1" repositioning. **Both ranks are incorrect for this cluster.**

## Fact

Anton's three nodes are **Minisforum MS-01** i9-13900H mini-workstations. They ship:

- 2× 2.5 GbE RJ45
- 2× 10 GbE SFP+
- **No dedicated BMC NIC.**
- **No shared-LOM IPMI / ASPEED / Redfish endpoint.**
- BIOS flashback via front-port USB is the only OOB facility — it requires physical access and serves one purpose (flashing BIOS), not log retrieval.

Derivable from `context/hardware.md`. Re-verifying now:

```
$ grep -iE 'bmc|ipmi|redfish|idrac' context/hardware.md
(no matches)
```

The hardware inventory does not mention any OOB management because there is none.

## Consequence

- **Phase 1 step 2 (BMC SEL pull):** drop from the action list. Structurally impossible.
- **devils-advocate's "IPMI is the cheapest answer, elevate to Tier 1":** refuted. Not cheaper; not possible.
- **simplifier's "delete Tier 3 IPMI":** correct, for the right reason — the premise was wrong.
- **observability-advisor's "do once, not as infra":** irrelevant — neither option exists.

## What replaces step 2

The in-band equivalent of "retroactively capture what the OS could not log" is **Talos `machine.logging.destinations`** — shipping kernel + machined logs to an off-box collector **before** the next reboot. That is the Phase 2 replacement, not a read-only Phase 1 step.

Specifically from the synthesis Phase 2 list:

> 6. Add `machine.logging.destinations` UDP to a stable collector. **Not** a laptop — use k8s-1 itself or another always-on tailnet host. Start with `nc -lku 6050 > k8s-2.jsonl`.

This is the corrected path forward for post-facto-reboot evidence. On MS-01, there is no alternative.

## How this was caught

The sibling memory `project_ms01_no_bmc.md` in the agent's auto-memory records that a prior session made the same mistake — reasoning about BMC IPs and 1Password credentials for half a session before the MS-01 inventory was re-read. That memory now pre-empts the error in future sessions. This corrigendum is its in-repo counterpart, so the synthesis doc's BMC references don't mislead a future reader who doesn't share that memory.

## Status

- **Phase 1 pre-work is effectively complete** — steps 1, 3, 4, and 5 done; step 2 is void.
- **No BMC-related action remains or should be proposed** for anton nodes.
- If anyone proposes a "pull SEL" path in the future for this cluster, reject the premise and redirect to Talos in-band logging or physical-access diagnostics.
