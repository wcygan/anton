# kubernetes/apps/databases/

Platform-scoped CRD operators for Postgres and Redis-compatible caches. **Not Harbor-specific** — Harbor (ADR 0015 / plan 0006) is the first consumer, but any future workload needing a Postgres `Cluster` CR or a DragonflyDB `Dragonfly` CR lives on these operators.

## Contents

- `cloudnative-pg/` — CNPG operator (chart `cloudnative-pg/cloudnative-pg` via `HelmRepository`, no upstream OCI). Installs the `postgresql.cnpg.io` CRD group. Operator itself is lightweight (100m CPU / 256Mi mem request); bump if cluster count grows into the dozens.
- `dragonfly-operator/` — DragonflyDB operator (chart lives *inside* `github.com/dragonflydb/dragonfly-operator` at `/charts/dragonfly-operator`, pulled via `GitRepository` with `ref.tag: v1.5.0` — upstream publishes neither an OCI chart nor a Helm repo). Installs the `dragonflydb.io` CRD group.

Both Kustomizations set `wait: true` so downstream apps can `dependsOn` them with confidence.

## Quirks to know

- **`GitRepository` chart source for Dragonfly.** The hook `.claude/hooks/check_3_file_pattern.py` accepts `app/gitrepository.yaml` as a valid chart source alongside OCI and HelmRepository (fixed 2026-04-21). To bump Dragonfly, edit `ref.tag` in `gitrepository.yaml`; Renovate needs a `# renovate: datasource=github-tags depName=dragonflydb/dragonfly-operator` comment on that line to auto-bump (not yet added).
- **CNPG-managed app Secret naming.** When a CNPG `Cluster` CR has `bootstrap.initdb.owner: <user>`, the operator creates `Secret/<cluster-name>-app` with keys `username` / `password` / `jdbc-uri` / `pgpass`. Harbor's Helm chart expects a Secret with a `password` key via `database.external.existingSecret` — this matches out of the box, no reshaping needed. **Don't** build an ExternalSecret that duplicates this Secret; reference CNPG's directly.
- **Dragonfly has no auth.** The Dragonfly CR doesn't set a password by default. Consumers use `redis.external.addr` only and leave `existingSecret` empty. If auth is ever needed, add `--requirepass` to the CR's `args` and set up an ExternalSecret — but be aware Dragonfly's clustering uses its own internal protocol that won't speak your password.
- **No smoke Cluster/Dragonfly CRs here.** The intended pattern is: Harbor (or the next consumer) brings its own `Cluster` / `Dragonfly` CR. See `kubernetes/apps/registries/harbor-config/` for Harbor's shape — sizing, replicas, and the `monitoring.enablePodMonitor: true` pattern are the reference.

## Usage

For a new consumer needing Postgres:

1. Author a `Cluster` CR in the consumer's namespace. Set `instances: 3` for HA, `storage.storageClass: longhorn`, `monitoring.enablePodMonitor: true`. Pin `imageName` to a specific PG major.minor (Renovate handles the patch bumps).
2. Add `dependsOn: [{name: cloudnative-pg, namespace: databases}]` + `wait: true` to the consumer's Kustomization so the CR doesn't race the operator.
3. Reference the auto-generated `<cluster>-app` Secret for credentials; don't try to precompute them.

For a new Redis consumer, use a `Dragonfly` CR with `replicas: 3`; same `dependsOn` pattern.

## Out of scope

- **Backup strategy for CNPG clusters.** ADR 0015 flags Harbor's DB as irreplaceable; plan 0006 Phase 7 defers this to a separate successor plan. When that plan opens, target S3 (SeaweedFS bucket `cnpg-backups` or similar) via CNPG's built-in `Backup` / `ScheduledBackup` CRs.
