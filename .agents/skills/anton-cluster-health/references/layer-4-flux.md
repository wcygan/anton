# Layer 4 — Flux

Flux is GitOps. If any controller in `flux-system` is down, the reconciliation engine is blind. If the root Kustomization `flux-system/flux-system` is stuck, nothing downstream will update.

## Controllers

Anton runs the four standard Flux controllers:

```sh
flux check
kubectl -n flux-system get pods
```

Expected pods (all `Running`, `1/1`, zero recent restarts):
- `source-controller` — pulls Git/OCI/Helm artifacts
- `kustomize-controller` — applies Kustomizations (this is where SOPS decryption happens)
- `helm-controller` — reconciles HelmReleases
- `notification-controller` — webhook + alerts

**If `flux check` fails**: read the stderr carefully. A CRD version skew surfaces here.

## Root Kustomization

```sh
flux -n flux-system get ks flux-system
```

This is the Kustomization that defines *all other* Kustomizations. If it is `Ready=False`, the tree is frozen — no app gets updates until you fix this one.

## Sources

```sh
flux get sources git -A
flux get sources oci -A
flux get sources helm -A
```

**Healthy**: all sources `Ready=True`, recent revisions, no error suffix in the status column.

**Common failures**:
- `git` source `Ready=False` with `authentication required` — deploy key expired or revoked. Hand off to `rotate-credential`.
- `oci` source `Ready=False` with `manifest unknown` — the referenced tag was deleted upstream; the HelmRelease is pinning a missing version
- `helm` source slow but not failing — upstream repository is rate-limiting; usually self-heals

## Finding stuck reconciliations (fast)

```sh
# Everything that is not Ready
flux get ks -A --status-selector ready=false
flux get hr -A --status-selector ready=false
```

For each row returned, walk the dependency chain upward:

```sh
flux -n <namespace> describe ks <name>
flux -n <namespace> describe hr <name>
```

## SOPS decryption errors (the silent killer)

kustomize-controller reports a failed decryption as a Kustomization status condition. It looks like:

```
Status: False
Reason: BuildFailed
Message: failed to decrypt secrets.sops.yaml: ... failed to create sops data key ...
```

**Root causes**:
1. The `age.key` in `flux-system/sops-age` Secret doesn't match the age recipient in `.sops.yaml`
2. The SOPS file was committed unencrypted
3. `age.key` was rotated but not propagated — hand off to `rotate-credential`

**Verify the Flux-side Secret exists**:

```sh
kubectl -n flux-system describe secret sops-age
```

`kubectl describe secret` prints key names and byte counts without exposing the private key. If the Secret exists but decryption still fails, hand off to credential rotation or operator-approved key inspection outside Codex.

## postBuild substitution errors

Every app Kustomization in this repo uses `postBuild.substituteFrom: cluster-secrets`. If that Secret is missing or out of sync, the Kustomization fails with:

```
variable substitution failed: cluster-secrets not found
```

```sh
# Verify the Secret exists and has keys without printing values
kubectl -n flux-system describe secret cluster-secrets
```

If `cluster-secrets` is missing entirely, something deleted it. It is defined in `kubernetes/components/sops/cluster-secrets.sops.yaml` and created by the root Kustomization.

## When to hand off

A Flux-layer fix usually requires force-reconcile in a specific order (source → ks → hr). Stop here and call `debug-flux-reconciliation` — it owns the mutation path.
