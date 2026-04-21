# SeaweedFS baseline — 2026-04-19

Phase 2 + 3 acceptance artifact for [plan 0005 — Adopt SeaweedFS per ADR 0019](https://github.com/wcygan/anton/blob/main/context/plans/0005-adopt-seaweedfs.md). Captures the install shape, the endpoint surface, the credential path, a copy-pasteable smoke test, and the two chart-level surprises we worked around — so future me (or future Harbor) can consume the S3 endpoint without rereading the whole plan log.

> ADR 0019 supersedes ADR 0016. The install uses the canonical `spec.s3` (standalone S3 Deployment) path, not the deprecated `FilerSpec.S3` subtree 0016 originally targeted.

## Cluster shape at install time

- Chart `seaweedfs-operator` **0.1.14**, app **1.0.12** (released 2026-04-19), image `chrislusf/seaweedfs:4.21`
- `HelmRepository` source at `https://seaweedfs.github.io/seaweedfs-operator/helm` (no OCI chart upstream; matches Longhorn's fallback)
- Namespace: `storage`
- Webhook: **on** (validating + mutating webhook configurations installed; certgen Job completes inside helm `--wait`)
- Flux shape: two Kustomizations (`seaweedfs` chart app, `seaweedfs-config` CR + ESO + HTTPRoute); `seaweedfs-config` has `dependsOn: [{name: seaweedfs}]` + `wait: true`

Component counts and placement as of install:

| Component | Kind | Replicas | Node spread |
|---|---|---|---|
| `seaweedfs-master-{0,1,2}` | StatefulSet | 3 | k8s-2 / k8s-3 / k8s-1 (operator hardcodes master podAntiAffinity) |
| `seaweedfs-volume-{0,1,2}` | StatefulSet | 3 | k8s-2 / k8s-3 / k8s-1 (one-per-node — our CR-level affinity, see quirks §2) |
| `seaweedfs-filer-{0,1}` | StatefulSet | 2 | k8s-2 / k8s-1 (embedded leveldb metadata) |
| `seaweedfs-s3-*` | Deployment | 2 | k8s-1 / k8s-2 |

Volume storage: three `mount0-seaweedfs-volume-{0,1,2}` PVCs, **100 GiB each on `longhorn` SC** (RWO), 300 GiB raw. `spec.master.volumeSizeLimitMB: 30000` — 30 GB per volume file, SeaweedFS allocates additional volume files inside each PVC as traffic fills them.

CR-level knobs worth citing verbatim (from `kubernetes/apps/storage/seaweedfs-config/app/seaweed.yaml`):

- `spec.master.defaultReplication: "000"` — **Longhorn owns durability** (ADR 0005). SeaweedFS keeps a single in-cluster copy per blob; the underlying Longhorn volume is 2-replica across nodes.
- `spec.s3.iam: false` — operator default is `true`; explicit override per ADR 0019. (See quirk §4 — the log line lies about this.)
- `spec.s3.configSecret: {name: seaweedfs-s3-config, key: s3.json}` — credentials arrive via ESO (see [Credential retrieval](#credential-retrieval)).

Manifest tree:

```
kubernetes/apps/storage/
  seaweedfs/
    ks.yaml
    app/
      helmrepository.yaml
      helmrelease.yaml                  # webhook.enabled: true (post-Phase 2 commit 2)
      rbac-supplement.yaml              # see quirk §1 — remove when upstream ships the fix
  seaweedfs-config/
    ks.yaml                             # dependsOn: [seaweedfs], wait: true on seaweedfs ks
    app/
      seaweed.yaml                      # the Seaweed CR
      externalsecret.yaml               # ESO → seaweedfs-s3-config Secret
      httproute.yaml                    # envoy-internal/https → seaweedfs-s3:8333
```

## Endpoint surface

| Component | Cluster-internal address | Ports |
|---|---|---|
| master | `seaweedfs-master.storage.svc.cluster.local` | `9333` (HTTP admin), `19333` (gRPC) |
| volume | `seaweedfs-volume-{0,1,2}.storage.svc.cluster.local` | `8444` (HTTP), `18444` (gRPC) |
| filer | `seaweedfs-filer.storage.svc.cluster.local` | `8888` (HTTP), `18888` (gRPC) |
| **s3** | `seaweedfs-s3.storage.svc.cluster.local` | `8333` (HTTP S3) |

Three addresses matter for consumers:

- **In-cluster workloads** (the Harbor path, per plan 0005 Log entry `(c)`): target `http://seaweedfs-s3.storage.svc.cluster.local:8333`. Plain HTTP, no TLS round-trip, no envoy hop. This is what the smoke test exercises.
- **Off-cluster / interactive clients over the LAN**: `https://s3.${SECRET_DOMAIN}` via the `envoy-internal` Gateway + the `seaweedfs-s3` HTTPRoute. Envoy terminates TLS; the backend speaks plain HTTP on `8333`. Resolves via split-horizon DNS through `k8s_gateway`.
- **No public entrypoint.** Internal-only per ADR 0019. No Cloudflare tunnel, no `envoy-external` binding, no `DNSEndpoint`.

**S3 clients must use `https://` directly for the HTTPRoute path.** The shared `network/https-redirect` HTTPRoute 301s all port-80 traffic to https on both gateways, and AWS SigV4 does not survive a redirect (the Authorization header is computed against the original URL). `http://s3.${SECRET_DOMAIN}` will return a 301 that the aws-cli will not follow.

## Credential retrieval

Admin credentials live in **1Password vault `anton`**, item **`seaweedfs-harbor`** (name preserved from the earlier Harbor-groundwork pass), fields `admin-access-key` (20-char hex) and `admin-secret-key` (40-char base64-safe). Never committed.

Wiring:

1. `ExternalSecret seaweedfs-s3-config` (ESO v1, provider `onepasswordSDK` via `ClusterSecretStore onepassword-connect`) pulls both fields with the combined-key syntax `<item>/<field>`.
2. `target.template` assembles them into an `identities[]` JSON document conforming to the SeaweedFS S3 config schema. One `admin` identity with `actions: ["Admin"]`.
3. ESO writes `Secret/seaweedfs-s3-config` (Opaque), key `s3.json`. The operator mounts this at `/etc/sw` in the S3 Deployment and invokes `weed s3 -config=/etc/sw/s3.json`.
4. The Seaweed CR references the Secret via `spec.s3.configSecret: {name: seaweedfs-s3-config, key: s3.json}`.

To extract the creds back out of the running cluster for an ad-hoc smoke test:

```sh
kubectl -n storage get secret seaweedfs-s3-config \
  -o jsonpath='{.data.s3\.json}' | base64 -d | \
  python3 -c 'import json,sys; i=json.load(sys.stdin)["identities"][0]["credentials"][0]; print("AK="+i["accessKey"]); print("SK="+i["secretKey"])'
```

## Smoke test

**In-cluster S3 round-trip** — passed on install day, ~10 objects written + read + deleted, no errors:

```sh
# Pull live admin creds from the ESO-managed Secret
AK=$(kubectl -n storage get secret seaweedfs-s3-config -o jsonpath='{.data.s3\.json}' \
     | base64 -d | python3 -c 'import json,sys; print(json.load(sys.stdin)["identities"][0]["credentials"][0]["accessKey"])')
SK=$(kubectl -n storage get secret seaweedfs-s3-config -o jsonpath='{.data.s3\.json}' \
     | base64 -d | python3 -c 'import json,sys; print(json.load(sys.stdin)["identities"][0]["credentials"][0]["secretKey"])')

kubectl -n storage run --rm -i smoke-test \
  --image=amazon/aws-cli:2.17.0 --restart=Never \
  --env=AWS_ACCESS_KEY_ID=$AK --env=AWS_SECRET_ACCESS_KEY=$SK \
  --env=AWS_EC2_METADATA_DISABLED=true \
  --command -- sh -c '
    set -e
    S3=http://seaweedfs-s3.storage.svc.cluster.local:8333
    aws --endpoint-url=$S3 s3 mb s3://smoke-test
    echo hello-anton-seaweedfs | aws --endpoint-url=$S3 s3 cp - s3://smoke-test/hello.txt
    aws --endpoint-url=$S3 s3 ls s3://smoke-test/
    aws --endpoint-url=$S3 s3 cp s3://smoke-test/hello.txt -
    aws --endpoint-url=$S3 s3 rm s3://smoke-test/hello.txt
    aws --endpoint-url=$S3 s3 rb s3://smoke-test
    echo SMOKE_PASS
  '
```

Expected tail of output:

```
2026-04-20 04:25:29         22 hello.txt
hello-anton-seaweedfs
delete: s3://smoke-test/hello.txt
remove_bucket: smoke-test
SMOKE_PASS
```

**Off-cluster HTTPRoute path** (not verified from the install session because that session ran over a Tailscale-proxy kubectl context with no LAN DNS; verify from a machine whose resolver forwards `*.wcygan.net` to `k8s_gateway` at `192.168.1.102`):

```sh
aws --endpoint-url=https://s3.wcygan.net --region=us-east-1 s3 mb s3://laptop-smoke
aws --endpoint-url=https://s3.wcygan.net s3 rb s3://laptop-smoke
```

## Known quirks — what we learned the hard way

Chart 0.1.14 + app 1.0.12 shipped four days after controller PR #200 (standalone S3 Deployment) landed. Two bugs made it into the release because the Helm RBAC manifest is hand-maintained separately from the controller's `+kubebuilder:rbac` markers; one CRD field the plan assumed was present is not. Both are documented in plan 0005 Log; the durable summary lives here.

### 1. RBAC supplement required on chart 0.1.14

Chart 0.1.14's `seaweedfs-operator-manager-role` ClusterRole is missing two permissions the controller needs:

- **`apps/deployments`** — controller PR #200 ([seaweedfs-operator#200](https://github.com/seaweedfs/seaweedfs-operator/pull/200)) added a `+kubebuilder:rbac` marker for Deployments (standalone S3 is a Deployment, not a StatefulSet) but `deploy/helm/templates/rbac/role.yaml` was not regenerated from `config/rbac/`. First reconcile after applying a `Seaweed` CR with `spec.s3` fails:

    > `deployments.apps is forbidden: User "system:serviceaccount:storage:seaweedfs-operator" cannot create resource "deployments" in API group "apps" in the namespace "storage"`

    The `scratch-s3` Service is created (Service RBAC is fine); the Deployment is never created, so S3 pods never exist.

- **`monitoring.coreos.com/servicemonitors`** — gated behind `{{- if .Values.serviceMonitor.enabled }}` in the chart, but `cmd/main.go` unconditionally registers the ServiceMonitor scheme and each component has a `controller_*_servicemonitor.go` reconciler, so the controller-runtime cached client starts a reflector on ServiceMonitors whether the values flag is set or not. Produces an endless stream of `reflector.go:150 Failed to watch *v1.ServiceMonitor: ... is forbidden` error-level log lines. Doesn't block reconciles; just pollutes the log stream and breaks any "operator log is clean" alerting.

**Our workaround: `kubernetes/apps/storage/seaweedfs/app/rbac-supplement.yaml`.** A supplemental `ClusterRole` + `ClusterRoleBinding` that grants both missing rules to the chart-created `seaweedfs-operator` ServiceAccount in `storage`. Authored as its own resource rather than an in-place patch because helm 4 server-side-apply refuses to let an in-place patch on `.rules` survive a `helm upgrade` (we tried — `--force-conflicts` reverts the patch). The supplement is owned by Flux's kustomize-controller field manager, not helm-controller, so there is no field overlap.

**Removal condition:** chart ≥ 0.1.15 (or whichever release) with `deploy/helm/templates/rbac/role.yaml` regenerated from `config/rbac/role.yaml`. Verify before deleting:

```sh
helm pull seaweedfs-operator/seaweedfs-operator --version <new> --untar --untardir /tmp/sw
grep -E 'deployments|servicemonitors' /tmp/sw/seaweedfs-operator/templates/rbac/role.yaml
# Both rules must be present and the servicemonitors rule must NOT be {{- if serviceMonitor.enabled }} gated.
```

No upstream issue is open as of 2026-04-19; if someone else files one or a fix lands, re-verify and delete the supplement in a single follow-up commit.

### 2. Chart 0.1.14's CRD does not expose `topologySpreadConstraints`

The plan's earlier draft assumed the per-component spec had `topologySpreadConstraints` because most modern Helm charts do. Chart 0.1.14 does not — on any of `master`, `volume`, `filer`, `s3`. First Flux reconcile of `seaweedfs-config` fails server-side dry-run:

> `Seaweed/storage/seaweedfs dry-run failed: failed to create typed patch object: .spec.volume.topologySpreadConstraints: field not declared in schema`

Verify via `kubectl get crd seaweeds.seaweed.seaweedfs.com -o json | jq '.spec.versions[0].schema.openAPIV3Schema.properties.spec.properties.volume.properties | keys'` — you get `affinity`, `nodeSelector`, `tolerations`, `schedulerName`, etc., but no `topologySpreadConstraints`.

**Workaround:** use `spec.<component>.affinity.podAntiAffinity.requiredDuringSchedulingIgnoredDuringExecution` with the operator's actual pod labels. Verified from `seaweedfs-operator/1.0.12/internal/controller/controller_volume.go::labelsForVolumeServer`, the labels are `app.kubernetes.io/name=seaweedfs`, `/component=<master|volume|filer|s3>`, `/instance=<Seaweed-CR-name>`, `/managed-by=seaweedfs-operator`. For the anton CR named `seaweedfs`:

```yaml
volume:
  replicas: 3
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - topologyKey: kubernetes.io/hostname
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: seaweedfs
              app.kubernetes.io/component: volume
              app.kubernetes.io/instance: seaweedfs
```

Same idiom works for any other component where one-per-node placement matters. The master StatefulSet ships its own hardcoded anti-affinity from the operator, so explicit CR-level constraints are only needed for `volume` (and potentially `filer` / `s3` if you start caring about their spread).

**Lesson for future plan drafts:** validate field-sets against the live CRD (`kubectl get crd X -o json | jq ...`) or at minimum a `kubectl apply --dry-run=server` before pushing the manifest. Both errors above would have caught themselves during plan authorship, not first reconcile.

### 3. DNS race on StatefulSet bootstrap — self-heals, don't chase it

Every master / volume / filer pod crash-loops 2–3 times on first boot with:

```
F master.go:… Filer listener error: listen tcp: lookup
  seaweedfs-master-0.seaweedfs-master-peer.storage on 10.43.0.10:53: no such host
```

The pod tries to bind `<pod>.<peer-headless-service>.<ns>` as its listen address before CoreDNS has published the A record for the new pod in the headless peer Service. kubelet's `CrashLoopBackOff` burns 20 s → 40 s → ~60 s; the race is typically won by the second or third retry, and the pod reaches `Ready` within ~1 minute of first start.

Same pattern hit the Phase 1 scratch shakeout. It's cosmetic — **all replaced StatefulSet pods pay this cost on recreate, and a traffic generator driving the live S3 endpoint during a `kubectl delete pod seaweedfs-filer-0` saw zero PUT failures** because the surviving filer held the work. Don't add readiness-gate workarounds; the recovery path is load-bearing but reliable.

S3 Deployment pods do not hit this because they bind `0.0.0.0:8333` rather than a pod-specific DNS name.

### 4. `spec.s3.iam: false` log line is misleading, not wrong

With `spec.s3.iam: false` set, the S3 pods still log:

```
Starting S3 API Server with standard IAM
```

But the `configSecret`-defined `admin` identity works, and during Phase 1 scratch the anonymous-credential path (`AWS_ACCESS_KEY_ID=anon`) also worked with `iam: false` and no `configSecret`. The flag controls IAM *enforcement semantics*, not whether the IAM subsystem starts. Confusing, not broken.

### 5. `FilerSpec.S3` is a trap — don't revert to it

ADR 0016 originally targeted the deprecated `filer.s3.enabled` path. ADR 0019 supersedes that decision on the canonical `spec.s3` (standalone Deployment) path. The validating webhook (once `webhook.enabled: true`) **rejects** CRs that try to set both:

```
Error from server (Forbidden): error when creating "STDIN": admission
webhook "vseaweed.kb.io" denied the request: spec.s3 and
spec.filer.s3.enabled cannot both be set; spec.filer.s3 is deprecated —
migrate to the top-level spec.s3 standalone gateway
```

Leave `spec.filer.s3` unset. Bare `spec.s3` is the canonical shape.

## Verdict + forward-looking

Acceptance criteria from plan 0005:

| # | Criterion | Status |
|---|---|---|
| 1 | `seaweedfs-operator` HelmRelease reconciles green on chart 0.1.14 / operator 1.0.12 | **Met.** `helm list -n storage` → `DEPLOYED`; `flux get hr` → Ready, revision v2 (post-webhook flip) |
| 2 | Seaweed CR reports all components Ready: master 3/3, volume 3/3 one-per-node, filer 2/2, s3 2/2 | **Met.** Placement verified via `kubectl get pods -o wide` |
| 3 | S3 endpoint reachable; smoke test passes (mb/PUT/GET/DELETE) | **Met** on in-cluster path (this doc's recipe). HTTPRoute path is configured + Accepted; end-to-end LAN test is an operational follow-up, not a cluster-correctness test |
| 4 | Filer-HA verified under `filer.replicas: 2` | **Met** via Phase 1 scratch-namespace pod-kill shakeout — traffic continuous (0 PUT errors), replaced pod recovers in ~60 s |
| 5 | Webhook bootstrap dance complete (`webhook.enabled: true` in final state) | **Met.** validating + mutating webhook configurations active; `vseaweed.kb.io` correctly denies dual-config CRs |

Backups are explicitly deferred per ADR 0019 until a real data workload justifies the bucket-target config. Harbor-on-SeaweedFS is a successor plan (see ADR 0015 and the Phase 4 note in plan 0005).

## Cleanup / uninstall path

Ordered, safe. Deleting the HelmRelease first orphans the Seaweed CR and causes the controller to stop managing its children — always tear down the CR first.

```sh
# 1. Delete the Seaweed CR. Operator will GC all child StatefulSets, the S3 Deployment,
#    Services, and the webhook certgen Secret. Watch `kubectl get pods -n storage -w`
#    until nothing seaweedfs-shaped remains.
kubectl -n storage delete seaweed seaweedfs

# 2. Remove the seaweedfs-config Flux app (deletes ExternalSecret + HTTPRoute,
#    and reconciles the CR absence idempotently).
#    Edit kubernetes/apps/storage/kustomization.yaml to remove the seaweedfs-config line,
#    commit, push, reconcile. Do NOT kubectl delete the Kustomization directly — Flux owns it.

# 3. Remove the seaweedfs Flux app (operator + CRD + RBAC supplement).
#    Same procedure: drop the line from the parent kustomization, commit, push, reconcile.

# 4. (Optional) Delete lingering Longhorn PVCs if you want the backing storage reclaimed.
kubectl -n storage get pvc | grep seaweedfs
# kubectl -n storage delete pvc mount0-seaweedfs-volume-{0,1,2}
```

**Do not delete the RBAC supplement ahead of the operator** — if the operator reconciles even once without the supplement in place, it re-fails with the `apps/deployments forbidden` error. The supplement lives in the `seaweedfs` Kustomization specifically so the two are torn down atomically.

## Pointers

- Decision: [`context/adrs/0019-seaweedfs-on-canonical-spec-s3.md`](https://github.com/wcygan/anton/blob/main/context/adrs/0019-seaweedfs-on-canonical-spec-s3.md) (supersedes [0016](https://github.com/wcygan/anton/blob/main/context/adrs/0016-adopt-seaweedfs-today-via-filerspec-s3.md))
- Plan: [`context/plans/0005-adopt-seaweedfs.md`](https://github.com/wcygan/anton/blob/main/context/plans/0005-adopt-seaweedfs.md) — full Phase 1 scratch shakeout and Phase 2 reconcile diagnostics
- Skill: `.claude/skills/seaweedfs-docs/` — upstream reference (architecture, CLI, operator CRD schema, S3 API coverage). Auto-loads on `seaweedfs`, `weed shell`, `Seaweed CRD`, etc.
- Release notes: https://github.com/seaweedfs/seaweedfs-operator/releases/tag/1.0.12
- Controller source (labels + RBAC markers): https://github.com/seaweedfs/seaweedfs-operator/tree/1.0.12
- Harbor consumer anchor: [ADR 0015](https://github.com/wcygan/anton/blob/main/context/adrs/0015-adopt-harbor-as-in-cluster-registry.md) — the successor plan that turns this baseline into a production dependency
