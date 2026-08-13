# Airflow runtime

This image provides the Airflow control plane, task-pod runtime, and the
Apache Spark Operator adapter with Ticket 06 recovery receipts.
It uses Airflow 3.2.2, Python 3.12, and Kubernetes provider 10.21.0.

The image also contains the manual `airflow_loki_source` DAG. That DAG queries
one five-minute Loki window, writes a deterministic JSONL snapshot to
`iceberg-raw`, and submits a shadow-only Spark Attempt.

Build and run the image tests:

```sh
docker build --platform linux/amd64 --target test \
  --file images/airflow-runtime/Dockerfile .
```

Publish the final Linux AMD64 image to Harbor before live rollout. Record the
new digest in `kubernetes/apps/airflow/airflow/app/helmrelease.yaml`.
