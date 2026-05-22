# kubernetes/apps/registries/

Goal: Maintain Harbor as Anton's internal OCI registry without breaking its CNPG, Dragonfly, S3, or Tailscale contracts.

Success means:
- `harbor-config/` owns Harbor's database, cache, secrets, and Tailscale ingress prerequisites.
- `harbor/` owns the Harbor HelmRelease and depends on `harbor-config`.
- Harbor continues to store blobs in SeaweedFS S3 with redirects disabled.

Stop when: the dependency direction is preserved and Harbor health can be checked with read-only API or Kubernetes status commands.

## Load-Bearing Shape

Dependency chain:

```text
databases/cloudnative-pg + databases/dragonfly-operator
  -> registries/harbor-config
  -> registries/harbor
```

`harbor` depends on `harbor-config` because the chart needs the CNPG `Cluster`, Dragonfly CR, and required Secrets before install.

Keep `persistence.imageChartStorage.type: s3`, endpoint `http://seaweedfs-s3.storage.svc.cluster.local:8333`, bucket `harbor`, and `disableredirect: true`. SeaweedFS does not support Harbor's pre-signed redirect flow reliably here.

Keep `externalURL: http://192.168.1.106` unless you are intentionally fixing the Tailscale auth-realm issue. That issue is documented in `docs/docs/notes/harbor-registry.md` and this namespace's Claude precedent.

## Validation

```sh
flux get ks -n registries
flux get hr -n registries
kubectl -n registries get pods,ingress,secrets
```
