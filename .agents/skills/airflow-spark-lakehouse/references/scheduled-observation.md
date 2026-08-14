# Scheduled Observation

Use this reference after an approved schedule enablement. It defines the
Ticket 11 observation gate. It does not authorize a schedule, retry, or
reconcile.

## Start record

Record the Git revision, Flux revision, deployed Airflow image digest, DAG
schedule, enablement time, and next expected run time. A disabled schedule has
`schedule=None`; `is_paused=False` can still permit a manual run.

Prove the deployed DAG matches the recorded digest before the first scheduled
run. Do not use a UI pause value as schedule proof.

## Watch contract

Use `monitor-until` with this authority and terminal condition:

```text
State source: Airflow Workflow Run history for airflow_spark_lakehouse
Success: 24 consecutive scheduled runs complete across 24 hours
Failure: an unexplained failure, a missed run, or conflicting Lease holder
Timeout: 26 hours from schedule enablement
Poll: every 10 minutes
```

For each scheduled run, retain its DAG, run ID, task ID, try number, exact
SparkApplication, Lease holder, terminal state history, and Trino result.
Compare new Iceberg snapshots with the prior run. Check Loki and History Server
when the run fails or its evidence conflicts.

Reset the window after an unexplained failure. Stop on the first failure and
report the earliest failing layer. Do not claim this gate passed before its
24-hour interval ends.
