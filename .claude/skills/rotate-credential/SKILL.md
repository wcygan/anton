---
name: rotate-credential
description: Credential rotation for Anton — rotate age key plus SOPS key rotation across the repo, generate a new deploy key for Flux, rotate the 1password token for ESO, or rotate the cloudflare token for the tunnel. Preconditions, verification, rollback.
allowed-tools: Read, Bash
---

# Rotate a credential

Task skill for the four credentials that gate Anton. Each ritual is preconditions → command sequence → verification → rollback. Run only one rotation at a time. Never rotate `age.key` and a downstream secret in the same change — recover from the age rotation first.

> **Sources of truth:**
> - Age public recipient (committed): `.sops.yaml`, currently `age1de4xdcq6h5yk4jjyyqe6qws344xsk055rdzvpr79mehvv7q7rdfqnyetjc`
> - Age private key: `age.key` at the repo root (gitignored). **Backup is in 1Password vault `anton-homelab oct 26 2025`.**
> - 1Password vault: `anton` — every cluster credential lives here.
> - SOPS rules: `talos/*.sops.*` encrypts the whole file; `bootstrap|kubernetes/*.sops.*` encrypts only `data` and `stringData` fields.

## Ritual 1 — rotate `age.key` (master SOPS key)

**Highest stakes.** A wrong rotation makes every SOPS file in the repo unreadable to Flux and stops reconciliation cluster-wide.

**Preconditions:** (1) backup current `age.key` to 1Password vault `anton` (new entry, dated today — do not overwrite the `anton-homelab oct 26 2025` backup); (2) `flux check && flux get ks -A --status=all | rg -v True` — empty; (3) `SOPS_AGE_KEY_FILE=./age.key sops --decrypt kubernetes/components/sops/cluster-secrets.sops.yaml >/dev/null && echo OK`.

**Sequence (dual-recipient transition):**
```sh
# 1. New key (do NOT overwrite age.key yet)
age-keygen -o age.key.new

# 2. Add new recipient to BOTH creation_rules in .sops.yaml (comma-separated, alongside the old)
$EDITOR .sops.yaml

# 3. Re-encrypt every SOPS file to both recipients
SOPS_AGE_KEY_FILE=./age.key fd '\.sops\.ya?ml$' bootstrap/ kubernetes/ talos/ -x sops updatekeys --yes {}
SOPS_AGE_KEY_FILE=./age.key fd '\.sops\.ya?ml$' bootstrap/ kubernetes/ talos/ -x sops filestatus {}

# 4. Promote the new key, re-verify under it
mv age.key age.key.old && mv age.key.new age.key
SOPS_AGE_KEY_FILE=./age.key fd '\.sops\.ya?ml$' bootstrap/ kubernetes/ talos/ -x sops filestatus {}

# 5. Remove the OLD recipient from .sops.yaml and re-run updatekeys
$EDITOR .sops.yaml
SOPS_AGE_KEY_FILE=./age.key fd '\.sops\.ya?ml$' bootstrap/ kubernetes/ talos/ -x sops updatekeys --yes {}

# 6. Push the new key into Flux
kubectl -n flux-system create secret generic sops-age \
  --from-file=age.agekey=./age.key --dry-run=client -o yaml | kubectl apply -f -
flux reconcile source git flux-system
```

**Verification:** `flux get ks -A --status=all` all `Ready=True`; pick one app using `${VAR}` and confirm the substituted value is correct.

**Rollback:** restore `age.key.old` → `age.key`, `git restore .sops.yaml`, re-apply the old `sops-age` secret to flux-system. Old key must still be in 1Password.

## Ritual 2 — rotate the GitHub deploy key (Flux GitRepository SSH)

Private half: `github-deploy.key` at repo root (gitignored). Public half: GitHub repo → Settings → Deploy keys.

**Preconditions:** confirm you can push to the repo with your normal creds (independent of the deploy key); note the current GitHub deploy-key fingerprint so you can identify it later.

**Sequence:**
```sh
ssh-keygen -t ed25519 -C "flux-anton-$(date +%Y%m%d)" -f github-deploy.key.new -N ""
gh repo deploy-key add github-deploy.key.new.pub --title "flux-$(date +%Y%m%d)"

kubectl -n flux-system create secret generic flux-system \
  --from-file=identity=github-deploy.key.new \
  --from-file=identity.pub=github-deploy.key.new.pub \
  --from-file=known_hosts=<(ssh-keyscan github.com 2>/dev/null) \
  --dry-run=client -o yaml | kubectl apply -f -

flux reconcile source git flux-system
flux get sources git -A    # READY=True with a recent revision
```

**Verification:** `flux get sources git flux-system` shows `READY=True` with a fetch in the last minute; push a trivial commit and confirm Flux picks it up. Then delete the OLD deploy key in GitHub.

**Rollback:** re-apply the old `flux-system` secret with the previous private half; the old GitHub deploy key must still exist.

## Ritual 3 — rotate the 1Password service-account token (ESO)

Consumed by `external-secrets-operator` via `ClusterSecretStore` `onepassword-connect`. Secret: `kubernetes/apps/external-secrets/onepassword-store/app/secret.sops.yaml`, key `stringData.token`. Without it, every `ExternalSecret` in the cluster stops syncing.

**Preconditions:** generate a new service-account token in 1Password admin scoped to vault `anton` only; baseline `kubectl get externalsecrets -A | rg SecretSynced | wc -l` (expect this count to stay constant after rotation).

**Sequence:**
```sh
SOPS_AGE_KEY_FILE=./age.key sops \
  kubernetes/apps/external-secrets/onepassword-store/app/secret.sops.yaml
# Replace stringData.token, save, exit.
SOPS_AGE_KEY_FILE=./age.key sops filestatus \
  kubernetes/apps/external-secrets/onepassword-store/app/secret.sops.yaml   # encrypted
git add kubernetes/apps/external-secrets/onepassword-store/app/secret.sops.yaml
git commit -m "chore(eso): rotate 1password service-account token"
git push
flux reconcile kustomization onepassword-store -n flux-system --with-source
```

**Verification:** `kubectl get externalsecrets -A | rg -v SecretSynced` empty; ESO logs show no `unauthorized`: `kubectl logs -n external-secrets -l app.kubernetes.io/name=external-secrets --tail=50`.

**Rollback:** revoke the new token in 1Password, `git revert HEAD`, push, reconcile. Old token must still be valid until rollback succeeds.

## Ritual 4 — rotate the Cloudflare tunnel token

Authenticates `cloudflare-tunnel`'s outbound HTTP2/QUIC connection to Cloudflare edge. Secret: `kubernetes/apps/network/cloudflare-tunnel/app/secret.sops.yaml`, key `stringData.TUNNEL_TOKEN`. Without it, every public URL stops resolving.

**Preconditions:** generate a new tunnel token in Cloudflare → Zero Trust → Networks → Tunnels → Anton → Configure → Token (rotate in place — do NOT delete the tunnel); baseline `kubectl logs -n network -l app.kubernetes.io/name=cloudflare-tunnel --tail=20` showing `Connection registered`.

**Sequence:**
```sh
SOPS_AGE_KEY_FILE=./age.key sops kubernetes/apps/network/cloudflare-tunnel/app/secret.sops.yaml
# Replace stringData.TUNNEL_TOKEN, save, exit.
SOPS_AGE_KEY_FILE=./age.key sops filestatus kubernetes/apps/network/cloudflare-tunnel/app/secret.sops.yaml
git add kubernetes/apps/network/cloudflare-tunnel/app/secret.sops.yaml
git commit -m "chore(network): rotate cloudflare tunnel token"
git push
flux reconcile kustomization cloudflare-tunnel -n flux-system --with-source
kubectl -n network rollout restart deploy/cloudflare-tunnel
kubectl -n network rollout status deploy/cloudflare-tunnel
```

**Verification:** fresh `Connection registered` in tunnel logs, no `unauthorized`. End-to-end: `curl -I https://<some-app>.${SECRET_DOMAIN}` returns expected response.

**Rollback:** `git revert HEAD`, push, reconcile, restart. Previous token stays valid in Cloudflare unless explicitly revoked.

## Hard rules

- One rotation at a time. Finish verification before starting the next.
- Never rotate `age.key` and a downstream secret in the same change.
- Never delete the old credential at the source until verification has passed end-to-end.
- Take a fresh 1Password backup of `age.key` before AND after every rotation.
- Never log secret values to scripts, files, or shell history. `sops` edits in-place via `$EDITOR`; do not pipe secrets through `echo` or `cat`.

## Related skills

- Triaging Flux when reconciliation breaks after a rotation → `debug-flux-reconciliation`
- The SOPS vs ExternalSecret decision tree (which credentials live where) → `anton-repo-conventions`
