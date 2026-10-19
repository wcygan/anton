# Notification-controller outbound restrictions

`notification-egress.yaml` selects only the notification-controller component
in this namespace. The existing ingress policy, restricted service account,
and reconciliation-only admission guard remain unchanged.

Allowed outbound connections:

- CoreDNS pods in `kube-system`, with `k8s-app=kube-dns`, on UDP/TCP 53.
- Cilium's `kube-apiserver` identity on TCP 6443. The Kubernetes Service uses
  port 443 and Cilium translates it to API endpoints on 6443.
- Tracked replies to incoming webhook, event, and monitoring connections.

Other new outbound connections are denied, including unrelated cluster services,
LAN destinations, and public HTTPS. API identity follows endpoint changes without
committing node addresses. It does not allow arbitrary ports on API nodes.
The owning Flux Kustomization depends on the existing Cilium installation.

There are no notification Providers or Alerts at rollout time. Adding an outbound
notification destination requires a reviewed egress exception first. Incoming
GitHub webhooks do not need outbound GitHub access. DNS and restricted Kubernetes
API permissions remain necessary; this does not prevent every action a compromised
process could perform through those permitted channels.

## Verification

Run from the repository root:

```sh
mise exec -- python3 -m unittest discover -s scripts/tests -p test_notification_egress.py -v
mise exec -- kustomize build kubernetes/apps/flux-system/flux-instance/app >/dev/null
mise exec -- task contracts:validate
```

Source checks constrain destination identities, ports, selection, Flux wiring,
and existing ingress. API-server dry-run validation checks the installed Cilium
CRD schema. Neither proves packet enforcement.

Before an approved rollout, capture the current controller, API EndpointSlices,
DNS Service, receiver-path fingerprint, admission policy/binding, and both edge
network-policy UIDs/specifications. Require a working webhook and Flux baseline.
Confirm Cilium recognizes the API-server identities.

Use `scripts/tests/notification_egress/probe-pod.yaml` only for an approved test.
It has no API token, reads only the public cluster CA, and matches this outbound
policy. Its different `app` label prevents production notification/webhook Services
from selecting it. Confirm their selectors first. Place it on the controller's
node when comparing before and after.

Run `probe.py` over stdin with `python3 - CONFIG_JSON before|after`. Supply discovered
addresses in that JSON argument; keep them outside Git. The probe makes fresh
connections, verifies API TLS against the cluster CA, queries UDP/TCP DNS, and
reads no application data from unrelated services. Require successful connections
before restricting them. Afterward, require API/DNS success and timeouts for
forbidden destinations. Use Cilium endpoint state and Hubble policy-denied events
to distinguish enforcement from unavailable destinations.

After natural Flux reconciliation, verify applied policy and endpoint rules,
signed GitHub delivery, fresh requests handled by both targets, invalid-signature
rejection, monitoring, leadership, and a subsequent Git revision. Exercise fresh
API connections and a controlled controller replacement to prove cache/watch/lease
startup after reconnection. Wait for readiness and recheck signed delivery. Check
public sites, FACEIT, LAN, and ten minutes of stability. Keep both edge policy
UIDs/specifications and admission policy/binding intact. Delete the exact probe
pod on success or failure and verify absence; its deadline does not delete it.

## Recovery

If required connectivity, delivery, monitoring, leadership, or readiness fails,
revert only the new Cilium policy and its Kustomize inclusion through Git.
Keep the ingress policy, restricted identity, admission guard, and both edge
restrictions. Exempt Flux controllers can deliver rollback through source polling
even if notification-controller cannot reconnect. Do not broaden other protections.

Basis: [Cilium entity policies](https://docs.cilium.io/en/stable/security/policy/layer3/).
Verification uses the installed Cilium 1.20.2 implementation.

Build the Lever supplied the reusable probe and source checks. Prove It Works
requires observed packet denials and production delivery after reconnection.
