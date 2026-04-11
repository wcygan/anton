# Layer 6 — Apps

Only meaningful if layers 3-5 are green. This layer **counts and categorizes** app-level failures; it does not deep-dive individual apps — hand those off to `debug-flux-reconciliation` or direct log reading.

## The fast pulse

```sh
flux get ks -A --status-selector ready=false
flux get hr -A --status-selector ready=false
```

Zero rows in both = the Flux view of apps is clean. Good signal, but go on to the pod-level check below because a HelmRelease can report Ready while its workload crash-loops.

## Pod-level anomalies

```sh
# Anything not Running or Succeeded
kubectl get pods -A \
  --field-selector=status.phase!=Running,status.phase!=Succeeded \
  -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,PHASE:.status.phase,REASON:.status.reason'
```

**Phases to care about**:
- `Pending` for > 2min → scheduling issue (resources, taints, PVC, image pull)
- `Failed` → permanent; delete or let its controller retry
- `Unknown` → node is gone or kubelet is unreachable (drop to `talos-inspect`)

## Crash loops

```sh
kubectl get pods -A -o json | jq -r '
  .items[]
  | select(.status.containerStatuses != null)
  | .status.containerStatuses[]
  | select(.restartCount > 3)
  | "\(.restartCount)\t\(.name)\t\(.lastState.terminated.reason // "running")"' \
  | sort -rn | head -20
```

Restart count > 3 in normal steady state is always worth investigating. Common reasons:
- `OOMKilled` → bump memory limits in the HelmRelease values
- `Error` with exit 1 → read the previous container logs: `kubectl logs <pod> --previous`
- `CrashLoopBackOff` with no terminated state → liveness probe too tight, or app failing early before printing logs

## Recent warning events

```sh
kubectl get events -A \
  --field-selector type=Warning \
  --sort-by=.lastTimestamp \
  -o custom-columns='TIME:.lastTimestamp,NS:.metadata.namespace,REASON:.reason,OBJECT:.involvedObject.name,MSG:.message' \
  | tail -30
```

Skim for patterns — one noisy app is a single bug; warnings across many namespaces is usually a platform-layer problem you missed in layer 5.

**Events to care about**:
- `FailedScheduling` → scheduler cannot place the pod (tolerations, PVC, resources)
- `FailedMount` → PVC/CSI issue; note that Anton has no storage layer right now (Rook-Ceph removed), so this should be rare
- `Unhealthy` → liveness/readiness probe failing
- `BackOff` → the pod is in CrashLoopBackOff with increasing delays
- `ImagePullBackOff` / `ErrImagePull` → bad tag, wrong registry, expired imagePullSecret
- `FailedCreate` on a ReplicaSet → usually an admission-controller denial (PSA, quota)

## Categorize, don't fix

Your output from this layer should be a short categorized list, not a root-cause analysis:

```
CRASH: 2 pods in databases/postgres (restartCount 47, OOMKilled)
STUCK: 1 HelmRelease in media/radarr (dependency not ready)
WARNING: 15 FailedScheduling events in default for app-foo
```

Hand each bucket to the right next step:
- CRASH → direct log reading; `kubectl logs --previous`
- STUCK → `debug-flux-reconciliation`
- WARNING → whichever skill owns the subsystem (e.g. `expose-service` for HTTPRoute complaints)

## What this layer is NOT

- Not a capacity planner — use `kubectl top` separately if you want resource trends
- Not a SLO dashboard — if the cluster needs alerting, that's observability, which was descoped
- Not a place to take action — this skill is read-only
