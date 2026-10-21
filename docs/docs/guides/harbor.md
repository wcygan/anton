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
