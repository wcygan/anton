# kubernetes/apps/storage/

Goal: Maintain Longhorn, SeaweedFS, and their config siblings while preserving the storage-network and S3 endpoint contracts.

Success means:
- `longhorn/` carries the chart release and `longhorn-config/` carries supporting raw config such as the `longhorn-storage` NAD.
- SeaweedFS chart/operator resources stay separated from the `Seaweed` CR and app-facing config.
- Longhorn traffic continues to use the `storage/longhorn-storage` NetworkAttachmentDefinition on the SFP+/VXLAN fabric.

Stop when: storage manifests keep the chart-vs-config split, important workarounds remain justified, and read-only checks can confirm current status.

## Longhorn

`longhorn/` sets `defaultSettings.storageNetwork: storage/longhorn-storage`. The NAD lives in `longhorn-config/` because chart upgrades should stay atomic and config resources need their own lifecycle.

Use existing Longhorn references before node or disk work:

- `context/adrs/0005-adopt-longhorn-for-block-storage.md`
- `docs/docs/notes/longhorn-storage-network-host-shim.md`
- `.claude/skills/longhorn-node-ops/references/talos.md`

## SeaweedFS

In-cluster S3 clients use `http://seaweedfs-s3.storage.svc.cluster.local:8333`. LAN/off-cluster clients use `https://s3.${SECRET_DOMAIN}` through `envoy-internal`.

Keep the chart 0.1.14 workarounds until upstream proves they are fixed:

- `rbac-supplement.yaml` for missing operator permissions.
- Pod anti-affinity instead of topology spread constraints because the CRD does not expose TSC fields.

Use top-level `spec.s3`; `filer.s3.enabled` conflicts with the canonical shape.

## Validation

```sh
flux get ks -n storage
flux get hr -n storage
kubectl -n storage get pods,pvc
```
