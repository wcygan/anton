# Helm Remediation Deadlocks

Use this reference when a HelmRelease reports timeout, exhausted retries,
cleanup, rollback, hook failure, or an immutable Job error.

Read `docs/docs/runbooks/flux-helm-remediation.md` for the evidence matrix and
human handoff. This reference defines the agent completion criteria.

## Diagnose before remediation

1. Identify the Git revision, HelmRelease generation, Helm release name,
   storage namespace, and release revision.
2. Read the HelmRelease install and upgrade remediation policy.
3. Collect conditions, events, and bounded helm-controller logs.
4. List the exact Deployments, Jobs, hooks, and RBAC resources involved.
5. Build one action timeline from first failure through cleanup or rollback.
6. Classify the earliest supported failure.

Keep chart failure, cleanup effects, rollback effects, and workload symptoms
separate. A missing resource after cleanup is not always the first cause.

## Known classifications

- A post-install migration hook can wait behind workloads that need migration.
- Failed-upgrade cleanup can remove RBAC needed by the next controller attempt.
- Helm can fail when an upgrade tries to patch an immutable Job template.
- A timeout can start rollback before a slow controller reaches readiness.
- Reconcile retries can repeat the same deterministic release failure.

Treat each item as a hypothesis until current evidence supports it.

## Airflow precedent

Anton's Airflow migration Job uses `migrateDatabaseJob.useHelmHooks: false`.
Flux then owns a normal Job before dependent workloads become ready.

The Airflow foundation contract rejects `useHelmHooks: true`. This is a
project-specific repair, not a default for every chart.

## Mutation boundary

Do not delete a Deployment, Job, Helm release, or HelmRelease during diagnosis.
Do not force reconcile to collect evidence.

For an approved reset, state:

- Exact owner, namespace, and object.
- Why the object is stateless or recoverable.
- Predicted controller transition.
- One-action limit and timeout.
- Rollback trigger and operation.
- Readiness, event, and recurrence checks.

## Completion criteria

Stop when the first failing release layer is supported by current evidence.
Return the smallest owner-side correction or one bounded approval handoff.

Do not claim an immutable Job failure without the exact controller error and
the old and new Job template identities.
