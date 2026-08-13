# Airflow runtime

This image provides the Airflow control plane, task-pod runtime, and Ticket 05
Apache Spark Operator adapter.
It uses Airflow 3.2.2, Python 3.12, and Kubernetes provider 10.21.0.

Build and run the image tests:

```sh
docker build --platform linux/amd64 --target test \
  --file images/airflow-runtime/Dockerfile .
```

Publish the final Linux AMD64 image to Harbor before live rollout. Record the
new digest in `kubernetes/apps/airflow/airflow/app/helmrelease.yaml`.
