# Airflow foundation

Flux owns the Airflow control plane and its one-instance metadata database.
The accepted local Kubernetes target is Kubernetes 1.36.

The Airflow image and task-pod template use the same Harbor image digest.
Metadata backup requires an independent off-cluster target. Do not use the
same SeaweedFS and Longhorn failure domain as a durable backup target.
