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

Preserve the configured `externalURL` unless an approved change addresses the verified Tailscale authentication-realm issue. Inspect the actual `WWW-Authenticate` header and client network boundary first; see `docs/docs/guides/harbor.md` and the shared Harbor authentication reference.

## Validation

```sh
flux get ks -n registries
flux get hr -n registries
kubectl -n registries get pods,ingress,secrets
```
