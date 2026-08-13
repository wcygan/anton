---
name: debug-flux-reconciliation
description: Ordered Flux reconciliation triage for Anton. Use when a Kustomization, HelmRelease, source, SOPS decryption, postBuild substitution, dependency, Helm timeout, rollback, cleanup, hook, or immutable Job is stuck.
---

# Debug Flux Reconciliation

Goal: Diagnose stuck Flux reconciliation from source artifact to workload dependency.

Success means:
- The first failing Flux object is identified.
- SOPS, postBuild, source, and dependency failures are separated.
- Reconcile commands are proposed in safe order and run only with operator approval.

Stop when: the stuck layer is named and the next correction is clear.

## Ordered Triage

1. Check sources.
2. Check Kustomizations.
3. Check HelmReleases.
4. Classify Helm remediation when timeout, cleanup, rollback, hooks, or Jobs appear.
5. Describe the first failing object.
6. Check SOPS decryption and postBuild substitutions.
7. Propose a safe reconcile order if the source is stale.

Read [helm-remediation-deadlocks.md](references/helm-remediation-deadlocks.md)
for Helm timeout, cleanup, rollback, hook-cycle, or immutable Job symptoms.

## Commands

```sh
mise exec -- flux get sources git -A
mise exec -- flux get sources oci -A
mise exec -- flux get sources helm -A
mise exec -- flux get ks -A
mise exec -- flux get hr -A
mise exec -- kubectl -n <namespace> describe kustomization <name>
mise exec -- kubectl -n <namespace> describe helmrelease <name>
```

For SOPS issues:

```sh
mise exec -- find . -name '*.sops.*' -not -name '.sops.yaml' \
  -not -path './.private/*' -exec sops filestatus {} \;
```

For substitution issues, inspect the failing `ks.yaml`, then check the `cluster-secrets` source referenced by `postBuild.substituteFrom`.

## Reconcile Handoff

Use this order when the operator approves a force reconcile:

```sh
mise exec -- flux reconcile source git flux-system -n flux-system
mise exec -- flux reconcile kustomization flux-system -n flux-system --with-source
mise exec -- flux reconcile kustomization <name> -n <namespace> --with-source
mise exec -- flux reconcile helmrelease <name> -n <namespace>
```

Name the exact resource and namespace before running any reconcile command.
