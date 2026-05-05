---
name: cluster-secrets keys (current)
description: What is actually in cluster-secrets.sops.yaml and how to add a key without leaking plaintext
type: reference
---

`kubernetes/components/sops/cluster-secrets.sops.yaml` is the only Secret every namespace's `kustomization.yaml` substitutes from (via `components: [../../components/sops]`). As of 2026-05-04 it has only:

- `SECRET_DOMAIN`
- `SECRET_DOMAIN_TWO`
- `SECRET_DOMAIN_THREE`
- `TAILNET_SUFFIX` (added 2026-05-04 by `flux-app-author` while scaffolding ntfy — full `<tailnet>.ts.net` value, no separate `.ts.net` append needed)

There is no `tailnet_name`, no `tailnet_dns`, no `cluster_dns_gateway_addr` (that one comes from the secondary domain doc, not from cluster-secrets). If a request asks for `${tailnet_name}` substitution, it is wrong about the variable name — verify by decrypting cluster-secrets first.

**How to add a key without leaving a plaintext SOPS file on disk:** use `sops set` (in-place, re-encrypts atomically), never decrypt-edit-encrypt:

```sh
SOPS_AGE_KEY_FILE=./age.key sops set kubernetes/components/sops/cluster-secrets.sops.yaml \
  '["stringData"]["NEW_KEY"]' '"value"'
SOPS_AGE_KEY_FILE=./age.key sops filestatus kubernetes/components/sops/cluster-secrets.sops.yaml
# {"encrypted":true}
```

The third arg is JSON — strings need the embedded double quotes. Do **not** `sops -d > /tmp/file && edit && sops -e -i` — that route leaves plaintext on disk and risks a `git add` mistake. The naming convention in this Secret is SHOUTY_SNAKE_CASE; respect it.

The registries CLAUDE.md mentioned `TAILNET_SUFFIX` as a deferred future change for Harbor's externalURL — that change is now possible without a separate cluster-secrets edit because ntfy already added the key.
