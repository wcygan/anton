---
name: anton-cluster
description: Repo conventions reference for the Anton homelab cluster (Talos + Flux GitOps). Covers the 3-file Flux app pattern, SOPS vs ExternalSecret wiring, envoy-internal/external gateways, HTTPRoute/DNSEndpoint patterns, talhelper config generation, per-node machine config patches, and the init→configure→bootstrap→manage task flow. Use when adding a Flux app, adding a Talos node, writing machine config patches, exposing a service, managing cluster secrets, or debugging Flux/HelmRelease/Kustomization wiring in this repo. Keywords: anton, flux, talhelper, talconfig, ks.yaml, helmrelease, ocirepository, kustomization, envoy-gateway, httproute, dnsendpoint, sops, onepassword, externalsecret, cluster-secrets, machine config, patches, nodes.yaml
allowed-tools: Read, Grep, Glob
---

# Anton Cluster Conventions

Project-local reference for *this repo's* conventions. The cluster is a Talos Linux + Flux GitOps homelab with Cilium CNI, Envoy Gateway API, cert-manager, External-Secrets (1Password), SOPS, and Cloudflare tunnels.

## Scope

**In scope** — answering questions about how this repo is *structured*:
- Where files live (`kubernetes/apps/<ns>/<app>/...`, `talos/patches/...`)
- Which patterns are canonical (the 3-file Flux app pattern, patch scopes, secret sources)
- How to add/change things (apps, nodes, routes, secrets)
- Why conventions exist (encoded in nested `CLAUDE.md` files)

**Out of scope** — defer to other skills:
- Generic Talos questions (schema lookups, CLI flags) → global `talos` skill
- Generic Kubernetes questions (kubectl, workload debugging) → global `kubernetes` skill
- Live cluster health → `cluster-status`, `cluster-health`, `flux-status`, `ceph-status`
- Image push/pull → `harbor-registry`
- Secret creation → `create-secret`
- Adding an app end-to-end → `deploy-app`, `ideate-app`

This skill is **read-only**. It does not run `task`, `flux`, `kubectl`, `talosctl`, or any mutation.

## Routing Table

| User asks about... | Read |
|---|---|
| Flux app layout, ks.yaml / HelmRelease / OCIRepository, substitution, components | [references/kubernetes-patterns.md](references/kubernetes-patterns.md) |
| Secrets (SOPS vs ExternalSecret, cluster-secrets, 1Password) | [references/kubernetes-patterns.md](references/kubernetes-patterns.md) §5 |
| Gateways, HTTPRoute, DNSEndpoint, certificates, split-horizon DNS | [references/kubernetes-patterns.md](references/kubernetes-patterns.md) §6 |
| talconfig, talhelper, patches, talenv, nodes.yaml, schematics | [references/talos-patterns.md](references/talos-patterns.md) |
| Bootstrap vs Flux handoff, template bridge | [references/talos-patterns.md](references/talos-patterns.md) §8 |
| "How do I add an app / node / route / secret?" | [references/workflows.md](references/workflows.md) |
| "Why isn't my app deploying / resolving / decrypting?" | [references/troubleshooting.md](references/troubleshooting.md) |

## Authoritative Sources

When this reference conflicts with the repo, the repo wins. Re-read these nested `CLAUDE.md` files for ground truth:

- `CLAUDE.md` — top-level rules (secrets, safety, UTF-8, code quality)
- `kubernetes/apps/CLAUDE.md` — 3-file Flux pattern, variable substitution
- `kubernetes/apps/network/CLAUDE.md` — gateway/DNS architecture
- `bootstrap/CLAUDE.md` — bootstrap vs Flux decision tree
- `.taskfiles/CLAUDE.md` — task workflow map (init → configure → bootstrap → manage)
- `scripts/CLAUDE.md` — shell script conventions

## File Path Quick Index

| Purpose | Path |
|---|---|
| Cluster parameters (IPs, DNS, Cloudflare) | `cluster.yaml` |
| Node inventory (hostname, IP, MAC, disk, schematic) | `nodes.yaml` |
| Talos + Kubernetes version pins | `talos/talenv.yaml` |
| Talhelper source | `talos/talconfig.yaml` |
| Global machine patches | `talos/patches/global/` |
| Control-plane-only patches | `talos/patches/controller/` |
| Per-node patches | `talos/patches/<hostname>/` |
| Talos secrets (encrypted) | `talos/talsecret.sops.yaml`, `talos/talenv.sops.yaml` |
| Generated machine configs (gitignored) | `talos/clusterconfig/` |
| Flux root entry point | `kubernetes/flux/cluster/ks.yaml` |
| Global cluster variables (`${SECRET_DOMAIN}` etc.) | `kubernetes/components/sops/cluster-secrets.sops.yaml` |
| App tree | `kubernetes/apps/<namespace>/<app>/{ks.yaml,app/*}` |
| Gateways + certs | `kubernetes/apps/network/envoy-gateway/app/` |
| ESO ClusterSecretStore | `kubernetes/apps/external-secrets/onepassword-store/app/` |
| Bootstrap helmfile | `bootstrap/helmfile.d/` |
| Age key (gitignored) | `age.key` |
| SOPS config | `.sops.yaml` |

## Canonical Examples

When showing a pattern, point at one of these known-good exemplars rather than inventing:

- **Clean OCI-chart app**: `kubernetes/apps/default/echo/`
- **HelmRepository variant**: `kubernetes/apps/harbor/harbor/`
- **App with SOPS secret + DNSEndpoint + HTTPRoute**: `kubernetes/apps/network/cloudflare-tunnel/`
- **App with ExternalSecret (ESO)**: `kubernetes/apps/external-secrets/onepassword-store/`
- **Secondary-domain app**: `kubernetes/apps/default/echo-two/`
- **Gateway + Certificate**: `kubernetes/apps/network/envoy-gateway/app/`

## Hard Rules (from nested CLAUDE.md)

1. Never commit unencrypted `*.sops.*` files — run `task configure` first.
2. Never add the real tailnet name to git — use `<tailnet-name>.ts.net` as a placeholder.
3. Every Flux app uses the 3-file pattern: `ks.yaml` + `app/kustomization.yaml` + resources in `app/`.
4. Every `ks.yaml` needs `postBuild.substituteFrom: cluster-secrets` or `${VAR}` won't resolve.
5. Every namespace kustomization must explicitly list its apps; there is no auto-discovery.
6. `task talos:reset`, `task template:reset`, `kubectl delete namespace`, `talosctl reset` are destructive — never run without explicit user confirmation.
