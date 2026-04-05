# Troubleshooting

Common symptoms and their root causes in this repo. Read top-to-bottom; the first match usually wins.

## Flux / Kustomize / HelmRelease

| Symptom | Likely cause | Fix |
|---|---|---|
| App never appears in the cluster | App not listed in `kubernetes/apps/<ns>/kustomization.yaml` | Add `./<app>/ks.yaml` to the resources list; there is no auto-discovery |
| Literal `${SECRET_DOMAIN}` in a deployed Secret / ConfigMap / HTTPRoute | Missing `postBuild.substituteFrom` in `ks.yaml`, or namespace kustomization doesn't include `../../components/sops` | Add `postBuild.substituteFrom: [{name: cluster-secrets, kind: Secret}]` to `ks.yaml`; verify namespace kustomization has `components: [../../components/sops]` |
| `HelmRelease` error: `chart not found` or `source not ready` | `OCIRepository.metadata.name` doesn't match `HelmRelease.spec.chartRef.name` | Align names; they must be identical |
| `Kustomization` stuck `ReconcilePending` | Missing `dependsOn` target, or the dependency is itself failing | `flux get ks -A`; fix the upstream first |
| `failed to decrypt secret` during reconciliation | SOPS provider not configured, or age key not present in `flux-system` | Check `decryption.provider: sops` is inherited from root ks.yaml; verify `sops-age` secret exists in `flux-system`; confirm the age recipient in `.sops.yaml` matches the key Flux has |
| Deployed but `postBuild` substituted the wrong value | Variable defined in both `cluster-settings` (ConfigMap) and `cluster-secrets` (Secret) — Secret wins | Deduplicate |
| Manifest changes never reach the cluster | GitRepository not syncing, or the branch differs from the one Flux watches | `flux get sources git -A`; check the branch name in the GitRepository matches the one you pushed to |

## Secrets

| Symptom | Likely cause | Fix |
|---|---|---|
| `task configure` refuses to encrypt | File not matched by any rule in `.sops.yaml`, or filename doesn't include `.sops.` | Rename to `*.sops.yaml`; check the rule path_regex covers it |
| ExternalSecret shows `SecretSyncError: not found` | Wrong `remoteRef.key` format or item missing from the `anton` 1Password vault | Use combined syntax `"item-name/field-name"` for the SDK provider; verify item exists |
| ExternalSecret syncs but Secret has wrong fields | `data` keys don't match field names in 1Password | Field names are case-sensitive and must match exactly |
| `sops filestatus` says unencrypted but file looks encrypted | File was edited outside SOPS and the MAC is stale | Re-encrypt via `task configure` or `sops --encrypt --in-place` |

## Networking / Gateway

| Symptom | Likely cause | Fix |
|---|---|---|
| HTTPRoute created but requests return 503 | No healthy backend endpoints | `kubectl get endpoints -n <ns> <svc>`; check pod readiness |
| HTTPRoute attaches to wrong gateway | Wrong `parentRefs.name` or missing `sectionName: https` | External via Cloudflare → `envoy-external`; internal LAN → `envoy-internal`; both are in namespace `network` |
| DNS doesn't resolve internally (home network) | k8s-gateway not picking up the route, or home DNS not forwarding `${SECRET_DOMAIN}` to `cluster_dns_gateway_addr` | Verify k8s-gateway pod running; confirm home router/DNS forwards the domain |
| Public host doesn't resolve | cloudflare-dns isn't syncing DNSEndpoints, or external-dns `--gateway-name` filter excludes it | Check cloudflare-dns pod logs; for secondary domain, **must** use explicit DNSEndpoint resource |
| Cert-manager `Certificate` stuck `Issuing` | Cloudflare API token missing/expired, or DNS-01 challenge blocked | Check `cloudflare-dns-secret`; look at challenge resources in the namespace |
| Secondary domain returns SSL cert for wrong host | Gateway certificate missing for that domain | Add gateway certificate entry for `${SECRET_DOMAIN_TWO}`; see `docs/docs/notes/adding-a-2nd-domain.md` |

## Talos / Nodes

| Symptom | Likely cause | Fix |
|---|---|---|
| `task talos:apply-node` refuses with "precondition failed" | Node unreachable, kubeconfig stale, or talosctl/talhelper missing | Preconditions: `talosctl -n <ip> version` works, `kubectl get nodes` works, `mise install` ran |
| `Error: certificate signed by unknown authority` from talosctl | Stale `talos/clusterconfig/talosconfig`, or node was reset | Re-run `task talos:generate-config`; or during bootstrap pass `--insecure` |
| Node stuck in maintenance mode after `apply` | Config was rejected | `talosctl -n <ip> dmesg`, `talosctl -n <ip> logs machined` |
| Containers can't pull from Harbor | Harbor service ClusterIP changed; static host entry in `machine-network.yaml` is stale | Update the patch, re-generate, re-apply to nodes |
| Node re-registers in Tailscale with `-1` suffix after reboot | Intended — `TS_STATE_DIR=mem:` | Clean up old node in Tailscale admin console |
| `task talos:upgrade-node` uses wrong image | `talosImageURL` in talconfig doesn't match new version | Bump `talosVersion` in `talenv.yaml`, re-run `task configure`, then upgrade |
| CUE schema validation fails on `nodes.yaml` | Duplicate name/IP/MAC, invalid schematic ID length, reserved name (`global`/`controller`/`worker`), bad MTU range | Read the validation error — the schema in `templates/.taskfiles/template/resources/*.schema.cue` is authoritative |

## Bootstrap

| Symptom | Likely cause | Fix |
|---|---|---|
| `task bootstrap:talos` fails at `gensecret` | `talsecret.sops.yaml` exists already | Skip; existing secret is reused. Only delete if intentionally resetting |
| `task bootstrap:apps` fails at Phase 3 (SOPS) | Age key not in `bootstrap/sops-age.sops.yaml` or not decryptable | Verify `age.key` exists at repo root, `SOPS_AGE_KEY_FILE` env set |
| Phase 5 (Flux) installs but never reconciles | GitHub deploy key missing or repo private without key configured | Add public half of `github-deploy.key` to repo's deploy keys in GitHub |
| Bootstrap uses different values than Flux | Someone edited `bootstrap/helmfile.d/` values directly instead of `kubernetes/apps/**/helmrelease.yaml` | Move values back to `kubernetes/apps/` — the template bridge reads from there |

## Safety reminders

- `task talos:reset` wipes node data. Never run without explicit user confirmation.
- `task template:reset` deletes all rendered configs. Destructive.
- `kubectl delete namespace` removes everything in it. Prefer removing the app's `ks.yaml` from its namespace kustomization and letting Flux prune.
- Never commit an unencrypted `*.sops.*` file. Always `task configure` first, verify with `sops filestatus`.
- Never commit the real tailnet name. Use `<tailnet-name>.ts.net` as a placeholder.
