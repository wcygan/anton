# Reconciliation-only admission guard

This guard is deployed in two verified stages: policy, then enforcement. Both
`network/cloudflare-tunnel-egress` and `network/envoy-external-egress` stay in
place, including during any later rollback.

The existing restricted account can still patch the whole configuration of its
two permitted Flux objects. This guard closes that gap at the Kubernetes API:
the controller can request reconciliation, but cannot change what Flux deploys.

## Behavior

Add a built-in `ValidatingAdmissionPolicy` and Deny binding, both named
`notification-controller-reconcile-only`, to the existing Flux app. No additional
admission service, controller restart, RBAC change, credential rotation, or
network-policy change is included.

The policy matches only user
`system:serviceaccount:flux-system:notification-controller-restricted`, namespace
`flux-system`, and updates to GitRepository `flux-system` or Kustomization
`flux-system`, including their status subresources. PATCH is UPDATE for admission.
Equivalent API versions are matched.

| Attempt by that controller | Result |
| --- | --- |
| Add/change `reconcile.fluxcd.io/requestedAt` | Allow a non-empty value of at most 128 characters |
| Preserve an existing valid request without changing anything | Allow |
| Change Git URL, branch, manifest path, pruning, suspension, source reference, or other configuration | Deny |
| Bundle configuration changes with a valid reconciliation annotation | Deny |
| Add, remove, or change another annotation | Deny |
| Change labels, finalizers, owners, identity, or other protected metadata | Deny |
| Change status or another top-level field | Deny |
| Update a status subresource | Deny; existing RBAC also denies this |
| Remove, empty, or oversize the request annotation | Deny |
| Access another target or namespace | Existing RBAC denies it; this policy grants no permissions |

Resource versions and `managedFields` ownership bookkeeping are exempt from the
metadata comparison because Kubernetes can update them while processing a valid
annotation change. This does not permit changing configuration, status, labels,
owners, finalizers, or other annotations.

The guard compares all object fields rather than listing today's spec fields.
Both-direction comparisons catch additions, removals, and nested changes.
The comparisons use CEL `dyn` for map iteration: schema-aware checking treats
the root and metadata as objects, while admission evaluation supplies dynamic
JSON maps. The suite checks both typed compilation and runtime evaluation;
live denial tests remain required before declaring enforcement verified.
Normal Flux controllers and your administrative identity are excluded by the
exact username condition, and retain their existing permissions. The old
notification-controller account is excluded too, preserving rollback options.

`failurePolicy: Fail` and `validationActions: [Deny]` reject failed validations or
evaluation errors for matching requests. There are no label selectors or external
parameters the account can change to evade the guard. Its existing Role does not
permit changing the policy or binding.

## Files

- `notification-admission.yaml`: policy and enforcement binding.
- `kustomization.yaml`: include them in the existing app.
- `ADMISSION.md` and `README.md`: boundary, verification, and recovery.
- `scripts/tests/notification_admission/admission_test.go`: evaluate the actual
  YAML expressions with Kubernetes v1.36.0's CEL compiler and admission library.
- `scripts/tests/notification_admission/go.mod` and `go.sum`: pinned test dependencies.
- `scripts/tests/notification_admission/probe.py`: in-cluster probe;
  every target PATCH uses `dryRun=All`.
- `scripts/tests/notification_admission/probe-pod.yaml`: temporary diagnostic
  fixture, outside all Flux resources. Create only for an approved live test.

## Local checks

Read-only inspection found Kubernetes v1.36.0, both admission v1 APIs, the
expected restricted controller identity, and both existing network restrictions.

From the repository root:

```sh
cd scripts/tests/notification_admission
mise exec -- go test -v ./...
mise exec -- go mod verify
```

This separate module needs Go 1.26 or newer and downloads its pinned dependencies
on the first run. It changes no cluster runtime. These are additional explicit
tests; `task contracts:validate` does not run the Go suite.

The suite reads the policy itself and tests both object types: valid requests,
missing/null annotations, server bookkeeping, nested configuration changes,
mixed attacks, metadata/status changes, malformed input, and unaffected controller
and operator identities. It checks exact resource/name/operation scope, lack of
selector bypasses, Fail/Deny settings, and Kustomize inclusion. Evaluation errors
are distinguished from ordinary denials.

The optional `NOTIFICATION_ADMISSION_FIXTURES` environment variable accepts a JSON
array of read-only snapshots of the two targets. This was used during preparation
to test their actual shapes. Runtime snapshots remain ignored.

Also run from the repository root:

```sh
mise exec -- python3 -m py_compile scripts/tests/notification_admission/probe.py
mise exec -- kustomize build kubernetes/apps/flux-system/flux-instance/app >/dev/null
mise exec -- task contracts:validate
```

Local tests do not prove installation or running API-server enforcement.
Policy type-checking status alone is also insufficient for Flux custom-resource
behavior. The following live tests remain required after deployment approval.

## Staged deployment and live tests

Use this staged rollout only with publication, deployment, and live-test
authorization. Repository validation alone does not authorize cluster changes.

1. Capture the verified Tailscale operator context, Git/Flux revisions, controller
   identity/readiness, receiver-path fingerprint, target annotations, and both
   network-policy UIDs/specs. Require a working webhook and application baseline.
2. Publish the **policy alone**, without its binding. Verify the applied spec,
   UID/generation, and any evaluation/type warnings. Re-run the CEL suite on the
   exact published revision. This stage has no enforcement effect.
3. Publish the Deny binding, then verify its target policy and applied revision.
   The proposal contains both YAML documents for review; publication must split
   them into these two observed stages. Do not activate a mismatched policy or
   one with known warnings. No controller restart is needed.
4. Create exactly one temporary Pod, `flux-system/notification-admission-check`,
   from the reviewed fixture. It uses the existing restricted service account,
   a pinned Python image, a read-only root filesystem, no added capabilities or
   host access, and a five-minute deadline. Its normal projected API token stays
   inside the pod; do not copy it out.
5. Feed `probe.py` to Python in that pod. It verifies its native API identity,
   then sends one allowed annotation patch and seven forbidden patches per
   target, **all with `dryRun=All`**. Require HTTP 200 for the allowed patch and
   HTTP 403 naming this exact policy for every forbidden patch. A schema error,
   generic RBAC denial, proxy response, or wrong identity is not guard evidence.
   Re-read the targets to confirm no requests persisted. Concurrent legitimate
   changes make the comparison inconclusive; repeat in a quiet window.
6. From your operator context, dry-run another annotation update that would be
   forbidden to this controller, and require success. This verifies the operator
   exemption. Do not test the controller with `kubectl --as` through Tailscale:
   its proxy replaces impersonation headers. Preparation found no direct
   `admin@anton` context, which is why a native service-account pod is specified.
7. Redeliver a signed GitHub push after activation. Require HTTP 200 and fresh
   annotations handled by both targets with Ready status. An invalid signature
   must return HTTP 400 without reconciliation. Keep token and endpoint path
   out of output.
8. Verify a subsequent real Git revision reconciles normally: source, Helm,
   FluxInstance, Kustomizations, releases, and image automation remain healthy.
   Check public sites, the original FACEIT matchroom, LAN access, monitoring,
   restarts, and both policy UID/spec matches. Observe ten minutes without
   unexpected admission denials.
9. Delete the exact temporary pod, including on failure, and verify absence.
   Its deadline stops execution but does not remove the object. No test Job,
   ConfigMap, token Secret, or debug container is needed or should remain.

Reviewed future commands, run from the configured Anton checkout:

```sh
# Only after authorization; use absolute paths to the reviewed files.
mise exec -- kubectl create -f /absolute/path/probe-pod.yaml
mise exec -- kubectl -n flux-system wait --for=condition=Ready pod/notification-admission-check --timeout=90s
mise exec -- kubectl -n flux-system exec -i notification-admission-check -- python3 - </absolute/path/probe.py
# Required cleanup, including on failure.
mise exec -- kubectl -n flux-system delete pod notification-admission-check --wait=true --timeout=60s
```

Target updates are dry runs; Pod creation and exec are live diagnostic mutations
that require deployment/test approval. Neither network policy needs changing.

## Stop and rollback

Stop at unexpected denials, failed valid delivery, readiness loss, unexpected
configuration changes, or an unverified test identity. An accepted forbidden
dry run fails acceptance but does not persist a dangerous configuration.
Do not relax RBAC or a network policy to make tests pass.

Revert **the binding first**, through Git. Keep the unbound policy, restricted
account, RBAC, and both network restrictions in place. Normal source and kustomize
controllers are excluded from the guard, so they can apply the rollback even
when webhook annotation is blocked. The source polls Git every minute; it does
not depend only on webhook delivery.

If prompt recovery needs a force reconcile, the exact proposed operator command
is `mise exec -- flux reconcile source git flux-system -n flux-system`, from the
verified context, followed by observing the owning Kustomization. That is a
separately approved live mutation. Only after the binding is absent and signed
delivery works should an unused policy be removed.

## Basis and limits

[Kubernetes admission-policy documentation](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)
describes actor conditions, Equivalent matching, Fail/Deny, and CEL. Tests use
the v1.36.0 admission library matching the observed cluster version. Live API
dry runs and webhook delivery remain the final acceptance checks.

The guard does not authenticate GitHub by itself, grant API rights, stop repeated
reconciliation requests, or protect other workloads after an unrelated compromise.
Existing signature validation, narrow RBAC, and network restrictions remain needed.

## Deployment verification, 2026-10-19 UTC

The policy was installed without enforcement first. Schema checking caught
typed-object map iteration; explicit `dyn` comparisons corrected it before the
binding was added. The corrected policy reported its current generation with
zero expression warnings. A typed-compilation regression test now catches the
original mistake alongside the runtime admission tests.

With the Deny binding active, the native restricted-account probe allowed both
annotation-only dry runs and rejected all fourteen forbidden dry runs with
HTTP 403 naming this policy. Neither target's configuration or annotations
changed during the probe. Operator annotation dry runs succeeded. The exact
temporary test pod was deleted and its absence verified.

A signed GitHub push redelivery returned HTTP 200 and both targets handled fresh
reconciliation requests. An invalid signature returned HTTP 400 with a matching
Flux validation error and no target changes. The network restrictions retained
their existing UIDs and specifications. Continued workload observation and a
subsequent Git revision are separate acceptance checks for this rollout.

Boundary Discipline put validation at the API that accepts the write. Build the
Lever produced rerunnable CEL tests and a dry-run probe. Prove It Works required
the actual Kubernetes CEL engine, typed compilation, current object shapes,
and native service-account API requests for live enforcement evidence.
