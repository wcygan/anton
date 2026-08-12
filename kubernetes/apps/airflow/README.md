# Airflow foundation

Flux owns the Airflow control plane and its one-instance metadata database.
The accepted local Kubernetes target is Kubernetes 1.36.

The Airflow image and task-pod template use the same Harbor image digest.
The metadata backup uses a CNPG scheduled backup and a Longhorn S3 backup.
