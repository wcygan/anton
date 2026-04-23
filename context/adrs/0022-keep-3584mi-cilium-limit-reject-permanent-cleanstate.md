---
status: Accepted
date: 2026-04-23
deciders: ['@wcygan']
affects: networking
intent: concrete-need
supersedes: [0021]
superseded-by: null
retrospective: false
---

# 0022 — Keep 3584Mi cilium-agent memory limit; reject `cleanState: true` as a permanent config

> ADR 0021 landed two changes together: raise `cilium-agent.resources.limits.memory` 2560 → 3584 MiB AND set `cleanState: true`. The limit bump works and stays. `cleanState: true` deadlocked the rolling DaemonSet update on 2026-04-23 — the `clean-cilium-state` init container refuses to run while the previous agent's `/var/run/cilium/cilium.pid` exists on the host, which is always true during an in-place DaemonSet replacement. `cleanState` is a manual one-shot recovery flag upstream, not a permanent value. Keep the 3584Mi. Drop `cleanState`.

## Status

Accepted

## Context

ADR 0021 was authored on 2026-04-23 as the remediation for the 2026-04-23 20:45-20:47Z two-node silent-reboot cascade, citing cilium/cilium #42007 as the near-exact upstream match. The ADR proposed a two-part intervention: raise the memory limit to 3584 MiB (giving brief BPF-state peaks room to breathe) AND set `cleanState: true` so every cilium-agent restart rebuilds BPF maps from scratch instead of inheriting possibly-corrupted state from the previous cgroup.

The author's reading of #42007 framed `cleanState: true` as the "upstream-recommended permanent pairing" for the taller ceiling. That reading was wrong.

Commit `65f10966` landed the ADR-0021 configuration on 2026-04-23 ~23:40Z. Flux reconciled the HelmRelease, incremented the DaemonSet generation, and began the rolling update. On k8s-1 and k8s-2, the new pods entered `Init:Error` / `Init:CrashLoopBackOff` with the clean-cilium-state init container emitting:

```
Agent should not be running when cleaning up
Found pidfile /var/run/cilium/cilium.pid
```

k8s-3's old pod stayed Running (the DaemonSet controller paused the rollout after two concurrent failures). Cluster datapath stayed up on existing BPF programs, but the control plane on k8s-1 and k8s-2 was down — no new endpoint programming, no policy updates, IPAM affected for new pods.

The mechanism: `/var/run/cilium/` is a hostPath mount. When the DaemonSet controller replaces a pod, the departing agent's `cilium.pid` does not clear instantly — it persists on the host until the kernel reaps the process and the cleanup handler runs. The new pod's init container starts within ~2 s of the old pod's termination and sees the stale pidfile. Its safety check (reasonable for a "wipe all state" operation — it should not run while the agent is alive) fires, the init container exits non-zero, and kubelet keeps retrying.

The Helm upgrade timed out at 5 min waiting for DaemonSet stability, Flux rolled back to v12 (the pre-ADR-0021 config at 2560 MiB), and the cluster stabilized in its original state. `fix` commit `d5835aa1` dropped `cleanState: true` from the HelmRelease. The subsequent reconcile (Helm v14 → v15) completed cleanly. All three cilium-agents now run with 3584Mi / no `cleanState`.

Reading `cleanState` in the cilium Helm chart values with more care: the accompanying documentation is `"Clean all Cilium state on startup"` with a `"Use with caution! This may cause unexpected side effects"` warning. It is clearly documented as a manual one-shot recovery surface, not a permanent value. The upstream pattern for using it is:

1. Flip `cleanState: true`, apply.
2. Delete the pod(s) you want wiped: `kubectl delete pod -l k8s-app=cilium -n kube-system --field-selector spec.nodeName=<node>`.
3. Flip `cleanState: false`, apply.

The init container's pidfile check makes that workflow work (you are deleting the old pod and it terminates cleanly before the replacement starts), but it makes the flag fundamentally incompatible with the DaemonSet controller's own rolling-update behavior (where new and old pods can transiently overlap on the same node's hostPath).

## Decision

Retain ADR 0021's memory-limit change: `cilium-agent.resources.limits.memory: 3584Mi`. The limit bump is orthogonal to the BPF-state-wipe mechanism and is sufficient on its own as the #42007 remediation's "durable" half — the extra 1 GiB of headroom is what prevents WSS from reaching the BPF-corruption zone under pod-churn spikes.

Reject `cleanState: true` as a permanent HelmRelease value. Do not pair it with the memory bump. Do not re-introduce it without the manual pod-delete workflow above.

Mark ADR 0021 `Superseded-by 0022`. 0021's body stays immutable (anton rule) and is preserved as the historical record of the incorrect framing. This ADR carries the corrected decision forward.

## Alternatives considered

- **Restore `cleanState: true` and engineer around the deadlock** (e.g., add `preStop` hook that removes the pidfile, or add an initContainer that does so before `clean-cilium-state` runs) — rejected. That inverts the safety check's purpose. The check exists precisely to prevent running cleanup while the agent is alive — bypassing it to unblock automation means running cleanup against a potentially-alive agent on host-shared state. Worse than the problem.
- **Use `cleanBpfState: true` instead** (cleaner scope, wipes only BPF maps, not identities) — same init container, same pidfile check, same deadlock. No different operationally.
- **Rely solely on the 3584Mi limit; treat `cleanState` as never needed** — this ADR's choice. The #42007 mechanism does require brief near-limit peaks; giving headroom addresses the trigger. If BPF-state corruption is ever actually observed (vs hypothesised as a secondary face of #42007), the manual one-shot `cleanState` workflow is available as an operator tool. Detection surface for that: Phase 3's `CiliumAgentMemoryCritical` alert + the cluster-health dashboard panel id 704.
- **Keep the pairing and accept rollback as a failure mode** — rejected. Every cilium HR change (chart bump, value tweak, annotation-only change that bumps the config checksum) triggers the rolling update. Permanent `cleanState: true` would make every reconcile deadlock. That is not a viable steady state.

## Consequences

### Accepted costs

- ADR 0020 → 0021 → 0022 in ~6 hours. The history is preserved, but the rapidity is worth naming: this is the mechanism's three-face nature showing up as three ADRs. 0020 addressed the cgroup-OOM face; 0021 tried to address the BPF-corruption face with the wrong tool; 0022 retracts the `cleanState` half and stands on the memory-bump half. Plan 0009's 14-day stable-uptime clock starts from the 0022 rollout, not 0021 — roughly 00:00Z 2026-04-24.
- The 04-23 cascade still lacks a direct BPF-corruption mitigation. If the next cascade's telemetry (kernel stream via Phase 1 netconsole, now live) points at BPF-state corruption rather than pure memory pressure, 0022 may need a successor that introduces the manual one-shot workflow, or that re-architects cilium-agent out of the DaemonSet rolling-update lifecycle (e.g., into a systemd slice per the ADR 0021 "alternatives considered" note). Out of scope here.
- Renovate-PR tax: none.

### Restore-runbook obligation

None — configuration decision.

### Lessons

- **Read Helm chart values' own documentation, not just upstream issue remediations.** `cleanState` comes with its own "Use with caution! This may cause unexpected side effects" warning right next to the value. Reading that first would have prevented the half-hour outage window.
- **"Permanent on" is a load-bearing claim.** When an upstream issue says "set X to fix Y", the next question is "is X a safe steady-state value, or a one-shot?" A value being off-by-default is often a signal that it is not safe to leave on. Defaults encode safety defaults.
- **DaemonSet rolling updates + hostPath state = fragile.** Any init-container safety check that reads host state from `/var/run/` or similar can deadlock under a rolling replacement because the old pod's state is still there. This is a category of footgun worth calling out in any future "add an init container" ADR.
- **Flux rollback saved us.** The Helm upgrade timed out at 5 min, Flux rolled back to v12 (2560 MiB pre-0021 state), and the cluster stabilized before manual intervention was needed. The 5-min Helm timeout is a well-chosen default for exactly this case.

## Follow-ups

- [x] Remove `cleanState: true` from `kubernetes/apps/kube-system/cilium/app/helmrelease.yaml`. (Done in `d5835aa1`.)
- [x] Mark ADR 0021 `Superseded-by 0022` in its frontmatter; 0021 body unchanged.
- [ ] Plan 0009 Phase 3's `CiliumAgentMemoryCritical` alert (at 3072 MiB for 2m) is now the operator's early-warning surface for the #42007 mechanism — no automated BPF-wipe-on-restart is landing. Update plan 0009 log to reflect that acceptance criterion 2's language needs reading: the criterion says "setting `clean-cilium-state: true`", which 0022 rejects. Resolution: treat criterion 2 as partially met — the 3584Mi bump is the "durable" half, and the criterion's `clean-cilium-state: true` clause is retracted by this ADR.
- [ ] If a cilium-agent restart is ever needed manually (e.g. for a confirmed BPF-state corruption), use the pattern documented above (flip → delete → flip back), not a persistent HelmRelease change.
