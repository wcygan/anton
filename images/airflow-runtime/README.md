# Airflow runtime

This image provides the ticket 04 Airflow control-plane and task-pod runtime.
It uses Airflow 3.2.2, Python 3.12, and Kubernetes provider 10.21.0.

Build and run the image tests:

```sh
docker build --platform linux/amd64 --target test \
  --file images/airflow-runtime/Dockerfile .
```

Publish the final Linux AMD64 image to Harbor. Record the returned digest in
`kubernetes/apps/airflow/airflow/app/helmrelease.yaml`.
