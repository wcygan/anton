---
title: Harbor registry
---

# Harbor registry

Harbor is Anton's private OCI registry. Image blobs live in SeaweedFS. Workloads in the cluster pull through the internal registry service; operators browse and push through the private Tailscale ingress. That ingress is private, not public.

Spegel is separate. It shares images that are already in nodes' local containerd stores and does not replace Harbor.

Examples on this page use a placeholder host. Resolve the real one from your own environment:

```text
registry.<tailnet-name>.ts.net/<project>/<image>:<tag>
```

## 1. Check the authentication challenge

A working browser session over HTTPS does not prove Docker token authentication works. An anonymous pull can also succeed without exercising the token flow at all.

From the client network you will push from, request `/v2/` without credentials and read the `WWW-Authenticate` header. The token realm's host, port, and scheme must all be reachable from that same client. Harbor can advertise an HTTP realm while the private ingress serves only HTTPS.

If the realm and the endpoint disagree, stop. Do not change Harbor's `externalURL` or turn off TLS verification to test a theory.

## 2. Log in, push, and pull

Use Docker's interactive prompt or a credential helper:

```sh
mise exec -- docker login registry.<tailnet-name>.ts.net
mise exec -- docker tag <source-image>:<tag> registry.<tailnet-name>.ts.net/<project>/<image>:<tag>
mise exec -- docker push registry.<tailnet-name>.ts.net/<project>/<image>:<tag>
mise exec -- docker pull registry.<tailnet-name>.ts.net/<project>/<image>:<tag>
```

In automation, read the credential from an approved secret manager and pass it with `--password-stdin`. Never put a token on the command line, in shell history, or in a manifest.

A successful login proves authentication only. To prove storage works, push, pull back, and compare digests.

## Pushing through a local tunnel

Sometimes a separately approved local port-forward is the only route. Use a registry client that runs natively on the host so the upload endpoint and the token realm share one network namespace. A Docker engine inside a VM may not share the host's loopback.

1. Keep the forward running in the foreground.
2. Check the challenge before authenticating.
3. Use temporary credential storage.
4. Verify the pushed digest and architecture.
5. Stop the forward and remove only the files this run created.

The `deploy-owned-app` skill has the detailed host-client steps.

## When a push or pull fails

Decide which of these failed before changing either service:

| Layer | Evidence |
| --- | --- |
| DNS or route | The client cannot reach `/v2/` |
| Authentication | The challenge or token request fails |
| Project permissions | Authenticated, but denied for the project |
| Blob storage | Uploads or downloads fail after authentication |

For the last case, check Harbor and SeaweedFS status and events. Harbor's storage credentials come from Flux and External Secrets; do not edit the generated Secret. Reclaiming registry storage has its own inventory and safety gates.

## During node maintenance

Harbor's nginx front door runs two replicas, spread across nodes where possible, with a disruption budget that keeps one available during a voluntary eviction. That protects the front door only. Image blobs still live in SeaweedFS, so a maintenance window that stops S3 also stops pushes and cold pulls ([SeaweedFS node maintenance](seaweedfs.md#node-maintenance)).

To check continuity, pull a previously uncached private image by digest while one node is drained. A cached or anonymous pull does not exercise the path.

The registry and `registryctl` containers carry explicit resource requests, sized from a bounded seven-day observation. Requests reserve scheduling capacity; they are not a measure of use. `scripts/check-harbor-resource-contract.py` renders the pinned chart and confirms the values reach the containers.

The `anton-cluster-health` skill holds the full [continuity check](https://github.com/wcygan/anton/blob/main/.agents/skills/anton-cluster-health/references/harbor-continuity.md) and [resource contract](https://github.com/wcygan/anton/blob/main/.agents/skills/anton-cluster-health/references/critical-resource-contracts.md). A NetworkPolicy limiting ingress to Harbor's PostgreSQL is staged for review but not active; see [internal service boundaries](https://github.com/wcygan/anton/blob/main/.agents/skills/anton-cluster-health/references/internal-service-boundaries.md).
