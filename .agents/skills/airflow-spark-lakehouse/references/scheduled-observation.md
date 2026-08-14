# Scheduled Verification

Use this reference after an approved schedule enablement. It defines the
Ticket 11 scheduled verification. It does not authorize a schedule, retry, or
reconcile.

## Start record

Record the Git revision, Flux revision, deployed Airflow image digest, DAG
schedule, enablement time, and next expected run time. A disabled schedule has
`schedule=None`; `is_paused=False` can still permit a manual run.

Prove the deployed DAG matches the recorded digest before the first scheduled
run. Do not use a UI pause value as schedule proof.

## Verification contract

Use this authority and terminal condition:

```text
State source: Airflow Workflow Run history for airflow_spark_lakehouse
Success: one scheduled authoritative run passes the complete evidence path
Failure: no run completes within 20 minutes after its expected start
Failure: an unexplained failure or conflicting Lease holder
```

For the selected scheduled run, retain its DAG, run ID, task ID, try number, exact
SparkApplication, Lease holder, terminal state history, and Trino result.
Compare its Iceberg snapshots with the pre-run state. Check Loki and History
Server before the verification passes.

Retain the enabled schedule, DAG digest, Airflow image digest, and Spark image
digest with the Workflow Run. Bind all values to the exact Spark Attempt.

Retain Trino schema, count, partition, location, and pre-run and post-run
snapshot results. Record peak memory use and the applicable memory ceiling.
Record any unavailable resource sample and its collection limit.

Block cleanup after an unexplained failure. Report the earliest failing layer.
Do not claim verification before the complete identity chain agrees.
