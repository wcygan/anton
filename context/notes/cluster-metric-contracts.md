# Cluster metric contracts

This note defines version 1 of Anton cluster metric contracts. It supports
plan 0022. A metric contract defines one measure. It does not create authority
for repository edits or live cluster actions.

## Contract version 1

Each metric contract contains these fields.

```text
Name:
Role:
Beneficiary:
Critical scope:
Numerator and denominator:
Start event:
Stop event:
Time window:
Environment and workload:
Evidence source and query:
Aggregation and sample count:
Baseline:
Direction:
Target:
Noise tolerance:
Independent guards:
Editable levers:
External factors:
Authority required:
Checkpoint and rollback:
Stop condition:
Result record:
```

Change this schema only with a new version. Keep prior metric records with
their original schema version.

## Read-only snapshot

Snapshot time: 2026-08-10.

- Branch: `main`.
- Revision display form: `50f05694`.
- Strict failure count at source `50f05694`: 1.
- Strict failure count in the uncommitted M1-E1 candidate: 0.
- Failed Kustomizations: five.
- First failure: `storage/seaweedfs-config`.
- Dependent failures: `iceberg-demo/spark-fixture`, `iceberg-demo/trino`, `observability/loki`, and `observability/otel-collector`.
- Aggregate guard: 47 applications, four validators, 69 tests, and 5.178 seconds.

The known escape is the literal shell variable `bucket` in the generated
`seaweedfs-bucket-provisioner` ConfigMap. Flux strict postBuild substitution
rejects it. The local storage validator checks shell syntax and source shape.
It does not model this Flux behavior.

The snapshot alone did not establish convergence, recovery, restart, OOM, or
saturation baselines. Later sections record the available read-only evidence
and its limits.

### Cross-metric guard experiment G1-E1

Experiment ID: G1-E1.

Metric contract version: 1.

Hypothesis: A verified Kubernetes context and endpoint prevent both live
observers from reporting another cluster as Anton.

Single lever: Bind both observers to one shared verified `kubectl` prefix.

Expected mechanism: The shared helper verifies the canonical context and API
endpoint against live Tailscale identity, explicit overrides, or the committed
fallback target before the first read. It returns fixed errors without target
names.

Baseline samples: Zero of two live observers verified both target fields.

Target and tolerance: Two of two observers must verify and bind both fields.
Allow zero ambient-context reads and zero identity-bearing errors.

Guards: Require wrong-context, missing-context, wrong-endpoint, and zero-read
tests. Run both observers read-only. Run the full contract guard.

Authority: Repository edits and read-only cluster observation only. No live
mutation authority applies.

Git checkpoint: Use an exact inverse patch for the target helper, observers,
and focused tests.

Live preconditions: The canonical Anton kubeconfig and expected API endpoint
must be available. Stop before any observer read if target proof fails.

Stop and rollback triggers: Restore only experiment hunks if either observer
can use an ambient target, an error exposes identity, or a guard fails.

Rejected candidate: The first helper derived expected identity from the same
kubeconfig that it checked. Independent Terra review proved that a fake
operator-style context and endpoint passed. That candidate was rejected. The
replacement uses an independent identity source and keeps the regression case.

Commands and evidence times: On 2026-08-11, 63 focused guard and observer tests
passed. Both
read-only observers then completed through the verified prefix. The M2 result
still had 18 resources and one incomplete resource. The M4 result stayed
partial. The final full guard passed 111 tests in 5.054 seconds. The sanitized
M2 observation is retained in
`context/notes/cluster-metric-evidence/2026-08-11T011440Z-m2.json`.

Result: Verified-target coverage improved from zero of two to two of two.

Decision: Keep.

Follow-up: Keep target verification as an independent guard for every future
live observer.

## Metric 1: Escaped deterministic GitOps failures

Name: Escaped deterministic GitOps failures per accepted revision.

Role: Outcome.

Beneficiary: Cluster operators and all shared platform users.

Critical scope: Kubernetes and Flux source changes. Include render,
substitution, schema, dependency, and admission failures.

Numerator and denominator: The numerator is accepted revisions that cause a
deterministic GitOps failure. The denominator is accepted revisions that touch
Kubernetes or Flux sources.

Start event: An accepted revision enters the configured Git source.

Stop event: Flux reports the revision Ready, or the revision has one
deterministic failure with a recorded cause.

Time window: Rolling 30 accepted revisions.

Environment and workload: The Anton repository and its Flux-managed cluster.

Evidence source and query: Git history, Flux Git source revision, and
Kustomization conditions. The current known case uses
`storage/seaweedfs-config` and its dependent Kustomizations.

Aggregation and sample count: Count the numerator and denominator across 30
accepted revisions. Keep each revision as one record.

Baseline: Strict failure count 1 at source `50f05694`. The uncommitted M1-E1
candidate has strict failure count 0. The 30-revision baseline is not
established.

Direction: Lower is better.

Target: Zero escaped deterministic failures in the rolling window.

Noise tolerance: Zero. A deterministic escape is never noise.

Independent guards: Keep validation deterministic and bounded. Do not read
Secret values. Preserve valid literal shell variables. Preserve all 47
application checks.

Editable levers: Regression fixtures and repository validation logic.

External factors: Flux version, controller configuration, source revision,
and external Git source availability.

Authority required: The explicit hill-climbing request granted repository-edit
authority for M1-E1. Live authority was not granted. Flux reconciliation,
Kubernetes, Talos, and external-provider actions require separate approval.

Checkpoint and rollback: Use an exact inverse patch for the current fixture
or validator experiment. Restore only loop-owned hunks. Do not use reset,
checkout, broad cleanup, or a live rollback.

Stop condition: Stop if the fixture cannot distinguish a valid literal shell
variable from a Flux substitution token. Stop if the guard fails, the result
is unparseable, user edits overlap the experiment, or new authority is needed.

Result record: Record revision, source path, failure class, evidence time,
measure result, guard result, decision, and follow-up.

### Experiment M1-E1

Experiment ID: M1-E1.

Metric contract version: 1.

Hypothesis: A controller-equivalent substitution check detects the current
`bucket` escape before Flux applies the revision.

Single lever: Add one failing regression fixture. Extend one shared contract
validator only as needed for that fixture.

Expected mechanism: The validator detects unescaped Flux substitution syntax
in generated ConfigMap content. It allows valid literal shell variables.

Baseline samples: The failure baseline snapshot time was
2026-08-10T23:22:56Z at source revision `50f05694`. The known failure was in
`kubernetes/apps/storage/seaweedfs-config/app/provision-buckets.sh`. Its
failure class was strict Flux postBuild substitution. The rolling baseline is
not established.

Target and tolerance: Detect the known escape. Zero tolerance for a missed
deterministic failure.

Guards: Run the narrow fixture. Then run
`mise exec -- task contracts:validate`. Do not inspect Secret values. Keep
the aggregate guard within a documented runtime bound.

Authority: The explicit hill-climbing request authorized the repository edit.
It did not authorize a Flux reconciliation, Kubernetes action, Talos action,
synthetic traffic, or external-provider action.

Git checkpoint: The exact inverse patch owns only the script, validator, and
test hunks. Pre-experiment SHA-256 values were:

- Script: `54caba5b3e94c465b9a9d81290bc8934d345a3ba94249a2b8ef356a5dbd78708`.
- Validator: `9490bc32ff9b66b4669961e003cc3d265b8e987dd29665ffa7d42bf6fa401596`.
- Test: `df4ed6c360588931daf50bbdd0a234e501d851a26e380e4f7f9ea123b420c2f8`.

Live preconditions: Not applicable. This experiment remains repository-only
unless a later approval authorizes Flux confirmation.

Stop and rollback triggers: Stop and restore the exact inverse patch if the
fixture fails to model the known error, valid shell variables are rejected,
the aggregate guard fails, the result is unparseable, or overlapping user
edits appear. Stop without rollback if ownership is unclear. Stop before a
live action that lacks approval.

Commands and evidence times: On 2026-08-10, run
`mise exec -- python3 -m unittest scripts.tests.test_seaweedfs_bucket_provisioner`.
Five focused tests passed. Run
`mise exec -- python3 scripts/validate-storage-contract.py`.
The validator passed. Run `mise exec -- task contracts:validate`. The aggregate
guard passed 47 applications, four validators, and 71 tests in 5.185 seconds.

Independent verification: The strict metric was 0. The experiment did not
read Secret values. Independent review reported no findings.

Result: Kept. At 2026-08-11T00:43:07Z, the final remeasure had
`strict_failure_count=0`. The count changed from 1 to 0 in the uncommitted
candidate.

Decision: Keep.

Follow-up: Obtain separate live authority before Flux confirmation. Measure
the accepted-revision rolling baseline after the candidate is accepted.

### Experiment M1-E2

Experiment ID: M1-E2.

Metric contract version: 1.

Hypothesis: Strict substitution for every generated ConfigMap root closes the
remaining known preflight coverage gap.

Single lever: Add one generic strict postBuild ConfigMap validator.

Expected mechanism: The validator discovers each application root with a
`configMapGenerator`, renders its ConfigMaps, and runs strict Flux substitution
with a PATH-only environment.

Baseline samples: One of two generated ConfigMap roots had a strict
postBuild check. Coverage was 50 percent.

Target and tolerance: Cover two of two roots. Allow zero missed roots, zero
unescaped runtime variables, and zero empty ConfigMap outputs.

Guards: Prove an unescaped variable fails and an escaped variable passes.
Keep Secret values unread. Preserve all application checks. Keep the full
contract runtime below seven seconds.

Authority: Repository edits only. No commit, push, reconciliation, or live
mutation authority applies.

Git checkpoint: Use an exact inverse patch for the validator, test, and
Taskfile hunk.

Live preconditions: Not applicable. This experiment is repository-only.

Stop and rollback triggers: Restore only experiment hunks if discovery misses
a root, a valid escaped variable fails, output is empty, or a guard fails.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_flux_postbuild_contract
mise exec -- python3 scripts/validate-flux-postbuild-contract.py
mise exec -- task contracts:validate
```

On 2026-08-11, four focused tests passed. The validator reported two passing
roots. The full guard passed 47 applications, five validators, and 104 tests
in 4.965 seconds.

Result: Strict generated-ConfigMap preflight coverage improved from one of two
roots to two of two roots.

Decision: Keep.

Follow-up: This improves a driver, not the rolling M1 outcome. Historical Flux
conditions still cannot establish the 30-revision baseline.

### Experiment M1-E3

Experiment ID: M1-E3.

Metric contract version: 1.

Type: Repository preflight coverage experiment.

Hypothesis: Strict substitution across every postBuild application root catches
the known failure class outside generated ConfigMaps.

Single lever: Expand one validator from generated ConfigMaps to full postBuild
application renders.

Expected mechanism: The validator discovers `ks.yaml` files with
non-null mapping `spec.postBuild` values. It verifies each `spec.path` against
the sibling application root. It then renders and substitutes each root.

Baseline samples: Two of 37 postBuild roots had strict validation. Coverage was
5.405 percent. Ten of 47 application roots do not declare postBuild and remain
outside this failure-class denominator.

Target and tolerance: Validate 37 of 37 postBuild roots. Allow zero missed
roots, strict failures, empty renders, or false positives.

Guards: The fixed placeholder names are `SECRET_DOMAIN`,
`SECRET_DOMAIN_TWO`, `SECRET_DOMAIN_THREE`, and `TAILNET_SUFFIX`. Dummy values
use the reserved `.invalid` suffix. The validator does not infer names from
rendered tokens. An unescaped `${runtime_var}` must fail. An escaped
`$${runtime_var}` must pass. No Secret value can enter the command environment.
Discovery, rendering, and substitution use the same restricted environment.

Semantic limit: A runtime variable with one of the four approved names is
indistinguishable from an intended Flux substitution. Workload scripts must
escape these names explicitly. This validator proves strict substitution, not
the author intent of an approved token.

Runtime guard: Measure the full contract command externally. The seven-second
threshold is a keep or reject rule. It is not an internal validator deadline.

Authority: Repository validator, test, and documentation edits only. No
manifest, Secret, live cluster, commit, push, or reconciliation authority
applies.

Git checkpoint: Use an exact inverse patch for the validator, test, and
documentation hunks.

Live preconditions: Not applicable. This experiment is repository-only.

Stop and rollback triggers: Restore only experiment hunks if discovery omits a
postBuild root, an undeclared runtime escape passes, a valid escape fails, a
render is empty, or a guard fails.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_flux_postbuild_contract
mise exec -- python3 scripts/validate-flux-postbuild-contract.py
mise exec -- task contracts:validate
```

Result: Strict postBuild coverage increased from two of 37 roots to 37 of 37
roots. The first candidate was rejected because its 7.7-second aggregate guard
exceeded the seven-second limit. Review rejected the next candidate because it
assumed sibling paths, counted invalid postBuild values, and inherited an
unrestricted render environment. The replacement validates these boundaries.
It uses four bounded workers and keeps result order stable.
Fourteen focused tests passed. The validator reported 37 passing roots from 47
total application roots in 0.638 seconds. The aggregate guard passed 163 tests
in 5.399 seconds and completed in 6.164 seconds. Three final shell-time samples
were 6.45, 6.21, and 6.33 seconds. All remained below seven seconds.

Decision: Keep.

Follow-up: This improves a deterministic M1 driver. It does not establish the
rolling 30 accepted-revision outcome or replace later live Flux evidence.

### Experiment M1-E4

Experiment ID: M1-E4.

Metric contract version: 1.

Type: Synthetic accepted-revision lifecycle experiment.

Hypothesis: A pure schema can validate accepted-source evidence, terminal Flux
evidence, and rolling 30-revision arithmetic without a live collector.

Single lever: Add one M1-only lifecycle validator and aggregator.

Baseline samples: No trusted M1 terminal records exist. The rolling baseline
remains unestablished.

Target and tolerance: Validate synthetic zero-of-30 and one-of-30 escape
windows. Allow zero forged source events, target sets, or terminal transitions.

Authority: Repository code, tests, and documentation only. No collector,
ledger, live read, commit, push, or reconciliation authority applied.

Git checkpoint: Use an exact inverse patch for the three new M1 model files and
the experiment documentation.

Result: The candidate passed 16 synthetic tests after lifecycle corrections.
Independent review then proved a critical authority bypass. Thirty hand-built
terminal mappings could pass structural validation and produce an eligible
rate. A caller could also reduce the expected target set and provide matching
partial evidence. Structural checks cannot prove that the trusted source and
target resolver created those mappings.

Review also found ambiguous multi-target failure classification. The first
sorted failure selected the class without causal proof. Ready evidence did not
require the attempted revision to match the accepted revision.

Decision: Reject and roll back the three new model files.

Follow-up: Do not add another repository-only M1 lifecycle model. A valid model
needs a trusted observer boundary, an authoritative target resolver, and an
approved durable store. Those needs require separate authority and design.

## Metric 2: Critical-path revision convergence time

Name: Critical-path revision convergence time.

Role: Outcome.

Beneficiary: Cluster operators and users of shared platform services.

Critical scope: Flux root and controllers, Cilium, CoreDNS, External Secrets,
Envoy Gateway, Longhorn, SeaweedFS, Prometheus, and alert delivery. Exclude
learning workloads.

Numerator and denominator: Record elapsed time for each complete critical
revision. Record incomplete and stale critical revisions as separate counts.

Start event: Flux observes one accepted Anton revision.

Stop event: Every critical Kustomization reports Ready at that same revision.

Time window: One record per accepted critical revision. Review a rolling 30
revision window after the inventory exists.

Environment and workload: The Flux-managed Anton cluster.

Evidence source and query: Flux Git source revision and critical
Kustomization Ready conditions with observed revision identity.

Observer: `scripts/evaluate_revision_convergence.py` uses
`scripts/lib/revision_convergence.py`. It reads one Flux GitRepository and
all Flux Kustomizations. It does not modify the cluster. It verifies and binds
the Anton Kubernetes target before the first read.

Critical inventory: `flux-system/flux-system`, `flux-system/cluster-apps`,
`flux-system/flux-operator`, `flux-system/flux-instance`,
`kube-system/cilium`, `kube-system/coredns`,
`external-secrets/external-secrets`, `external-secrets/onepassword-store`,
`network/envoy-gateway`, `network/cloudflare-dns`,
`network/cloudflare-tunnel`, `network/k8s-gateway`,
`storage/longhorn-config`, `storage/longhorn`, `storage/seaweedfs`,
`storage/seaweedfs-config`, `observability/kube-prometheus-stack`, and
`observability/ntfy`.

Comparison rule: Compare the full source revision. Require the resource
generation, status observed generation, and Ready observed generation to be
current. A Ready resource at an older revision is stale, not converged.

Aggregation and sample count: Record p50, p95, maximum, and incomplete count
after at least 30 complete revision records.

Baseline: One failed and incomplete read-only observation is recorded below.
No completed convergence-time baseline exists.

Direction: Lower is better. Incomplete convergence is a failure, not a slow
sample.

Target: Set after the baseline. Keep the target in the first baseline record.

Noise tolerance: Set after the baseline. Use no tolerance for incomplete
convergence.

Independent guards: Do not replace a failed revision with an older Ready
revision. Keep the critical inventory explicit. Preserve Flux dependency rules.

Editable levers: Preflight validation, dependency edges, readiness signals,
and documented controller configuration.

External factors: Git source latency, controller load, image pulls, cluster
health, and external dependency availability.

Authority required: Read-only Flux access for measurement. Separate approval
for repository edits, Flux reconciliation, or live changes.

Checkpoint and rollback: Use an exact inverse patch for one repository
experiment. Revert only experiment-owned hunks.

Stop condition: Stop if revision identity is ambiguous, a critical resource
is not inventoried, the measure fails, or an action needs new authority.

Result record: Record revision, start and stop times, each resource identity,
missing resources, aggregate values, guards, decision, and follow-up.

### Read-only baseline observation

Source revision: `refs/heads/main@sha1:50f056942b78cfaa16052ff781630cfcde4d793a`.

Observation time: 2026-08-10T23:40:43Z.

Artifact last update: 2026-08-10T21:34:40Z.

Current sample age: at least 2 hours, 6 minutes, and 3 seconds.

Current critical resources reported the current revision and Ready state except
`storage/seaweedfs-config`. That Kustomization failed and last applied
`fc3f7940`. The earliest cause was strict substitution of `bucket`.

Observer result: The live source revision was
`refs/heads/main@sha1:50f056942b78cfaa16052ff781630cfcde4d793a`. The 18-item
inventory reported 17 `current_ready` resources and one `current_failed` resource:
`storage/seaweedfs-config`. `incomplete_count` was 1.

Decision: Record this sample as failed and incomplete. Do not use it as a
completed convergence-time sample.

Limitation: Live object status cannot reconstruct historical p50 or p95.
Persist event history before calculating those values.

`age_seconds` is Git artifact age. It is not convergence duration.

Validation commands:

```sh
mise exec -- python3 -m unittest scripts.tests.test_revision_convergence
mise exec -- python3 scripts/evaluate_revision_convergence.py
```

The observer is a measurement prerequisite. It is not an M2 metric win.

### Experiment M2-E1

Experiment ID: M2-E1.

Metric contract version: 1.

Type: Synthetic observer coverage experiment.

Authority: Repository-only fixture and test work. No live authority applies.

Hypothesis: The exact fixed fixture scope prevents untested critical-inventory
omissions.

Single lever: Expand the revision-convergence fixture.

Git checkpoint: Use an exact inverse patch for fixture and test hunks. Restore
only experiment-owned hunks.

Live preconditions: Not applicable. The fixture is synthetic.

Expected mechanism: The fixed fixture covers every inventory item and rejects
omitted, duplicate, or reordered scope.

Baseline samples: Five of 18 inventory items had fixture coverage. This was
27.78 percent coverage.

Target and tolerance: Cover 18 of 18 items. Keep zero omissions, duplicates,
and order changes.

Result: Live revision, start, and stop are not applicable because the fixture
is synthetic. The fixture has all 18 resource identities. It includes an
intentional missing `kube-system/cilium` case. Aggregate coverage was 18 of
18, or 100 percent. There were zero omissions, duplicates, and order changes.

Guards: Run the focused M2 test suite and the aggregate contract guard.

Stop and rollback triggers: Stop and restore the exact inverse patch if an
inventory item is omitted, duplicated, or reordered, or if a guard fails.

Commands and evidence times: On 2026-08-10, the focused M2 suite passed 12
tests. The aggregate guard passed 47 applications, four validators, and 93
tests in 4.868 seconds.

```sh
mise exec -- python3 -m unittest scripts.tests.test_revision_convergence
mise exec -- task contracts:validate
```

Decision: Keep.

Follow-up: The fixture is synthetic. This result improves observer prerequisite
coverage. It does not measure or improve live convergence time.

### Experiment M2-E2

Experiment ID: M2-E2.

Metric contract version: 1.

Type: Synthetic record lifecycle and aggregation experiment.

Hypothesis: A versioned exact-revision lifecycle can retain incomplete records
and calculate the rolling aggregate only after 30 complete records exist.

Single lever: Add one pure revision-record transition and aggregation seam.

Expected mechanism: An incomplete first observation creates an immutable
revision start. A later observation from `GitRepository flux-system/flux-system`
can complete it only when all 18 resources are `current_ready`. Exactly 30
distinct source events form the aggregate window. Each record retains its
initial scope, classifications, and incomplete count.

Baseline samples: No versioned lifecycle or rolling aggregation existed. The
retained live observation was one incomplete snapshot.

Target and tolerance: Admit a synthetic 30-record complete window with p50 15
seconds, p95 29 seconds, maximum 30 seconds, and zero incomplete records.
Allow zero shortened or duplicate revisions, source identity or scope changes,
tied source events, failed evidence in complete records, reversed observations,
changed initial evidence, or durations that disagree with event times.

Guards: Pin `GitRepository flux-system/flux-system`. Keep full source revisions.
Keep only fixed classifications and incomplete records outside latency quantiles.
Use nearest-rank quantiles over the fixed 30-record window. Label duration as a
first-observed completion upper bound. Require a complete record to advance
beyond its retained first observation. Do not add a writer, poller, or cluster
mutation.

Authority: Repository library, test, and documentation edits only. No live
authority applies.

Git checkpoint: Use an exact inverse patch for the M2 library, tests, and
documentation hunks.

Live preconditions: Not applicable. The corpus is synthetic. The retained live
snapshot is used only to prove an incomplete record.

Stop and rollback triggers: Restore only experiment hunks if an incomplete
record enters a quantile, an identity mismatch passes, percentile arithmetic
changes, or a guard fails.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_revision_convergence
mise exec -- task contracts:validate
```

Result: The synthetic 30-record window was eligible. Nearest-rank p50 was 15
seconds, p95 was 29 seconds, maximum was 30 seconds, and incomplete count was
zero. A window with 29 complete records and one incomplete record was
ineligible and emitted no latency quantiles. The seam rejected direct complete
starts, source changes, tied source events, unsupported classifications, and a
window-size override. It retained immutable initial incomplete evidence and
rejected a forged complete start. The retained live snapshot created one
incomplete record with no duration. On 2026-08-11, the focused M2 suite passed
28 tests. The final contract guard passed 125 tests in 5.024 seconds.

Decision: Keep.

Follow-up: This enables prospective records. It does not create missing history
or a live M2 baseline. A later collector needs an approved durable path and a
fixed polling interval.

### Experiment M2-E3

Experiment ID: M2-E3.

Metric contract version: 1.

Type: Synthetic lifecycle persistence experiment.

Hypothesis: One atomic ledger can retain prospective revision records without
lost updates, false history, or target-data leaks.

Single lever: Add one target-bound collector and one atomic JSON ledger.

Expected mechanism: The collector validates the ledger before the live read.
It validates the complete proposed state before one atomic replacement. A
stable file lock serializes concurrent collectors.

Baseline samples: No collector or ledger existed. Zero of 25 required
persistence scenarios had executable coverage.

Target and tolerance: Pass 25 of 25 scenarios. Allow zero existing JSON ledger
payload changes after validation rejection or pre-replacement failure. Allow
zero writes during dry-run or observation failure. A first persistence attempt
can create the stable private lock before it validates the transition.

Guards: Require an explicit absolute path. Require parent directory mode `0700`.
Require mode `0600` for the ledger and lock. Reject symbolic ledger files,
duplicate revisions, tied source events, corrupt state, stale observations, and
completed-record changes. Keep the fixed 18-resource scope. Keep target
preflight before both cluster reads. Do not store context, endpoint, address,
condition message, Secret data, or raw command errors.

Time guard: The collector always uses its local observation time. It rejects an
operator-supplied observation time. Whole-second durations round up to preserve
the upper-bound claim.

Scope guard: The observer command rejects source and critical-scope overrides.
The collector uses the fixed GitRepository and the fixed 18-resource inventory.

Durability guard: A directory sync failure after replacement is a separate
uncertain-durability error. The new complete ledger is already installed. An
operator must read and validate it before retrying.

Record semantics: Version 2 admits `incomplete_first` and `complete_first`.
Both record a first-observed completion upper bound. A complete-first record
stops at its first observation. It does not claim an exact convergence time.
Canonical timestamps keep fractional seconds.

Authority: Repository code, tests, and documentation only. No collector was
run against Anton. No durable ledger path was selected or created.

Git checkpoint: Use an exact inverse patch for the collector, ledger, version 2
lifecycle, tests, and documentation hunks.

Live preconditions: A real run needs separate read-only Anton authority and an
approved absolute durable path. A recurring run also needs an approved fixed
schedule and owner.

Stop and rollback triggers: Restore only experiment hunks if validation changes
the JSON payload, a concurrent update is lost, a private value appears, or a
guard fails. Do not assume that a post-replacement sync error kept old bytes.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest \
  scripts.tests.test_revision_convergence \
  scripts.tests.test_revision_convergence_collector
mise exec -- task contracts:validate
```

Operator path after separate read and local-write authority:

```sh
mise exec -- python3 scripts/collect_revision_convergence.py \
  --records-path /absolute/private/path/revision-convergence.json \
  --dry-run
mise exec -- python3 scripts/collect_revision_convergence.py \
  --records-path /absolute/private/path/revision-convergence.json
```

Result: The first candidate was rejected. Its safe path traversal did not
support the macOS `/var` alias. Eight scenarios errored and three failed. The
replacement canonicalizes the existing parent, checks its file identity, and
keeps no-follow access after that check.

The replacement passed 25 of 25 persistence scenarios. It serialized distinct
concurrent revisions. It rejected a concurrent duplicate without adding a
second record. It preserved bytes after stale, completed, corrupt, duplicate,
tied, and pre-replacement failure cases. A post-replacement directory sync
failure reported its installed but unconfirmed state. Dry-run and failed
observations wrote no files. The full 53-test M2 suite passed.
The aggregate contract guard passed 153 tests in 5.395 seconds.

Decision: Keep.

Follow-up: This is a measurement prerequisite. It does not create a live
record or baseline. Select the durable path, schedule, and owner before use.

Target-bound read command:

```sh
mise exec -- python3 scripts/evaluate_revision_convergence.py
```

## Metric 3: Critical service recovery time

Name: Critical service recovery time.

Role: Outcome.

Beneficiary: Cluster operators and users of critical services.

Critical scope: Node and etcd, CNI and DNS, storage attachment, Flux and
configuration, Secret delivery, gateway, and external path failures.

Numerator and denominator: The numerator is elapsed recovery time per
scenario. The denominator is one classified loss event. Keep scenario
families separate.

Start event: First authoritative evidence of critical service loss.

Stop event: Stable dependency health and user-visible service recovery.

Time window: One record per classified incident or approved drill.

Environment and workload: The Anton cluster and the named critical service.

Evidence source and query: Alert, Flux, Kubernetes, Talos, log, and
user-visible probe evidence. Record source identity and timestamps.

Aggregation and sample count: Record detection, diagnosis, mitigation, and
restoration times. Do not aggregate scenario families before ten records each.

Baseline: One read-only tabletop sample is recorded below. It is not a
performance baseline or target.

Direction: Lower is better.

Target: Set after scenario-specific baselines exist.

Noise tolerance: Set after scenario-specific baselines exist.

Independent guards: Keep detection, diagnosis, mitigation, and restoration
times separate. Confirm stable dependencies and user-visible recovery.

Editable levers: Runbooks, alert routing, observability queries, dependency
readiness, and approved recovery procedures.

External factors: Incident severity, quorum state, provider state, operator
availability, and data recovery needs.

Authority required: Read-only inspection for tabletop work. Separate approval
for drills, reboots, pod deletion, storage actions, reconciliation, or traffic.

Checkpoint and rollback: Tabletop work has no rollback. A live drill requires
an approved recovery plan, explicit rollback, and data and quorum gates.

Stop condition: Stop a live proposal before it can reduce quorum, risk data,
or mutate state without approval. Stop if the start or stop event is unclear.

Result record: Record scenario, event times, evidence sources, dependency
state, user-visible proof, decision, and recurrence window.

### Experiment M3-E1

Experiment ID: M3-E1.

Metric contract version: 1.

Type: Read-only tabletop exercise.

Hypothesis: The corrected incident sources can provide six distinct recovery
phase fields without an unmarked chronology conflict.

Single lever: Classify one corrected incident source set.

Authority: Read-only access to committed incident, postmortem, and evidence
files. The exercise used no repository edit or live cluster action.

Guards: Keep the sequential chronology. Keep etcd retention separate from an
etcd-loss scenario. Keep storage recovery separate from public-path recovery.

Git checkpoint: Not applicable. No system changed.

Live preconditions: Not applicable. This was a read-only tabletop.

Stop and rollback triggers: Stop if a phase lacks a source, a chronology
conflict is unmarked, or the scenario classification becomes ambiguous. No
rollback applies.

Expected mechanism: The corrected sources separate detection, diagnosis,
mitigation, public-path recovery, and incomplete storage recovery.

Scenario: Sequential node reboot. The event retained etcd quorum. It was not
an etcd-loss scenario.

Baseline samples: `context/incidents/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`,
`context/postmortems/2026-05-05-k8s-1-k8s-3-dual-silent-reboot.md`, and
`context/notes/k8s-2-instability/evidence-2026-05-05-dual-silent-reboot.md`.

Corrected chronology: k8s-3 rebooted at 19:07:13Z. K8s-1 silently rebooted
at about 19:33Z. K8s-2 retained etcd membership. The nodes did not reboot
simultaneously.

Service-loss start: About 19:33Z.

Detection: 21 minutes.

Diagnosis: At most 6 minutes.

Mitigation start: 28 minutes.

Public-site B recovery: 29 minutes.

Public-site A recovery: 40 minutes.

Both public paths recovery: 40 minutes.

Stable named public-path scope: 62 minutes at 20:35Z.

Storage status: Storage was not fully recovered at 20:35Z.

Target and tolerance: Six of six phase fields have a source. Allow zero
unmarked chronology conflicts. Use plus or minus 1 minute for minute-stamped
events.

Result: Achieved. Six of six phase fields have a source. No unmarked
chronology conflict remains.

Commands and evidence times: On 2026-08-10, use `mise exec -- qmd get` to
retrieve the cited source. The incident, postmortem, and evidence note support
the six phase fields and corrected chronology. No live command was used.

Decision: Keep.

Follow-up: This is one classified sample. Do not aggregate it with other
scenario families. Wait for ten records in this family before aggregation. It
is not a performance target or a performance win.

### Experiment M3-E2

Experiment ID: M3-E2.

Metric contract version: 1.

Type: Read-only tabletop exercise.

Hypothesis: The closed postmortem can supply six sourced recovery phases
without a chronology conflict.

Single lever: Classify one Flux control-plane source.

Authority: Read-only source review and current documentation authority only.
No live authority applies.

Guards: Keep this scenario separate from other families. Require Pod Ready and
HelmRelease True. Retain both rejected hypotheses. Do not infer public impact.

Git checkpoint: Use a documentation-only exact inverse patch. Do not change
the source postmortem.

Live preconditions: Not applicable. This was a read-only tabletop.

Stop and rollback triggers: Stop if a phase boundary is missing or ambiguous.
Restore only documentation-owned hunks.

Expected mechanism: The closed postmortem supplies distinct recovery phases
without inferring public-user impact.

Scenario: Flux control-plane service failure. This was not a public-user
outage.

Baseline samples: `context/postmortems/2026-05-04-flux-operator-networkpolicy-blocked-probes.md`.

Onset: About 2026-05-01 05:40 UTC. This time is approximate and unbounded.

Detection: 2026-05-04 19:30 UTC.

Diagnosis complete: 20:08 UTC.

Effectful mitigation: 20:10:17 UTC.

Pod Ready: 20:10:28 UTC.

HelmRelease stable True: 20:13:51 UTC.

Duration: The nominal onset-to-stable duration was 86 hours, 33 minutes, and
51 seconds. It is not exact. The reliable detection-to-stable duration was
43 minutes and 51 seconds, plus or minus 1 minute.

Rejected hypotheses: A flux-operator chart regression was rejected. A one
second probe timeout was rejected.

Chronology: The 20:09 desired-state commit disabled the chart NetworkPolicy.
It was not the effectful mitigation. The direct NetworkPolicy deletion at
20:10:17 broke the Helm-controller retry loop.

Target and tolerance: Six of six phase fields have a source. Allow zero
unmarked chronology conflicts. Use plus or minus 1 minute for minute-stamped
fields. Do not bound the approximate onset.

Result: Achieved. Six of six phase fields have a source. No unmarked
chronology conflict remains. User-visible proof is not applicable because this
was not a public-user outage. Service proof was Pod Ready at 20:10:28 and
HelmRelease True at 20:13:51.

Commands and evidence times: On 2026-08-10, use `mise exec -- qmd get` to
retrieve the closed postmortem. It provides the phase evidence. No live command
was used.

Decision: Keep.

Follow-up: This is a second scenario-family sample. It is not a performance
target or a Phase 4 causal improvement. Wait for ten records in this scenario
family before aggregation.

### Experiment M3-E3

Experiment ID: M3-E3.

Metric contract version: 1.

Type: Read-only sample eligibility tabletop.

Hypothesis: The fixed start and stop gates reject a thermal incident that did
not cause critical service loss.

Single lever: Classify the 2026-05-06 k8s-2 thermal incident against M3 entry
and exit requirements.

Expected mechanism: The incident cannot enter the recovery corpus without
authoritative service-loss and user-visible-recovery evidence.

Baseline samples: One unused candidate record. It has zero critical
service-loss proofs and zero user-visible-recovery proofs.

Target and tolerance: Reject one of one ineligible candidates. Allow zero
inferred outages, zero inferred recoveries, and zero unmarked timestamp gaps.

Guards: Keep thermal risk separate from service recovery. Treat "cluster
serving" as no-outage evidence. Preserve the source timestamps.

Authority: Read-only QMD and source review. No live authority applies.

Git checkpoint: Use a documentation-only exact inverse patch.

Live preconditions: Not applicable.

Stop and rollback triggers: Stop if either M3 boundary must be inferred.
Restore only documentation-owned hunks if the classification changes.

Commands and evidence times: On 2026-08-11, QMD retrieved
`context/incidents/2026-05-06-k8s-2-thermal-throttle.md` and
`context/postmortems/2026-05-06-k8s-2-thermal-throttle.md`.

Result: The candidate is not an M3 sample. The cluster remained available,
and the record has no user-visible recovery event.

Decision: Keep the eligibility result. Reject the candidate sample.

Follow-up: The next M3 outcome sample needs a new closed incident or a
separately approved drill.

## Metric 4: Shared platform restart, OOM, and saturation rates

Name: Shared platform restart, OOM, and saturation rates.

Role: Outcome family.

Beneficiary: Cluster operators and all shared platform users.

Critical scope: Flux controllers, Cilium, Multus, Whereabouts, storage VXLAN,
CoreDNS, gateway controllers, External Secrets, Longhorn, SeaweedFS,
Prometheus, Alertmanager, and log collection.

Numerator and denominator: Record restarts per platform container-hour and
OOM events per platform container-hour. Record minutes above memory headroom,
CPU throttle, storage capacity, API latency, and API error thresholds.

Start event: A platform container starts, an OOM event occurs, or a threshold
breach begins.

Stop event: The container-hour ends or the threshold breach ends.

Time window: Rolling 15 days by component and node.

Environment and workload: The shared Anton platform.

Evidence source and query: Prometheus series, alert rules, workload status,
and node evidence. Confirm no-data behavior before use.

Observer: `scripts/evaluate_platform_stability.py` uses fixed 15-day
Prometheus service-proxy queries. It uses a 60-second total monotonic budget
and a 30-second cap for each query. It reports separate measures. It does not
modify the cluster. It verifies and binds the Anton Kubernetes target before
the first query.

The `budget_exhausted` state differs from `query_error`. It means the
60-second total deadline prevented later calls.

Aggregation and sample count: Record rates and breach minutes by component
and node. Do not create a composite score.

Baseline: A read-only 15-day observation is recorded below. It is incomplete
where the listed gaps apply.

Direction: Lower is better, subject to actual headroom and service health.

Target: Set after approved thresholds and a complete baseline. Do not use
commitment ratio as a target. Memory thresholds are deployed rules. Storage
and API thresholds are not approved.

Noise tolerance: Set after approved thresholds and a complete baseline by
measure and component.

Independent guards: Require headroom, restart, OOM, latency, or recovery
evidence. Do not lower requests only to improve a commitment ratio.

Editable levers: Resource settings, placement, controller configuration,
alerts, and approved workload changes.

External factors: Node events, workload demand, image changes, cluster
maintenance, and incomplete telemetry.

Authority required: Read-only Prometheus and Kubernetes access for baselines.
Separate approval for repository edits, workload changes, or live actions.

Checkpoint and rollback: Use one exact inverse patch per repository change.
Live changes require an approved rollback and recurrence window.

Stop condition: Stop if data is missing, a threshold lacks a tested meaning,
the proposed change reduces safety, or new authority is required.

Result record: Record component, node, denominator, measure values, query,
evidence time, guards, decision, and recurrence window.

### Read-only baseline observation

Observation method: Prometheus service proxy.

Prometheus version: 3.11.2.

Retention: 15 days.

Observation verified again: 2026-08-10T23:44:45Z.

Platform scope: `flux-system|kube-system|network|external-secrets|storage|observability|envoy-gateway-system`.

Restart rate: 24.107 extrapolated restart increases across 50,994 hourly
running-container samples. This equals 0.4727 restarts per 1,000
container-hours.

OOM events: `no_data`. Total: `null`.

Cilium memory above 2,048 MiB: 0 minutes on all nodes. Peak values were
223.79 MiB, 304.92 MiB, and 219.64 MiB.

Multus memory above 400 MiB: 0 minutes.

Whereabouts memory above 400 MiB: 0 minutes.

Storage VXLAN memory above 96 MiB: 0 minutes.

Package CPU throttle: 0.

PVC capacity peaks: Talos log sink 52.84 percent, Prometheus 33.67 percent,
and the largest SeaweedFS PVC 6.26 percent.

API errors: 44.001 extrapolated 5xx events. The peak five-minute ratio was
0.2467 percent. The current ratio was 0.

Earlier fixed observation API p99: 45.35 milliseconds.

Gaps: Storage and API thresholds lack approval. Historical API p99 returned
`query_error`. Loki and OTel cover only about eight days. Historical restart
node attribution is incomplete. Full scrape continuity is unknown. Alert
delivery is not proved. Coverage is partial. Do not treat this observation as
a complete platform baseline.

Validation commands:

```sh
mise exec -- python3 -m unittest scripts.tests.test_platform_stability_evaluator
mise exec -- python3 scripts/evaluate_platform_stability.py
```

The observer is a measurement prerequisite. It is not an M4 metric win.

### Experiment M4-E1

Experiment ID: M4-E1.

Metric contract version: 1.

Type: Historical API latency query coverage experiment.

Authority: Repository evaluator, fixture, and test work, plus read-only
Prometheus service-proxy access. No live mutation authority applies.

Hypothesis: A one-hour historical subquery resolution avoids Prometheus sample
memory failure while keeping five-minute rates.

Single lever: Change the historical subquery resolution from `[15d:5m]` to
`[15d:1h]`. Keep the five-minute rate expression.

Expected mechanism: The hourly subquery stays within sample memory and returns
one finite historical latency scalar.

Git checkpoint: Use an exact inverse patch for the three M4 files: the
evaluator, fixture, and test. Restore only experiment-owned hunks.

Live preconditions: The Prometheus service proxy must be available for one
read-only fixed-time query.

Baseline samples: One catalog query returned `query_error`. Coverage had three
reasons. The `[15d:5m]` subquery exceeded Prometheus sample memory.

Target and tolerance: Zero query errors, two coverage reasons, and one finite
0.983800-second scalar. Apply plus or minus 0.000001 seconds only to the
scalar.

Result: The component was the API server. Node attribution was aggregate and
not applicable. The denominator was one fixed 15-day hourly-sampled historical
query. Evidence time was 2026-08-10T23:44:45Z. The fixed-time live query
returned one finite 0.983800-second scalar. The query-error count was 0.
Coverage had two reasons.

Guards: Preserve no-data semantics and separate measures. Keep API and storage
thresholds unapproved. Keep other outputs unchanged. Keep the 60-second total
monotonic budget and 30-second per-query cap.

Stop and rollback triggers: Stop and restore the exact inverse patch if a
query error returns, no-data semantics change, a measure merges, a threshold
changes, an unrelated output changes, or a query budget is exceeded.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_platform_stability_evaluator
mise exec -- task contracts:validate
```

At 2026-08-10T23:44:45Z, the fixed live evaluator completed in 30.59 seconds.
Eleven focused M4 tests passed. The full guard passed 94 tests in 4.816 seconds.

Final historical PromQL:

```promql
max_over_time((
  max(histogram_quantile(0.99,
    sum by (le,verb) (
      rate(apiserver_request_duration_seconds_bucket{verb!="WATCH"}[5m])
    )
  ))
)[15d:1h])
```

Limit: Prometheus can apply monotonicity correction during histogram quantile
calculation. Keep that correction information with the evidence. Hourly
sampling can miss between-hour peaks. This result is not a true five-minute
resolution maximum.

Correction: At the fixed observation, the current raw maximum p99 was 27.1
seconds because CONNECT was included. This differs from the earlier 45.35
millisecond observation. Do not use either value as a performance threshold.

Status: API and storage `threshold_state` remain unapproved. Their
`breach_minutes` values remain `null`. OOM remains `no_data` with total
`null`.

Decision: Keep.

Follow-up: The recurrence window is a fixed 15 days. Re-run the same observer
after a later approved change. Retain the query correction and hourly-fidelity
limits. This result improves observer coverage. It is not an M4 metric win.

### Experiment M4-E2

Experiment ID: M4-E2.

Metric contract version: 1.

Type: Historical platform outcome experiment.

Hypothesis: Relaxing k8s-2 PM-QoS from 0 microseconds to 1 microsecond restores
shallow C1 idle and removes package and core throttling without reopening deep
idle states.

Single lever: Change only k8s-2 PM-QoS from 0 microseconds to 1 microsecond.

Expected mechanism: C1 residency reduces package heat while C2 and C3 remain
blocked.

Baseline samples: The first nonzero throttle bucket was at 12:27 UTC on
2026-05-06. The pre-mitigation package rate was about four to five events per
second. Eight-hour package and core increases were about 13,000 on k8s-2 and
zero on peer nodes.

Target and tolerance: Both five-minute throttle rates must reach zero. k8s-2
must remain Ready. C1 must increment while C2 and C3 remain flat. Allow zero
node reboots and zero deep-idle regressions.

Guards: Check pod configuration, cpuidle counters, both throttle rates, node
readiness, and a ten-minute watch. A planned 24-hour recurrence watch must use
consistent timestamps before it supports a durability decision.

Authority: This record describes the historical authorized canary. It grants
no current live authority.

Git checkpoint: Commit `f7b8cafc` was the durable GitOps checkpoint.

Live preconditions: The canary was limited to k8s-2. Peer nodes stayed at
0 microseconds as negative controls.

Stop and rollback triggers: Restore 0 microseconds on k8s-2 if deep idle
returns, readiness fails, a reboot occurs, or throttle rates do not fall.

Commands and evidence times: QMD retrieved the incident, postmortem, and plan
0013 on 2026-08-11. The source timeline records live application at 14:08,
commit at 14:10, Flux convergence at 14:11, zero throttle rates at 14:13, and
a clean ten-minute watch at 14:20.

Result: The immediate target passed. Package and core rates reached zero,
k8s-2 stayed Ready, and the deep-idle guard passed. Plan 0013 later describes
a second episode and a 21-hour delay, but its stated UTC interval precedes the
canary. The recurrence chronology is unresolved.

Decision: Inconclusive. The immediate improvement passed, but durability is
not proved.

Follow-up: Later work changed other variables and promoted 1 microsecond to all
nodes. Do not attribute later outcomes to this single-node canary.

### Experiment M4-E3

Experiment ID: M4-E3.

Metric contract version: 1.

Type: Required-source continuity coverage experiment.

Hypothesis: One fixed continuity query can prove that each required M4 source
had a real, healthy sample in every evaluated one-minute interval.

Single lever: Add one `scrape_continuity` query and fixed target-count map to
the M4 evaluator.

Expected mechanism: Each required job returns 1 only when every expected
target has at least one real sample, and every sample is up, in each evaluated
one-minute interval.

Baseline samples: Coverage had two reasons. Scrape continuity was unproved.
The evaluator encoded zero of four required source checks.

Target and tolerance: Require four of four jobs with value exactly 1. Reduce
coverage reasons from two to one. Allow zero missing, duplicate, nonfinite, or
non-1 results.

Guards: Keep OOM as `no_data`. Keep API and storage thresholds unapproved.
Preserve separate measures, the service proxy, and the 30-second and 60-second
budgets.

Authority: Repository edits and one read-only fixed-time Prometheus query. No
live mutation authority applies.

Git checkpoint: Use an exact inverse patch for the evaluator, fixture, test,
and documentation hunks.

Live preconditions: G1-E1 must verify and bind the Anton context and endpoint.
The Prometheus service proxy must be available.

Stop and rollback triggers: Restore only experiment hunks on a query error,
budget exhaustion, target-count mismatch, unrelated output change, or guard
failure.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_platform_stability_evaluator
mise exec -- python3 scripts/evaluate_platform_stability.py --observed-at 2026-08-11T00:51:10Z
mise exec -- task contracts:validate
```

Result: All four required jobs returned 1. Expected target counts were API
server 3, kube-state-metrics 1, kubelet 9, and node-exporter 3. Coverage reasons
decreased from two to one. OOM remained `no_data`. API and storage thresholds
remained unapproved. The sanitized fixed-time output is retained in
`context/notes/cluster-metric-evidence/2026-08-11T005110Z-m4.json`. Sixteen
focused tests passed. The final full guard passed 111 tests in 5.054 seconds.

Decision: Keep.

Follow-up: The query proves availability in evaluated one-minute intervals.
It cannot exclude a gap between samples inside one interval. Historical
restart node attribution remains incomplete.

### Experiment M4-E4

Experiment ID: M4-E4.

Metric contract version: 1.

Type: Historical restart node attribution coverage experiment.

Hypothesis: A time-local UID join attributes every observed restart increment
to one node without changing the aggregate restart rate.

Single lever: Add one one-minute restart attribution estimator.

Expected mechanism: Each one-minute restart increase joins the matching
`kube_pod_info` sample before the 15-day sum.

Baseline samples: Observer instrumentation had one reason. Historical restart
node attribution was unavailable.

Target and tolerance: Reduce observer instrumentation reasons from one to
zero. Require the absolute raw-to-node residual to be at most 0.000001 restart
increments.

Guards: Keep the original 15-day restart rate separate. Require a positive
raw total, finite node totals, node labels, and conservation. Preserve OOM as
`no_data`. Keep API and storage thresholds unapproved.

Authority: Repository edits and fixed-time read-only Prometheus queries. No
live mutation authority applies.

Git checkpoint: Use an exact inverse patch for the evaluator, fixture, test,
evidence, and documentation hunks.

Live preconditions: G1-E1 must verify and bind the Anton target. The
Prometheus service proxy must be available.

Stop and rollback triggers: Restore only M4-E4 hunks on a query error, budget
exhaustion, missing node label, residual breach, unrelated output change, or
guard failure.

Commands and evidence times:

```sh
mise exec -- python3 -m unittest scripts.tests.test_platform_stability_evaluator
mise exec -- python3 scripts/evaluate_platform_stability.py \
  --observed-at 2026-08-11T01:39:27Z
mise exec -- task contracts:validate
```

Result: The raw one-minute estimator was 17.130266666666667 restart increments.
The three node totals summed to 17.130266666666668. The absolute residual was
0.000000000000001. Instrumentation reasons changed from one to zero. The fixed-time result is retained
in `context/notes/cluster-metric-evidence/2026-08-11T013927Z-m4-restart-attribution.json`.

The original 15-day restart rate remained separate. Overall M4 coverage stayed
partial. OOM remained `no_data`. API and storage thresholds remained
unapproved. Nineteen focused tests passed. The final contract guard passed 128
tests in 5.195 seconds.

Decision: Keep.

Follow-up: This completes restart attribution coverage only. It does not make
OOM absence authoritative or approve storage and API thresholds.

Primary PromQL queries:

```promql
1000 *
sum(increase(kube_pod_container_status_restarts_total{
  namespace=~"flux-system|kube-system|network|external-secrets|storage|observability|envoy-gateway-system",
  container!=""
}[15d]))
/
clamp_min(sum(sum_over_time(kube_pod_container_status_running{
  namespace=~"flux-system|kube-system|network|external-secrets|storage|observability|envoy-gateway-system",
  container!=""
}[15d:1h])), 1)
```

```promql
sum by (node) (
  sum_over_time((
    container_memory_working_set_bytes{
      namespace="kube-system",container="cilium-agent"
    } > bool 2048 * 1024 * 1024
  )[15d:1m])
)
```

```promql
sum by (nodename) (
  sum_over_time((
    rate(node_cpu_package_throttles_total[1m]) > bool 0
  )[15d:1m])
  * on(instance) group_left(nodename) node_uname_info
)
```

Each true one-minute sample counts as one breach minute.

```promql
topk(20,
  max by (namespace,persistentvolumeclaim) (
    max_over_time((
      kubelet_volume_stats_used_bytes{
        namespace=~"flux-system|kube-system|network|external-secrets|storage|observability|envoy-gateway-system"
      }
      / kubelet_volume_stats_capacity_bytes{
        namespace=~"flux-system|kube-system|network|external-secrets|storage|observability|envoy-gateway-system"
      }
      * 100
    )[15d:1h])
  )
)
```

```promql
max_over_time(((sum(rate(apiserver_request_total{code=~"5.."}[5m])) / sum(rate(apiserver_request_total[5m]))) and (sum(rate(apiserver_request_total[5m])) > 0))[15d:5m])
```

Use the true positive request-rate denominator. Zero traffic returns `no_data`.
