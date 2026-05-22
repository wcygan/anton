---
name: debug-flux-reconciliation
description: Ordered Flux reconciliation triage for Anton. Use when a Kustomization, HelmRelease, GitRepository, OCIRepository, HelmRepository, SOPS decryption, postBuild substitution, dependency, or Flux sync is stuck or not progressing.
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
4. Describe the first failing object.
5. Check SOPS decryption and postBuild substitutions.
6. Propose a safe reconcile order if the source is stale.

## Commands

```sh
flux get sources git -A
flux get sources oci -A
flux get sources helm -A
flux get ks -A
flux get hr -A
kubectl -n <namespace> describe kustomization <name>
kubectl -n <namespace> describe helmrelease <name>
```

For SOPS issues:

```sh
find . -name '*.sops.*' -not -name '.sops.yaml' -not -path './.private/*' -exec sops filestatus {} \;
```

For substitution issues, inspect the failing `ks.yaml`, then check the `cluster-secrets` source referenced by `postBuild.substituteFrom`.

## Reconcile Handoff

Use this order when the operator approves a force reconcile:

```sh
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization flux-system -n flux-system --with-source
flux reconcile kustomization <name> -n <namespace> --with-source
flux reconcile helmrelease <name> -n <namespace>
```

Name the exact resource and namespace before running any reconcile command.
