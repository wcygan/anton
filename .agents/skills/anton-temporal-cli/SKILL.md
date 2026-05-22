---
name: anton-temporal-cli
description: Use when Codex needs to inspect or troubleshoot the Anton cluster's self-hosted Temporal deployment with the local Temporal CLI, including checking cluster health, namespaces, workflow visibility, schedules, search attributes, Web UI reachability, or Kubernetes readiness for the `temporal` namespace. Prefer this for Temporal CLI tasks in Anton rather than generic Temporal SDK guidance.
---

# Anton Temporal CLI

## Overview

Inspect Anton's Temporal deployment with the local `temporal` CLI while keeping the gRPC frontend private. Use a temporary localhost port-forward to the in-cluster frontend service; do not assume the Web UI hostname is the CLI endpoint.

## Safety

- Work from the Anton checkout. Use the current workspace when it is the Anton repo; otherwise prefer `${ANTON_REPO:-$HOME/Development/anton}` after verifying it exists.
- Use `./kubeconfig` with `kubectl` and Flux commands.
- Keep checks read-only by default. Do not reconcile, apply, delete, rotate credentials, or edit manifests unless the user explicitly asks.
- Do not print secret values. Listing Secret key names is acceptable when useful.
- Do not hardcode the tailnet FQDN in skill output or files. Discover the current Web UI hostname from `Ingress/temporal` or use `temporal.<tailnet-name>.ts.net` as a placeholder.
- Close any port-forward before finishing the turn.

## Quick Workflow

1. Confirm tools and baseline state:

```sh
ANTON_REPO="${ANTON_REPO:-$HOME/Development/anton}"
cd "$ANTON_REPO"
command -v temporal
temporal --version
KUBECTL="$(mise which kubectl 2>/dev/null || command -v kubectl)"
FLUX="$(mise which flux 2>/dev/null || command -v flux)"
"$FLUX" --kubeconfig ./kubeconfig get ks -n temporal
"$FLUX" --kubeconfig ./kubeconfig get hr -n temporal
"$KUBECTL" --kubeconfig ./kubeconfig -n temporal get cluster temporal-postgres -o wide
```

2. Open a localhost tunnel to the private Temporal frontend:

```sh
"$KUBECTL" --kubeconfig ./kubeconfig -n temporal \
  port-forward --address 127.0.0.1 svc/temporal-frontend 17233:7233
```

Run it as a long-running command, then use `--address 127.0.0.1:17233` for CLI calls. If `17233` is busy, pick another localhost port and keep the same pattern.

3. Introspect with the CLI:

```sh
temporal operator cluster health --address 127.0.0.1:17233
temporal operator cluster describe --address 127.0.0.1:17233
temporal operator namespace list --address 127.0.0.1:17233
temporal workflow count --address 127.0.0.1:17233 --namespace default
temporal workflow list --address 127.0.0.1:17233 --namespace default
temporal schedule list --address 127.0.0.1:17233 --namespace default
temporal operator search-attribute list --address 127.0.0.1:17233 --namespace default
```

Use `temporal-system` only for system-health context. Its scanner workflows are expected and should not be treated as user workloads.

4. Verify Web UI reachability separately:

```sh
UI_HOST="$("$KUBECTL" --kubeconfig ./kubeconfig -n temporal \
  get ingress temporal -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
curl -fsS -o /tmp/temporal-ui.html -w 'ui_http=%{http_code} bytes=%{size_download}\n' \
  "https://${UI_HOST}/namespaces/default"
curl -fsS "https://${UI_HOST}/api/v1/namespaces" \
  | jq -r '.namespaces[]?.namespaceInfo.name // .namespaces[]?.name // empty'
curl -fsS -o /tmp/temporal-workflows.json -w 'workflows_http=%{http_code} bytes=%{size_download}\n' \
  "https://${UI_HOST}/api/v1/namespaces/default/workflows"
```

## Expected Healthy Shape

- Flux Kustomizations `temporal-config` and `temporal` are Ready.
- HelmRelease `temporal` is Ready on the deployed chart.
- CNPG `Cluster/temporal-postgres` reports `3/3` Ready.
- Schema and namespace Jobs are Complete.
- Temporal Deployments are Available; initial restarts during first boot can be benign if counts stay flat afterward.
- CLI cluster health returns `SERVING`.
- Cluster describe reports `postgres12` for both persistence and visibility stores.
- Namespace list includes `default` and `temporal-system`.
- The default namespace can list workflows, schedules, and search attributes without errors.

## Reporting

Summarize command evidence, not raw dumps. Include:

- CLI endpoint method: localhost port-forward to `svc/temporal-frontend`.
- Cluster health and persistence stores.
- Namespaces and retention values.
- Workflow and schedule counts for `default`.
- Web UI/API HTTP status using the discovered hostname or placeholder, not a hardcoded tailnet FQDN.
- Kubernetes readiness from Flux, HelmRelease, CNPG, pods, jobs, ServiceMonitors, and Ingress.
