# GitHub webhook permissions

This document describes the restricted identity and its rollout acceptance checks.
Keep `network/cloudflare-tunnel-egress` and `network/envoy-external-egress`
applied throughout preparation, rollout, verification, and rollback.

The public webhook receiver currently runs as `notification-controller`, which
inherits the shared `crd-controller-flux-system` ClusterRole. That role can read
Secrets across the cluster and broadly modify Flux resources. The proposal gives
only this Deployment a separate identity and a namespaced Role. The shared role,
its bindings, and the other Flux controllers stay unchanged.

## Exact source changes

| File | Proposed change |
| --- | --- |
| `notification-rbac.yaml` | Add ServiceAccount, Role, and RoleBinding named `notification-controller-restricted` in `flux-system`. |
| `kustomization.yaml` | Include those three objects in the existing Flux app. |
| `helmrelease.yaml` | Patch only the notification-controller Deployment to use the new identity, watch its own namespace, reject cross-namespace references, disable Secret caching, and disable Secret change watchers. |
| `receiver.yaml` | Set a one-minute reconciliation interval for checking the existing webhook token. Keep type, accepted events, token reference, and both targets unchanged. |
| `scripts/check-notification-permissions.py` | Check the allow/deny matrix and optionally compare the complete before/after controller renders. Kubernetes authorization queries only when explicitly run with `--live`. |
| `scripts/tests/test_notification_permissions.py` | Test the boundary and reject accidental permission broadening. |

JSON Patch tests guard the existing service account and argument positions. If a
future Flux distribution changes that layout, rendering must fail for review
rather than patch a different argument. No images, Services, routes, DNS records,
network policies, webhook credentials, or other controller settings are changed.

## Allowed actions

All resource permissions below apply only within `flux-system`.

| Resource | Allowed actions | Why |
| --- | --- | --- |
| Secret `github-webhook-token-secret` | `get` | Validate webhook signatures and compute the receiver path. |
| Receivers, Alerts, Providers | `get`, `list`, `watch` | Start the controller's namespaced caches. There are currently no Alerts or Providers. |
| Receiver `github-webhook`, including its status | `patch`, `update` | Maintain receiver readiness, status, and finalizers. |
| GitRepositories and Kustomizations | `get`, `list`, `watch` | The pinned controller's metadata client uses an informer even for named targets. |
| GitRepository `flux-system` | `patch` | Request source reconciliation. |
| Kustomization `flux-system` | `patch` | Request configuration reconciliation. |
| Lease `notification-controller-leader-election` | `get`, `update`, `patch` | Retain and renew controller leadership. |
| Leases | `create` | Recreate the leadership lease if absent. RBAC cannot restrict ordinary create requests by resource name. |
| Events | `create`, `patch` | Record normal controller events. |

Built-in authenticated-user API discovery permissions also remain, as for other
service accounts. The new account is not added to any cluster role binding.
The original controller account remains managed by the Flux distribution but is
no longer mounted into this Deployment.

## Blocked actions and remaining limits

The new identity cannot list or watch Secrets, read another Secret (including
`sops-age` or `cluster-secrets`), read workload Secrets in other namespaces, mint
service account tokens, create or modify permissions, execute in pods, or modify
HelmReleases or other Flux deployment targets. It cannot patch `auxiliary` or
objects outside `flux-system`. It cannot create or delete Receivers, Alerts, or
Providers. Adding another receiver or notification provider requires a deliberate
permissions review.

There are two important remaining powers:

- The controller can read **all** GitRepositories and Kustomizations in
  `flux-system`, because the existing cache lists and watches those types.
- The controller can still request repeated reconciliation of its two targets.
  RBAC permits whole-object patches, but the deployed admission guard rejects
  changes beyond the reconciliation annotation and Kubernetes bookkeeping.
  Configuration, status, other annotations, labels, finalizers, and owners are
  protected. See [ADMISSION.md](ADMISSION.md) for the exact boundary, live tests,
  and rollback procedure.

Secret watchers are disabled so the controller does not need collection access
to Secrets. The controller already reads the token directly when handling a
request. Receiver reconciliation checks the token approximately once per minute
instead of relying on Secret events; after an intentional token rotation,
receiver-path readiness can therefore take a minute plus scheduling delay.
No token rotation is included here. Existing webhook delivery and URL are
expected to be unchanged while the token stays unchanged.

## Evidence before applying

Inspection on 2026-10-19 UTC found notification-controller v1.9.4, one ready
Receiver (`flux-system/github-webhook`), no Alerts or Providers, the expected
leadership Lease, and no custom group binding that grants all service accounts
additional workload permissions. The GitHub hook remains active with TLS
verification enabled. The latest observed real push delivery returned HTTP 200,
and both intended Flux targets recorded that reconciliation request as handled.
This was a read-only check of existing delivery history, not a new delivery test.

The exact Flux Instance chart 0.60.0 and Flux Operator CLI 0.60.0 rendered the
proposal against distribution artifact
`sha256:5757dc8cb5a83a496421e9b2686d710c70dc0300521641c03a8970f7cd3f4522`
(Flux v2.9.5, notification-controller v1.9.4). Of 38 generated objects, only
notification-controller's service account and arguments changed. The three new
RBAC objects are owned by the existing application Kustomization, outside the
generated controller distribution.

Run the retained local permission check and focused tests from the repository root:

```sh
mise exec -- python3 scripts/check-notification-permissions.py
mise exec -- python3 -m unittest discover -s scripts/tests -p test_notification_permissions.py -v
mise exec -- task contracts:validate
```

For complete rendering, extract `spec.values` from the before/after HelmRelease
using `yq`, render the pinned `flux-instance` chart with `helm template`, and
extract its FluxInstance. Use the matching `flux-operator build instance -f FILE`
with the immutable artifact reference above. The CLI archive checksum must match
the upstream v0.60.0 checksums. Compare the resulting files with:

```sh
mise exec -- python3 scripts/check-notification-permissions.py \
  --rendered-before /absolute/path/controllers-before.yaml \
  --rendered-after /absolute/path/controllers-after.yaml
```

These checks prove source permissions and rendering. They cannot prove startup
under the new identity or actual webhook delivery before that identity is deployed.

## Proposed rollout and end-to-end checks

Publication, deployment, synthetic requests, and webhook redelivery require
operator authorization for the rollout.

1. Capture the current context, Flux revisions, controller pod/identity/readiness,
   receiver generation, both targets' reconciliation annotations, and both network
   policies' UIDs and specs. Record GitHub delivery IDs, not the webhook URL or
   Secret contents. Require the expected Tailscale operator context and a healthy
   webhook/controller baseline.
2. Publish only the new ServiceAccount/Role/RoleBinding and their Kustomize
   inclusion first. Wait for natural Flux reconciliation and read back their
   applied definitions. The running controller still uses its original identity.
   Check effective permissions with the retained checker
   (`--live --live-report /absolute/path/permissions.json`), run through
   `mise exec --` from the configured Anton checkout. It submits non-persisted
   SubjectAccessReviews with the explicit service account username and groups.
   Do not use `kubectl auth can-i --as` through the Tailscale proxy: the proxy
   replaces impersonation headers, so that check can report the operator
   identity's access instead. Cover the table above,
   including named token access, denied Secret collection access, cache reads,
   exact target patches, forbidden other targets, and forbidden namespaces.
   These are authorization checks; do not read Secret contents or try destructive
   writes to prove denial.
3. Publish the Deployment patch and receiver interval as a second change. Wait up
   to five minutes for the intended Flux/Helm/FluxInstance revision and a ready
   new pod running as `notification-controller-restricted`. Confirm leadership,
   Receiver Ready, unchanged receiver-path fingerprint, stable restart count,
   existing monitoring target up, and no persistent Forbidden/cache-sync errors.
   Stop at the first unexpected permission error.
4. **After the new identity is running**, redeliver one known valid GitHub push
   through the existing hook. Record its delivery ID/time/GUID and HTTP 200.
   Require fresh reconciliation-request annotations on **both** the GitRepository
   and Kustomization, followed by matching last-handled values and Ready status.
   A delivery that arrived before the new pod was running does not count.
5. Send one invalid-signature request with the established descriptive User-Agent
   to the existing endpoint, keeping its path out of output. Require HTTP 400
   from Flux plus a corresponding signature-validation error. Cloudflare HTTP
   403 is inconclusive. Neither target's reconciliation annotation may change
   because of that request; correlate any concurrent real delivery separately.
6. Repeat the effective-permission matrix against the identity actually in the
   ready pod. Verify both network policies retain their original UIDs/specs,
   both tunnel replicas stay connected, both Envoy replicas stay ready and
   connected to their controller, and all eight established public-site checks
   still pass. Check the original FACEIT matchroom as an application smoke test.
7. Observe for ten minutes with stable readiness, restarts, monitoring, and no
   new persistent authorization errors. Retain revision, delivery, annotation,
   permission, health, and unchanged-policy evidence. No debug pod, ephemeral
   container, or port-forward is required for this plan.

## Stop and rollback

Stop if the new pod fails readiness/leadership, API caches fail, the Receiver
becomes unready, a valid push fails or stops reconciling either target, an invalid
signature is accepted, or a required workload regresses. Do not widen permissions
in place as a diagnostic shortcut.

Revert the Deployment patch and receiver interval through Git first. **Keep the
new RBAC objects until the controller has returned to its original identity**;
otherwise the running restricted pod can lose permissions before replacement.
Wait for the restored revision, ready controller, working signed delivery, and
unchanged network policies. Only then remove unused proposal RBAC in a separate
revert if desired. No network policy rollback is part of this change.

## Design evidence

Pinned source: [controller startup](https://github.com/fluxcd/notification-controller/blob/v1.9.4/main.go),
[receiver reconciliation](https://github.com/fluxcd/notification-controller/blob/v1.9.4/internal/controller/receiver_controller.go),
[webhook handling](https://github.com/fluxcd/notification-controller/blob/v1.9.4/internal/server/receiver_handlers.go),
and [controller-runtime cache behavior](https://github.com/kubernetes-sigs/controller-runtime/blob/v0.24.1/pkg/client/client.go).

Build the Lever produced the reusable permission/render checker. Prove It Works
required rendering through the actual operator and separating local proof from
pending live webhook verification.
