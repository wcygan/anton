# kubernetes/apps/databases/

Goal: Maintain platform-scoped Postgres and Redis-compatible operators for shared consumers.

Success means:
- CNPG and Dragonfly remain platform operators, not Harbor-owned resources.
- Downstream consumers depend on the operators and wait for CRDs before applying their own CRs.
- Consumer-owned database/cache CRs live in the consumer namespace.

Stop when: operator manifests reconcile independently and consumers reference generated credentials or CRs through the documented shape.

## Components

- `cloudnative-pg/`: CNPG operator via HelmRepository. Installs the `postgresql.cnpg.io` CRD group.
- `dragonfly-operator/`: vendored upstream manifest in `app/upstream.yaml`; upstream does not publish a Helm repo or OCI chart for this install path.

Both operator Kustomizations use `wait: true` so consumers can declare `dependsOn`.

## Consumer Rules

For Postgres, author a CNPG `Cluster` CR in the consumer namespace. Use Longhorn storage, enable PodMonitor when metrics matter, and reference the generated `<cluster>-app` Secret. The generated Secret includes `username`, `password`, `jdbc-uri`, and `pgpass`.

For Dragonfly, author a `Dragonfly` CR in the consumer namespace. Current consumers use no auth; add auth only with a matching ExternalSecret and explicit consumer changes.

## Validation

```sh
flux get ks -n databases
kubectl get crd | rg 'postgresql.cnpg.io|dragonflydb.io'
```
