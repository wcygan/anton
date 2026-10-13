# Longhorn metrics and Talos health address selection

Incident window: 2026-10-13 03:02–03:15 UTC (October 12 local time).

## Causes

Longhorn 1.12.1's Helm-owned `storage/longhorn-manager` NetworkPolicy
allowed Longhorn components but no ingress from Prometheus in `observability`.
All three `longhorn-backend` scrape targets timed out on TCP 9500. Managers
and all 16 volumes were healthy. This was an observability connectivity failure,
not evidence of failed storage.

Talos membership advertises all routable non-Kubernetes addresses, including
point-to-point storage interfaces. Automatic health discovery selected
`10.100.0.0`, `10.100.0.1`, and `10.100.0.3`. From k8s-2, the last address
belongs to the k8s-1↔k8s-3 cable and has no direct route. Its own link to
k8s-3 uses `10.100.0.4/31`. The resulting timeout appeared during the etcd
health phase, although etcd itself already advertises management addresses.
This is consistent with the separate management/storage fabrics in
[ADR 0009](../adrs/0009-10g-sfp-full-mesh-networking.md).

## Repairs

- Added a supplemental NetworkPolicy under `longhorn-config`, permitting only
  the kube-prometheus-stack Prometheus pods in `observability` to reach
  Longhorn managers on TCP 9500. Existing chart policies remain intact.
  This is a port-level allowance: Longhorn serves its API and metrics on the
  same port; it is not an HTTP path filter.
- Updated `scripts/talos-health.sh` to read management addresses from
  `talos/talconfig.yaml` and pass `--control-plane-nodes` explicitly. It fails
  closed for unexpected/missing nodes, duplicate addresses, non-control-plane
  roles, or addresses outside the management subnet. Client connections remain
  through Tailscale. No node configuration, route, reboot, or etcd change.
- Added executable wrapper tests for management target selection and invalid
  inventory rejection before Talos calls.

Bare `talosctl health` still uses automatic discovery. Use `task talos:health`,
or explicitly pass management addresses with `--control-plane-nodes`, when
checking this multi-interface cluster. Changing storage routing merely to make
an automatically selected cable address reachable would be unnecessary scope.

## Verification

- Before: automatic discovery through k8s-2 reproduced a deadline timeout;
  explicit management-address health checks succeeded independently through
  k8s-1, k8s-2, and k8s-3, including etcd, apid, kubelet, and control-plane pods.
- Updated wrapper completed successfully; all three Kubernetes nodes Ready.
- Kustomize rendered; Bash syntax and the repository contracts passed.
- Flux applied repair revision `e8a45178`; supplemental policy generation 1
  matches source. All three Longhorn targets became UP with empty errors on
  their next scrape. All 72 current Prometheus targets UP; the volume-size
  metric reports all 16 Longhorn volumes.
- All 54 Flux Kustomizations and 27 HelmReleases Ready; 16/16 Longhorn
  volumes healthy and 3/3 nodes Ready. No workload restarts or temporary
  diagnostic resources were required. Full contract suite: 354 tests passed.
