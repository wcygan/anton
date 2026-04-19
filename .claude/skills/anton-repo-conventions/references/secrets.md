# Secrets — SOPS vs ExternalSecret

## Contents
- Decision matrix
- SOPS Secret template
- ExternalSecret template
- cluster-secrets.sops.yaml — the special one

Two systems coexist. Pick based on lifecycle and source.

## Decision matrix

| Need | Use | File location |
| --- | --- | --- |
| Static infra credential, rarely rotates, must be in git for bootstrap | SOPS Secret | `app/secret.sops.yaml` |
| Anything sourced from 1Password, rotating credentials, app passwords | ExternalSecret (ESO) | `app/externalsecret.yaml` |
| Cluster-wide variables (`SECRET_DOMAIN`, etc.) substituted via `${VAR}` | SOPS Secret named `cluster-secrets` | `kubernetes/components/sops/cluster-secrets.sops.yaml` |
| Bootstrap-phase secret (cilium, cert-manager, flux itself) | SOPS Secret | inside `bootstrap/` (different SOPS rules apply) |

The default for a brand new app secret is **ExternalSecret + 1Password**. Reach for SOPS only when the secret must already exist before ESO is running.

## SOPS Secret template

Path: `kubernetes/apps/<ns>/<app>/app/secret.sops.yaml`. Author in plaintext; `sops -e -i <file>` encrypts in place.

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: my-app-secret
type: Opaque
stringData:
  token: "sensitive-value"
  api-key: "another-value"
```

After editing:

```sh
SOPS_AGE_KEY_FILE=./age.key sops -e -i kubernetes/apps/<ns>/<app>/app/secret.sops.yaml
```

Verify encryption status:

```sh
SOPS_AGE_KEY_FILE=./age.key sops filestatus kubernetes/apps/<ns>/<app>/app/secret.sops.yaml
# expect: encrypted
```

SOPS rules in `.sops.yaml`:
- `(bootstrap|kubernetes)/*.sops.ya?ml` → encrypts only `data` and `stringData` fields
- `talos/*.sops.ya?ml` → encrypts the whole file (Talos configs are not data/stringData shaped)

Both rulesets share the same Age recipient. Private key: `age.key` at the repo root (gitignored, backup in 1Password vault `anton-homelab oct 26 2025`).

Don't forget to add the file to `app/kustomization.yaml`:

```yaml
resources:
  - ./helmrelease.yaml
  - ./secret.sops.yaml
```

## ExternalSecret template

Path: `kubernetes/apps/<ns>/<app>/app/externalsecret.yaml`. No encryption step — nothing sensitive is in git.

```yaml
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: my-app-credentials
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: my-app-credentials
    creationPolicy: Owner
  data:
    - secretKey: password
      remoteRef:
        key: "my-app/password"           # SDK provider combined-key syntax: <item>/<field>
```

Three field-mapping shapes:

**Single field:**
```yaml
data:
  - secretKey: password
    remoteRef:
      key: "my-app/password"
```

**Multiple fields from one item:**
```yaml
data:
  - secretKey: username
    remoteRef:
      key: "my-app/username"
  - secretKey: password
    remoteRef:
      key: "my-app/password"
```

**Entire item as a single Secret with all fields:**
```yaml
dataFrom:
  - extract:
      key: "my-app"
```

Rules:
- `apiVersion` MUST be `external-secrets.io/v1` (not `v1beta1` — the cluster runs the v1 CRD)
- The 1Password vault is `anton`. The store is `onepassword-connect` (`ClusterSecretStore`).
- Field names are case-sensitive and must match the 1Password item exactly. A typo lands as `SecretSyncError: not found` in the ExternalSecret status.
- Add `- ./externalsecret.yaml` to `app/kustomization.yaml`.

Verify after apply:

```sh
kubectl get externalsecret -n <ns> my-app-credentials
kubectl get secret        -n <ns> my-app-credentials
kubectl describe externalsecret -n <ns> my-app-credentials | grep -A5 Status:
```

## cluster-secrets.sops.yaml — the special one

`kubernetes/components/sops/cluster-secrets.sops.yaml` is a SOPS Secret named `cluster-secrets` that holds the variables every `ks.yaml` substitutes from. Edit with `sops`, never in plaintext:

```sh
SOPS_AGE_KEY_FILE=./age.key sops kubernetes/components/sops/cluster-secrets.sops.yaml
```

`sops <file>` decrypts on open and re-encrypts on save automatically, so no extra step is needed — just save in the editor and commit. Apps using new keys will pick them up at the next Flux reconcile.
