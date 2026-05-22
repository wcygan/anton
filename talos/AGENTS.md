# talos/

Goal: Maintain Talos source config and generated machine configs with one-node-at-a-time operational safety.

Success means:
- Source edits land in `talos/talconfig.yaml`, `talos/talenv.yaml`, or `talos/patches/`.
- Generated files in `talos/clusterconfig/` come from `task talos:generate-config`.
- SOPS files stay encrypted and node operations preserve etcd quorum.

Stop when: generated config is refreshed when needed, validation output is captured, and any live apply/upgrade/reset waits for explicit operator approval.

## Source Files

- `talconfig.yaml`: cluster and per-node Talos source of truth.
- `talenv.yaml`: non-secret Talos and Kubernetes version pins.
- `talenv.sops.yaml` and `talsecret.sops.yaml`: encrypted Talos inputs.
- `patches/`: global and controller patches applied by talhelper.
- `clusterconfig/`: generated output and local talosconfig.

## Commands

```sh
task talos:generate-config
task talos:apply-node IP=<ip> MODE=auto
task talos:upgrade-node IP=<ip>
task talos:upgrade-k8s
```

Use `./talos/clusterconfig/talosconfig` and Tailscale MagicDNS names (`k8s-1`, `k8s-2`, `k8s-3`) for read-only inspection.

## Safety

Check cluster health before proposing any mutation:

```sh
kubectl get nodes -o wide
talosctl --talosconfig ./talos/clusterconfig/talosconfig -e k8s-1 -n k8s-1,k8s-2,k8s-3 health
```

Apply or upgrade one node at a time, then verify health and etcd quorum before the next node. Treat reset, bootstrap, upgrade, apply-config, and etcd member changes as operator-approved actions.
