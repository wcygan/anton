---
sidebar_position: 1
slug: /
---

# Anton

Anton is a Talos Kubernetes homelab for public applications, private services
over Tailscale, and learning experiments. Flux applies the committed desired
state. Manifests under `kubernetes/` and `bootstrap/` are hand-edited; Talos
machine configs are generated from the sources under `talos/`.

## Start here

The [routine operations guide](runbooks/routine-operations.md) covers checking
health, deploying a change, and finding the first failing layer. Run commands
from the repository root with `mise exec --`.

```sh
mise exec -- task --list
```

| Situation | Guide |
| --- | --- |
| Remote access or Talos health | [Talos health](runbooks/talos-health.md) |
| Workload logs or missing log streams | [Kubernetes logs in Loki](runbooks/kubernetes-logs-loki.md) |
| Helm timeout, rollback, cleanup, or hook failure | [Flux Helm remediation](runbooks/flux-helm-remediation.md) |
| Storage network attachment failure | [Multus attach failure](runbooks/multus-attach-failure.md) |
| Push or pull an image through Harbor | [Harbor developer guide](notes/harbor-developer-guide.md) |

Runbooks describe operator procedures. Notes and Playground pages also contain
historical experiments; their examples are not a current workload inventory.
Use committed manifests for desired state and bounded live reads for current health.

## Hardware and access

The hardware inventory last verified April 20, 2026 records three Minisforum
MS-01 control-plane nodes, each with an Intel Core i9-13900H and 96 GiB RAM.
Each node has a 500 GB system NVMe and two 1 TB data NVMes. A dedicated 10 Gbit
SFP+ full mesh carries storage traffic; management uses a separate RJ45 network.
The repository's `context/hardware.md` retains the dated inventory and topology.

Public applications use Cloudflare Tunnel and the external Envoy gateway.
Private access uses Tailscale; internal HTTPRoutes use the internal Envoy
gateway. Public exposure is an explicit operator decision.

Talos provides API-based node management without SSH. Flux owns application
configuration; routine deployment changes go through Git rather than live edits.
