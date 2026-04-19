---
name: debug-flux-reconciliation
description: Triage a flux sync stuck in Anton. Ordered diagnostic path when flux is stuck, kustomization not progressing, HelmRelease failing, SOPS decryption error blocks sync, or dependency not ready. Force reconcile in safe dependency order.
allowed-tools: Read, Bash
---

# Debug a Flux reconciliation

Ordered triage skill. Walk top to bottom — the first step that reports an error is the one to fix. Order: **source → kustomization → helmrelease → describe → SOPS → postBuild → force reconcile**. If you're tempted to start with `kubectl rollout restart`, stop — the problem is almost always upstream of the workload.

## Step 1 — Is the GitRepository / OCI source healthy?

Flux cannot apply anything if the source artifact is broken or stale. Always start here.

```sh
flux get sources git -A
flux get sources oci -A
flux get sources helm -A
```

Look for `READY=False`. Common causes:
- **GitRepository fetch failing** → deploy key broken. Check the `flux-system` secret in namespace `flux-system` and compare fingerprints with the GitHub deploy keys UI. Rotation steps: `rotate-credential`.
- **OCIRepository auth failing** → registry rate-limit or registry-pull secret problem. `kubectl logs -n flux-system deploy/source-controller --tail=100 | rg <ocirepo-name>`.
- **HelmRepository index failing** → upstream repo down. Temporary; wait, or switch to OCIRepository.

If any source is stuck, **fix the source first** — every downstream Kustomization will look broken until the source is green.

## Step 2 — Which Kustomization is not progressing?

```sh
flux get ks -A --status=all
flux get ks -A --status=all | rg -v 'Applied revision'   # only the broken ones
```

Look for `READY=False` or no revision advance. The status message usually says which resource failed. Common messages:

| Message fragment | Cause | Next step |
| --- | --- | --- |
| `dependency <name> is not ready` | a `dependsOn` target is still failing | go fix THAT ks first; this one will recover on its own |
| `Kustomization apply failed: ...` | manifest invalid or API-server rejected | `kubectl describe kustomization -n flux-system <name>` for full error |
| `failed to decrypt ... sops` | SOPS problem | jump to Step 5 |
| `YAML has not been tagged ...` | stale cache | `flux reconcile ks <name> -n flux-system --with-source` |
| `variable substitution failed: key "<VAR>" not found` | missing key in `cluster-secrets` | jump to Step 6 |

## Step 3 — Which HelmRelease is failing?

```sh
flux get hr -A --status=all
flux get hr -A --status=all | rg -v 'Release reconciliation succeeded'
```

Common HelmRelease failure shapes:

| Message fragment | Cause | Fix |
| --- | --- | --- |
| `chart not found` / `source not ready` | OCIRepository `metadata.name` ≠ HelmRelease `spec.chartRef.name` | align names; both must match the app |
| `install retries exhausted` | chart install keeps failing — upstream schema change or bad values | `kubectl describe hr -n <ns> <name>` for the actual chart error |
| `upgrade retries exhausted` | values change broke the chart | revert the values change; fix; retry |
| `post-renderer failed` | postBuild variable missing | Step 6 |

## Step 4 — `kubectl describe` the failing resource

If Steps 1–3 named a specific resource (Kustomization or HelmRelease), describe it for the full event stream:

```sh
kubectl describe kustomization -n flux-system <name>
kubectl describe helmrelease -n <ns> <name>
```

Also look at controller logs:

```sh
kubectl logs -n flux-system deploy/kustomize-controller --tail=100 | rg <name>
kubectl logs -n flux-system deploy/helm-controller     --tail=100 | rg <name>
```

The error message on the CR's status is a summary; the controller logs have the real stack trace.

## Step 5 — SOPS decryption errors

Symptom: `failed to decrypt secret` or literal `data: ENC[AES256_GCM,...]` appearing in a Secret that reached the cluster.

Checks (in order):
1. `kubectl get secret -n flux-system sops-age -o yaml | rg age.agekey` — the secret exists. If missing, Flux has no way to decrypt anything.
2. Pull the Age recipient from the secret and compare to `.sops.yaml`:
   ```sh
   kubectl get secret -n flux-system sops-age -o jsonpath='{.data.age\.agekey}' | base64 -d | age-keygen -y
   grep -E 'age: ' .sops.yaml
   ```
   If they disagree, Flux is holding an old/wrong private key — rotate via the `rotate-credential` skill.
3. Confirm the failing file is actually SOPS-encrypted locally:
   ```sh
   SOPS_AGE_KEY_FILE=./age.key sops filestatus <path-to-file>
   ```
   If `unencrypted`, run `SOPS_AGE_KEY_FILE=./age.key sops -e -i <path-to-file>` to encrypt in place, then commit and push.

## Step 6 — postBuild variable substitution failed

Symptom: a literal `${SECRET_DOMAIN}` (or any `${VAR}`) lands in a deployed object, OR Flux reports `variable substitution failed: key "<VAR>" not found`.

Two possible causes:
1. The `ks.yaml` is missing `postBuild.substituteFrom`. Grep the failing app:
   ```sh
   rg -n 'substituteFrom' kubernetes/apps/<ns>/<app>/ks.yaml
   ```
   If empty, add the block (see `add-flux-app` or `anton-repo-conventions`).
2. The namespace kustomization is missing the SOPS component, so `cluster-secrets` never reaches the app's namespace:
   ```sh
   rg -n 'components/sops' kubernetes/apps/<ns>/kustomization.yaml
   ```
   Add `components: [../../components/sops]` if missing.
3. The variable is genuinely missing from `cluster-secrets`. Read the current set:
   ```sh
   SOPS_AGE_KEY_FILE=./age.key sops --decrypt \
     kubernetes/components/sops/cluster-secrets.sops.yaml
   ```
   If the key isn't there, add it via `sops` in-place edit, commit, reconcile.

## Step 7 — Force reconcile in dependency order

Only after the underlying fix is pushed. Never force-reconcile a HelmRelease that depends on a broken source — fix top-to-bottom:

```sh
flux reconcile source git flux-system                                # newest git revision
flux reconcile kustomization <name> -n flux-system --with-source     # re-apply manifests
flux reconcile helmrelease <name> -n <ns>                            # re-upgrade chart
```

The `--with-source` flag on step 2 is what most "force reconcile" one-liners miss — without it you re-run the same stale artifact.

## Quick-symptom decision table

| Symptom | Most likely step |
| --- | --- |
| "Flux is stuck, nothing is updating" | Step 1 |
| "Just this one Kustomization is `ReconcilePending`" | Step 2 → look for `dependsOn` |
| "HelmRelease shows `Ready=False` with `chart not found`" | Step 3 → name mismatch |
| "`${SECRET_DOMAIN}` showed up literally in a deployed HTTPRoute" | Step 6 |
| "Secret is encrypted bytes in the cluster" | Step 5 |
| "New commit is pushed but Flux is still on the old revision" | Step 7 (reconcile source) |
| "App was listed in namespace kustomization but never appeared" | `kubernetes/apps/<ns>/kustomization.yaml` missing the `./<app>/ks.yaml` line — not a Flux bug, a config gap |

## Related skills

- Fixing the authoring problem once diagnosed → `anton-repo-conventions`, `add-flux-app`, `expose-service`
- SOPS or deploy-key rotation when the decryption/source auth is the root cause → `rotate-credential`
- Reaching the cluster from off-LAN to run these commands → `anton-remote-access`
