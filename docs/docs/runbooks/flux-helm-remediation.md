# Flux Helm Remediation Deadlocks

Use this runbook when a Flux HelmRelease repeats install or upgrade failure.
It covers timeout, cleanup, rollback, hook cycles, and immutable Jobs.

## Safety boundary

Start with read-only commands. A force reconcile, release reset, object
deletion, suspension, rollback, or restart requires explicit operator approval.

Record the current Kubernetes context, namespace, HelmRelease, Git revision,
HelmRelease generation, release revision, and incident window.

## Collect the release timeline

```sh
mise exec -- kubectl config current-context
mise exec -- flux get hr -A
mise exec -- kubectl -n <namespace> describe helmrelease <name>
mise exec -- kubectl -n <namespace> get helmrelease <name> -o yaml
mise exec -- kubectl -n <namespace> get helmrelease <name> \
  -o jsonpath='{.spec.releaseName}{"\t"}{.spec.storageNamespace}{"\t"}{.spec.targetNamespace}{"\t"}{.status.history[0].name}{"\t"}{.status.history[0].namespace}{"\n"}'
mise exec -- kubectl -n <namespace> get events \
  --field-selector involvedObject.kind=HelmRelease,involvedObject.name=<name> \
  --sort-by=.metadata.creationTimestamp
mise exec -- kubectl -n flux-system logs deploy/helm-controller \
  --since=30m --tail=500 | rg '<namespace>|<name>|error|rollback|cleanup|timeout'
mise exec -- helm -n <release-storage-namespace> history <helm-release-name>
```

Bound event and log output to the incident window. Redact any unexpected
credential value before retaining output.

Resolve the Helm release name and storage namespace from the desired fields
and current status history. Do not assume they equal the HelmRelease identity.

Build this timeline:

| Field | Record |
|---|---|
| Source | Git revision and HelmRelease generation |
| Helm action | Install, upgrade, test, cleanup, or rollback |
| Release | Previous and attempted Helm revisions |
| First error | Exact reason and message |
| Cleanup | Resources removed after failure |
| Rollback | Target revision and result |
| Workload | Deployment, Job, hook, or RBAC state |
| Current state | Ready condition and last transition time |

## Classify the first failure

### Migration hook cycle

A post-install migration hook can run after workloads become ready. Those
workloads can also wait for the same migration in init containers.

This creates a cycle:

```text
Flux waits for workloads -> workloads wait for migration -> hook waits for install
```

Anton's Airflow chart avoids this cycle with
`migrateDatabaseJob.useHelmHooks: false`. The migration renders as a normal
Flux-owned Job. The Airflow foundation contract protects this setting.

Use this repair only when the chart and workload dependency match the cycle.

### Failed-upgrade cleanup removes prerequisites

`cleanupOnFail` can remove resources created by the failed upgrade. A later
attempt can then fail on missing RBAC or another prerequisite.

Prove the earlier failure before treating the missing resource as the cause.
Compare Helm events with the current resource owner and release revision.

### Immutable migration Job

Kubernetes rejects changes to immutable Job template fields. Require the exact
immutable-field error before using this classification.

Compare the existing Job owner, annotations, completion state, and pod template
with the newly rendered Job. Determine whether Helm, Flux, or another owner
must replace it.

Keep a completed migration Job until its database effect and rollback path are
known. Job deletion is a live mutation and is not a diagnostic shortcut.

### Timeout and rollback

Record the HelmRelease timeout and the slowest required controller transition.
Determine whether rollback began before that transition could complete.

Increasing a timeout is valid only when current evidence proves slow progress.
It cannot repair a deterministic chart, RBAC, hook, or immutable-field error.

## Choose the owner-side correction

| Finding | Correction owner |
|---|---|
| Wrong chart values or hook mode | Git repository |
| Missing Flux dependency | Git repository |
| Failed external dependency | External system owner |
| Correct desired state with stale stateless object | Approved controller reset |
| Immutable Job template conflict | Chart or Job lifecycle owner |
| Unknown first cause | Continue read-only evidence collection |

Use one causal mutation at a time. Observe its predicted transition before any
second action.

## Mutation handoff

Return this contract before an approved live action:

```text
Owner: <Git, Flux, Helm, Kubernetes, or external system>
Target: <namespace and exact object>
Action: <one command or file change>
Preconditions: <revision, state, recovery proof>
Expected transition: <condition sequence>
Timeout: <bounded duration>
Stop condition: <failure or ambiguity>
Rollback: <exact operation>
Acceptance: <revision, readiness, events, workload result>
Cleanup: <temporary resources or listeners>
```

## Acceptance

Verify the intended Git revision, Flux source revision, HelmRelease generation,
release revision, applied objects, stable workload readiness, and dependency
result. Check the prior recurrence window when practical.

Confirm that no temporary resource or unmanaged live drift remains.
