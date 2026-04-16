---
name: 1Password SDK provider uses combined-key syntax, not `property:`
description: anton's ClusterSecretStore `onepassword-connect` uses the `onepasswordSDK` provider; ExternalSecret field refs must use `key: "<item>/<field>"` and never `property:`
type: reference
---

The `onepassword-connect` `ClusterSecretStore` in anton uses provider `onepasswordSDK` (see `kubernetes/apps/external-secrets/onepassword-store/app/clustersecretstore.yaml`). That provider accepts only the **combined-key syntax** for field references:

```yaml
data:
  - secretKey: admin-password
    remoteRef:
      key: "grafana-admin/password"    # <1Password item title>/<field name>
```

It does **not** accept the classic `property:` shape:

```yaml
# WRONG for anton — this is the onepassword-connect HTTP provider's shape, not the SDK's
data:
  - secretKey: admin-password
    remoteRef:
      key: grafana-admin
      property: password
```

Documented in `.claude/skills/anton-repo-conventions/references/secrets.md` and in the `externalsecret.yaml.template`. If an operator hands you a spec written in the `property:` style, translate it before writing.

To pull every field from an item as one Secret: use `dataFrom[].extract.key: "<item-title>"` (no field).

Field names and item titles are case-sensitive. Typos surface as `SecretSyncError: not found` in the ExternalSecret status.
