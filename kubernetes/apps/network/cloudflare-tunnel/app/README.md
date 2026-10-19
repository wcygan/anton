# Cloudflared outbound isolation

`networkpolicy.yaml` restricts connections started by cloudflared. It selects
only cloudflare-tunnel pods in the `network` namespace and leaves incoming
traffic unchanged, including health probes and Prometheus scrapes.

Allowed connections:

| Destination | Protocol and destination port |
| --- | --- |
| CoreDNS pods in `kube-system` | UDP/TCP 53 |
| External Envoy pods in `network` | TCP 10443; the Envoy Service exposes 443 |
| Public IPv4 destinations | TCP 7844 for the HTTP/2 tunnel; TCP 443 for optional HTTPS features |

The Internet rule excludes private, shared, loopback, link-local, documentation,
benchmark, multicast and reserved IPv4 ranges. The current pod, Service, node,
LAN and tailnet ranges are covered by these exclusions. There is no IPv6 or
QUIC/UDP allowance. Revisit the policy before changing tunnel transport or
enabling IPv6.

This first stage preserves public HTTPS destinations to reduce compatibility
risk. It does not restrict those destinations to Cloudflare, prevent all data
exfiltration, or change external Envoy's own outbound access. Other matching
Kubernetes/Cilium allow policies could widen access; check them before rollout.
The older, stricter `.codex-security/proposals/cloudflare-tunnel-egress.yaml`
remains an inactive alternative, not the source used by this app.

## Local verification

From the repository root:

```sh
mise exec -- python3 -m unittest scripts.tests.test_cloudflare_tunnel_egress scripts.tests.test_edge_egress_proposals -v
mise exec -- task contracts:validate
git diff --check
```

The fixtures check Kustomize inclusion, workload selection, DNS and origin
access, Internet ports, and rejection of unrelated/private destinations. They
evaluate the source rules; they do not prove Cilium packet handling, Service
translation, DNS behavior, or successful tunnel reconnection.

## Rollout checkpoint

Repository preparation does not authorize a push, reconcile, apply, restart,
audit-mode change or active connection test. Obtain operator approval for the
exact rollout and test operations before performing them. Baseline evidence
for this preparation is retained locally in `.private/cloudflared-egress/`.

Before rollout, verify the intended source revision, expected cluster context,
current workload labels, CoreDNS labels, Envoy's Service target port, tunnel
transport and all overlapping policies. Review baseline gaps before treating
the rollout as ready. Apply only this workload's policy through GitOps; do not
introduce external Envoy restrictions in the same rollout.

After an approved rollout:

1. Verify Flux's applied revision and the exact policy. Both cloudflared
   replicas must remain ready with no new restart or warning loop.
2. Check all public site addresses, application API features, a valid GitHub
   webhook delivery, existing LAN access and representative private services.
   A 404 at the webhook hostname's root does not prove delivery.
3. Verify both Prometheus scrape targets stay up and both tunnel replicas
   retain their expected connections. Resolve any pre-existing monitoring gap
   separately; do not call a missing target a passing check.
4. With separately approved operations, test fresh DNS/origin connections,
   reconnect each tunnel replica one at a time, and confirm blocked access
   from the selected workload to internal Envoy, Kubernetes API, storage and
   unrelated private workloads. A connection from an unselected debug pod is
   not proof that this policy works.
5. Observe for at least ten minutes after the last test. Remove any temporary
   test resources and audit settings; retain sanitized evidence.

Stop on a required connection failure, unexpected restart, readiness loss,
tunnel failure or scrape regression. Roll back at the Git owner by removing
the policy's Kustomize entry and file in an approved commit. Verify Flux prunes
the exact policy and the affected paths recover. Emergency live removal needs
explicit approval. Leave external Envoy's policy unchanged.

References: [Cloudflare firewall requirements](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/),
[ADR 0029](../../../../../context/adrs/0029-restore-pod-security-isolate-public-workloads.md).
