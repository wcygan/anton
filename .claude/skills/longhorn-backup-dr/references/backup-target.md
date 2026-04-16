---
name: longhorn-backup-target
description: Configuring the Longhorn backup target (S3, NFS, CIFS).
---

# Backup target

Canonical: https://longhorn.io/docs/1.11.1/snapshots-and-backups/backup-and-restore/set-backupstore/

## Shapes

- `s3://<bucket>@<region>/<prefix>` — AWS or any S3-compatible (MinIO, R2, B2-with-S3-compat). Requires a credentials secret.
- `nfs://<server>:/<path>` — any NFSv4 export. No credentials; relies on network-level isolation.
- `cifs://...` — SMB. Rarely used.

## Credentials secret shape (S3)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: longhorn-backup-credentials
  namespace: storage
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "..."
  AWS_SECRET_ACCESS_KEY: "..."
  AWS_ENDPOINTS: "https://<host>"    # omit for AWS
  AWS_REGION: "auto"                  # omit for AWS
```

Prefer authoring via `ExternalSecret` + the 1Password `anton` vault — see `add-flux-app` for the template. The Secret must live in the `storage` namespace to be referenced by `backupTargetCredentialSecret`.

## Anton guidance

Whenever we pick a target, write it up as an ADR (via the `adr` skill) first — the choice drives cost, durability, and RPO. Non-obvious options worth considering:

- **Cloudflare R2** — already have a CF account for the tunnel; S3-compatible; egress-free reads.
- **NFS off a home NAS** — cheapest, single-host failure domain.
- **Backblaze B2 S3-compat** — cheap per-GB; small egress fees.

Avoid: the same bucket used by another cluster (path collision), a target without versioning (accidental deletes), or a target in the same failure domain as the cluster (power loss takes both).
