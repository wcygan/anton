---
name: iter-15 retracted (NVMe APST disable removed cluster-wide)
description: 2026-05-06 plan-0013 iter-15 thermal-driven retraction; cmdline + DS Op 3 + per-drive sysfs all back to APST-natural (PM-QoS 100000)
type: project
---

Iter-15 NVMe APST disable was retracted in 3 steps on 2026-05-06 because the thermal cost outweighed unvalidated silent-reboot benefit. End state: every NVMe drive on every node is back to kernel-default APST behavior (`nvme_core.default_ps_max_latency_us` cmdline absent, per-drive `pm_qos_latency_tolerance_us=100000`).

**Step 1** — one-shot Job wrote 100000 to all 9 per-drive sysfs entries.
**Step 2** — commit `e57906f9` removed Op 3 (per-drive APST disable) from the `idle-mitigations` DaemonSet. DS now only handles Op 1 (cluster PM-QoS=1) and Op 4 (HMB=0).
**Step 3** — commit `77667632` (revert of `11e097a5`) switched `talosImageURL` back to `445a99db4002e6127e7f6e2a96377ac2c06d0de52f7a186b5536c0ac2f2a2ece:v1.13.0`. Rolling reboot k8s-1 → k8s-3 → k8s-2.

**Why:** k8s-2 nvme0 was holding at 93.85 °C, nvme1 at 84.85 °C with iter-15 active. After step 1 those dropped to 70.85 / 62.85 °C immediately. Post step 3 verification: nvme0=64 °C, nvme1=63 °C, nvme2=71 °C on k8s-2 — drives are stably cool while running production workload.

**How to apply:** if a future operator considers re-enabling `nvme_core.default_ps_max_latency_us=0`, treat the +20-30 °C steady-state as the baseline cost and weigh it against whatever benefit is actually being measured. Iter-15 was speculative and never produced a measured silent-reboot decrease.

**Reboot durations** (reboot command issued → kube Ready):
- k8s-1: 19:48:50 → 19:52:08 = ~3 min 18 s (first node, longer because external-secrets-webhook had to be rescheduled before flux could reconcile downstream Ks)
- k8s-3: 20:28:11 → 20:29:35 = ~1 min 24 s
- k8s-2: 20:46:03 → 20:47:23 = ~1 min 20 s

**Pre-existing issue observed but unrelated:** `harbor-postgres-2` was in a pod-restart loop (CNPG bootstrap-controller) before, during, and after the rollout — pre-existing CNPG state, the harbor-config Kustomization stayed in `Reconciliation in progress` throughout. Not regression.
