---
title: SeaweedFS node maintenance
---

# SeaweedFS node maintenance

SeaweedFS currently has one volume server per Kubernetes node. A Longhorn
replica protects a volume server's PVC; it does not serve SeaweedFS reads while
that server is absent. With native placement `000`, an existing object can be
unavailable for the maintenance window even when another S3 gateway is Ready.

## Check existing data placement

From the canonical Anton checkout, run the read-only audit:

```sh
mise exec -- python3 scripts/verify-seaweedfs-maintenance.py \
  --expected-kube-system-uid 5848c42c-b3ec-4003-a02c-becc2c9fa63f \
  --expected-seaweed-uid dce6fb89-c179-4c19-9a98-2bfc7d0aaa73
```

Supply `--expected-context` when an exact locally known context is available.
The command requires the Tailscale operator context, pins every subsequent
read to that context, redacts its tailnet, and bounds the entire observation
to 15 seconds. It performs GETs only. The reported start/end timestamps delimit
separate API reads, rather than an atomic snapshot.

Exit zero means every selected native volume has consistent nonzero replica
placement, matching reported sizes, and active copies on distinct Ready nodes.
The audit joins master topology to the Seaweed-owned StatefulSet, Ready Pods,
their actual Bound PVCs and Kubernetes nodes. Inactive locations, terminating
resources, ambiguous ownership and mismatched identity fail closed. Exit 2
means the condition is unmet or the observation failed; inspect `issues`.
The default selection includes every collection, including the empty collection.
Use repeatable `--collection` arguments only to produce an explicitly partial
report; it does not establish availability of excluded data.

This is a placement check. Matching sizes do not establish matching bytes.
It does not prove S3 reads, writes, cache freshness, in-flight request recovery
or permission to drain a node. Repeat fresh identity and health preflight
immediately before any separately approved maintenance.

## Availability acceptance

A useful maintenance test reads an object that has never been fetched through
the tested gateways and checks its exact digest while a known owning server
is absent. Map that exact object's chunk file IDs and each chunk's owners
before withdrawal. A new OCI client alone is insufficient: the S3 gateway can
serve a warm body cache. A fresh PUT followed by an exact GET tests a different
property and must be recorded separately.

The October 19 baseline has 20 native `000` volumes, each with one active
SeaweedFS location. Stable peer DNS improves replacement recovery, but does not
make this data available while its only serving process is absent. A future
replication-default change must include an existing-data migration and gateway
lookup-cache verification; it cannot pass acceptance from the default alone.

The measured baseline and migration investigation are recorded in
[`2026-10-19-seaweedfs-maintenance-availability.md`](https://github.com/wcygan/anton/blob/main/context/notes/2026-10-19-seaweedfs-maintenance-availability.md).
