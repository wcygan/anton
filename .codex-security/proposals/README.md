# Edge egress proposals

These are reviewed source proposals, **not deployed policies**. They are outside
`kubernetes/` and are not referenced by Flux. Do not `kubectl apply` them.
They address lateral movement after an independently compromised edge pod;
they do not establish or fix an initial Internet compromise.

| Selected workload | Allowed destinations |
| --- | --- |
| cloudflared | CoreDNS TCP/UDP 53; external Envoy TCP 10443; the 20 published global Cloudflare IPv4 tunnel endpoints TCP 7844 |
| external Envoy | CoreDNS TCP/UDP 53; Envoy Gateway xDS TCP 18000; bakery/food-site TCP 8000; homepage/CS2Plant TCP 3000; echo TCP 80; Flux webhook TCP 9292 |

The exact pod labels, Service target ports, public HTTPRoute backends, and
readiness were observed through the verified Anton context on 2026-09-29.
CS2Plant's route and workload are managed outside this repository, so they must
remain in the inventory and be rechecked before rollout. No SecurityPolicy or
EnvoyExtensionPolicy was present at that observation time; new external auth,
tracing, rate limiting, WASM, or backend dependencies need explicit exceptions.

Cloudflare destinations come from its [firewall documentation](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/).
The current HelmRelease selects HTTP/2 and disables auto-update. This proposal
does not allow optional external HTTPS, QUIC, IPv6, or US-region endpoints. Before
rollout, confirm effective tunnel configuration, including provider-side
overrides, and absence of origin-side Access JWT validation that needs HTTPS.
Recheck endpoint addresses on cloudflared upgrades. If those features become
required, add narrow destination exceptions before changing tunnel settings.

## Rollout and acceptance

Follow [ADR 0029](../../context/adrs/0029-restore-pod-security-isolate-public-workloads.md):
one workload at a time, with positive and negative traffic checks before
expanding. The exact test workload/command needs operator approval under
`AGENTS.md`; no debug pod, exec, synthetic traffic, or force reconcile is
authorized by these files.

1. Confirm current labels, all public routes, target ports, other additive
   Kubernetes/Cilium policies, and effective tunnel/xDS dependencies. Obtain
   the provider-side tunnel, Access, WAF, and DNS review without copying tokens.
2. For cloudflared only, copy its policy into
   `kubernetes/apps/network/cloudflare-tunnel/app/networkpolicy.yaml`, removing
   the draft comment. Add it to that app's `kustomization.yaml`; validate and
   commit. Let Flux reconcile naturally.
3. Verify the source revision, applied policy, both replicas ready, no new
   restarts/events, DNS and tunnel connections, public routes, and metric
   scraping. Approved negative checks must reject direct Headlamp, Kubernetes
   API, internal Envoy, and unrelated workload access from a selected pod.
   A ready pod alone does not prove enforcement.
4. Only after that acceptance, move/wire the Envoy policy into the Envoy Gateway
   app. Verify xDS reconnects, all six public backends, probes and metrics,
   blocked private destinations, and existing Tailscale Headlamp access/login.
   Test established and new connections; retain sanitized evidence privately.

Watch each rollout for at least ten minutes; stop immediately on unexpected
restart, readiness, tunnel, route, or scrape failure. Roll back at the Git owner
by removing that policy's Kustomize entry and policy file in a normal commit.
Observe Flux pruning it and restoration of the previously working paths.
Emergency live removal remains an explicitly approved mitigation.

These policies select pods rather than the entire privileged `network`
namespace. They leave incoming traffic unchanged and do not isolate host-network
or node-origin traffic. Kubernetes policies are additive; an overlapping allow
policy can widen egress. DNS and authorized upstreams remain permitted channels.
Router NAT, UPnP, IPv6 firewall, NodePorts, and direct-origin ingress require a
separate external-network review.
