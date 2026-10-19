# Cluster rebuildability audit and tabletop

This runbook checks whether Anton's committed sources describe a dependency-ordered rebuild and highlights inputs Git cannot prove. It is a source audit, not a restoration test. A clean audit cannot establish that a fresh Talos node, external registry, age identity, 1Password account, or application will work.

The scope follows [ADR 0001](https://github.com/wcygan/anton/blob/main/context/adrs/0001-cluster-reset-and-structured-rebuild.md): rebuild deliberately from the smallest base. Persistent application data is disposable by the October 13 decision in `context/notes/2026-10-13-disable-longhorn-backups.md`; do not add backup infrastructure, external storage, paid services, or Betty to this work. Longhorn replication remains part of normal operation, not a backup guarantee.

## Rerun the source audit

From the repository root:

```sh
python3 scripts/check-rebuild-prerequisites.py
```

The command checks declared bootstrap, secret-delivery, storage, and Harbor source paths, then scans application YAML for images served from the private Harbor address. It never contacts the cluster, pulls images, decrypts SOPS, reads Secret values, or runs workloads. `PASS` means the declared source path exists. `INFO` shows declared stage order, owner, and origin without asserting readiness. `UNKNOWN` means source alone cannot establish availability. `FAIL` means a declared source is absent. An earlier-stage image reference to Harbor is reported as `UNKNOWN` when independent cold-start availability is not proven. Exit status is 0 for all-pass, 2 when evidence is incomplete, and 1 for a failure. Use `--json` for machine-readable output.

The current source audit finds a potential cold-start cycle: `storage-vxlan` is required at the `storage-network` stage and its manifest points to Harbor, which comes later. The [Talos registry patch](../../../talos/patches/global/machine-registries.yaml) and [Spegel mirror configuration](../../../kubernetes/apps/kube-system/spegel/app/helmrelease.yaml) both configure Harbor. The October 13 [image reclamation record](https://github.com/wcygan/anton/blob/main/context/plans/0024-verify-image-harbor-disk-reclamation.md) says this exact custom image was recovered from node cache. That establishes a cache-based recovery path for that event, but committed source does not establish that a cache survives or can be seeded after a cold rebuild. The [Longhorn Kustomization](../../../kubernetes/apps/storage/longhorn/ks.yaml) waits for `storage-vxlan`, and [Harbor configuration](../../../kubernetes/apps/registries/harbor-config/ks.yaml) waits for SeaweedFS configuration, making the ordering relevant to Harbor recovery. Treat this ancestry as unknown until a cold-start source is evidenced. The audit also finds a Harbor-hosted `nvme-power-collector` image whose availability cannot be verified from committed source. Public OCI image and chart availability is not tested by this offline scan. These results identify evidence gaps; they do not prove current workloads are broken.

## Two-hour tabletop

Budget two hours with one operator and one note-taker. Keep the exercise in Git and a blank worksheet; do not reset hardware, alter cluster state, or use credentials in output.

1. **0–15 minutes — agree on outcome.** Start with an empty Kubernetes state and disposable persistent data. Acceptance means the operator can name the independent owner/origin and deterministic order for each critical input through private apps, or mark it unknown with a specific evidence source. Do not count a successful parse or current healthy cluster as proof of recovery.
2. **15–35 minutes — inspect the audit.** Run the command above; record commit, timestamp, all FAIL/UNKNOWN rows, and which image references came from YAML. Confirm there was no live access or Secret-value inspection.
3. **35–75 minutes — walk the dependency order.** Trace Talos source and operator-held prerequisites; bootstrap Cilium then CoreDNS/Spegel; SOPS/Flux and ESO delivery; Multus/storage network; Longhorn and SeaweedFS; CNPG/Dragonfly and Harbor; then private apps. For each transition, state the source owner, independent origin, required artifact, and what observation would prove it ready. Unknown stays unknown.
4. **75–105 minutes — challenge failure points.** Assume public OCI is unreachable, the age identity is unavailable, 1Password cannot deliver a Harbor prerequisite, and the Harbor image server is empty. Identify the first blocked layer and whether a bootstrap-critical image can be obtained without Harbor. For the current `storage-vxlan` potential cycle, record an independent image source or a cache-seeding proof as an open decision; do not imply either exists.
5. **105–120 minutes — close evidence gaps.** Assign owners for verifying external inputs and propose a later isolated-cluster drill. The tabletop passes when the dependency order is explicit, every unresolved input has an owner and a read-only evidence plan, and no step silently relies on Harbor before Harbor exists. It does not count as a measured rebuild-time result.

## Evidence and later drill

Retain the sanitized CLI output, repository revision, tabletop decisions, unresolved inputs and owners. Never copy age keys, tokens, Secret values, or literal tailnet names into the record.

A later isolated rebuild drill needs separate operator approval and a disposable environment. Before that drill, specify the exact target, recovery sources, timeout, stop condition, cleanup, and rollback. Acceptance evidence should include completed Talos bootstrap; CNI and DNS readiness; Flux source and reconciliation; ESO delivery conditions without displaying values; storage and Harbor readiness; image pull availability for all pinned critical workloads; and a user-visible check for nominated private services. Record elapsed time by stage only during that real drill. Until then, the proposed goal of completing a rebuild within one workday remains unmeasured.

## Rollback

This change only adds an offline script, its data contract, tests, and this runbook. To roll it back, revert the commit containing those files. There is no live-state rollback because the audit makes no cluster changes.
