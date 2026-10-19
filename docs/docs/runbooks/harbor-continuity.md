---
sidebar_position: 5
---

# Harbor continuity during planned node maintenance

This runbook prepares a one-node-at-a-time maintenance check for Harbor's
front door. It does not indicate that the candidate HelmRelease has been
merged, reconciled, or exercised on the cluster.

## Outcome and limits

The current evidence snapshot (2026-10-19) has one ready `harbor-nginx`
endpoint and no nginx disruption budget. The HelmRelease candidate uses chart
1.19.2 values for two nginx replicas, soft hostname spreading, and the chart's
own PDB with `minAvailable: 1`. The intended check is an authenticated pull of
a previously uncached private image by digest while one node is cordoned and
drained.

This change only protects Harbor's nginx front door against one voluntary
pod eviction when both replicas are healthy. `ScheduleAnyway` prefers separate
nodes but permits co-location when capacity or scheduling constraints require
it. The check does not establish availability of Harbor's database, Dragonfly,
SeaweedFS S3, or the whole image path. In particular, SeaweedFS volume `000`
uses Longhorn and can require volume reattachment; no end-to-end 60-second
recovery target is claimed.

The target is one active maintenance node at a time, at least one nginx pod
available, and completion of the authenticated digest pull through
`192.168.1.106`. The pull has no fixed latency target; record its start/end and
whether it completed before the maintenance timeout chosen by the operator.

Before review, render the release values against the chart version declared in
Git with `mise exec -- python scripts/checks/check_harbor_continuity_render.py`.
The check uses a temporary chart archive and isolated Helm directories; it does
not access the cluster.

## Preconditions

Use the canonical Anton checkout and the operator's normal maintenance
approval. Do not proceed unless all of these are true:

- The candidate revision is merged and Flux reports the intended source
  revision, the Harbor Kustomization and HelmRelease are Ready, and the nginx
  Deployment has two ready replicas on distinct nodes.
- `harbor-nginx` reports `ALLOWED DISRUPTIONS` of at least 1. Harbor core,
  registry, portal, CNPG, Dragonfly, SeaweedFS S3, and Longhorn are healthy.
- The target node is Ready, is not already cordoned, and no other node
  maintenance or disruption is underway. Confirm remaining capacity for every
  workload that the drain will evict.
- A dedicated client with Docker configured to access the Harbor HTTP endpoint
  is available. It has credentials for a private Harbor project and an image
  digest that has not previously been pulled into that client's image store.
  Do not use a public `library` project: it would not test authentication.
- The operator has selected a maintenance timeout that allows workloads and
  storage to recover. The pull has no 60-second service-level promise.

Start by confirming the context and cluster state from the canonical checkout:

```sh
cd /Users/wcygan/Development/anton
mise exec -- kubectl config current-context
mise exec -- flux get sources git -n flux-system
mise exec -- flux get kustomization harbor -n flux-system
mise exec -- flux get helmrelease harbor -n registries
mise exec -- kubectl -n registries get deployment harbor-nginx -o wide
mise exec -- kubectl -n registries get pods -l app=harbor,component=nginx -o wide
mise exec -- kubectl -n registries get pdb harbor-nginx
mise exec -- kubectl get nodes
```

The expected context is `tailscale-operator.<tailnet-name>.ts.net`; use
`admin@anton` only as the documented fallback. Stop on a different context,
unexpected revision, unhealthy dependency, fewer than two ready nginx pods,
co-located nginx pods, zero allowed disruptions, or an already unavailable
node.

## Maintenance check

Record the target node, source revision, image repository and digest, initial
nginx pod placement, PDB allowance, and start time. From the dedicated client,
configure a fresh Docker client directory and log in interactively. Keep the
auth file private and remove the temporary directory after the check:

```sh
export DOCKER_CONFIG="$(mktemp -d)"
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
docker login 192.168.1.106
```

In the canonical checkout, start the maintenance only after recording the
preconditions and target node. Drain one node and use the timeout approved for
this maintenance window:

```sh
NODE='<one-ready-node-name>'
mise exec -- kubectl cordon "$NODE"
mise exec -- kubectl drain "$NODE" --ignore-daemonsets --timeout=10m
```

While the node is cordoned/drained, run the first pull of an approved private
image digest from the clean dedicated client. Replace both placeholders before
running. This exercises authentication and retrieves the immutable digest
without a pre-existing local image cache:

```sh
IMAGE='192.168.1.106/<private-project>/<repository>@sha256:<64-hex-digest>'
date -u +%FT%TZ
docker pull --platform linux/amd64 "$IMAGE"
docker image inspect "$IMAGE" --format '{{json .RepoDigests}}'
date -u +%FT%TZ
```

Observe nginx placement and disruption allowance:

```sh
mise exec -- kubectl -n registries get pods -l app=harbor,component=nginx -o wide
mise exec -- kubectl -n registries get pdb harbor-nginx
```

Acceptance requires the pull during the maintenance window to exit successfully
and report the requested digest, at least one nginx pod to remain Ready, and
the PDB to prevent eviction below one available pod. Record pull timestamps,
digest, node, revision, and relevant readiness evidence. Do not retain Docker
credentials or auth files.

After maintenance, uncordon and wait for the node and nginx replicas to recover
before considering another node:

```sh
mise exec -- kubectl uncordon "$NODE"
mise exec -- kubectl wait --for=condition=Ready "node/$NODE" --timeout=10m
mise exec -- kubectl -n registries rollout status deployment/harbor-nginx --timeout=10m
```

Then confirm two ready nginx replicas on separate nodes, a healthy PDB, healthy
dependencies, and another authenticated pull using a second previously uncached
private digest from a clean client. A successful nginx continuity check does
not substitute for checking the dependent data path.

## Stop and recovery

Stop if the pull fails, nginx has no Ready endpoint, the PDB allows no planned
disruption before drain, the drain exceeds its timeout, or any required
dependency becomes unhealthy. Do not bypass the PDB or start maintenance on a
second node. If a node is cordoned, restore scheduling with:

```sh
mise exec -- kubectl uncordon "$NODE"
```

Allow evicted workloads and storage attachments to recover, then re-check
Harbor and its dependencies. If the candidate configuration causes a sustained
regression, revert the owning Git change through the normal reviewed Flux
workflow and verify the resulting HelmRelease and endpoint. Do not use a
manual Helm change as rollback; Flux owns Harbor's desired state.
