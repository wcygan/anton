# Airflow foundation

Flux owns the Airflow control plane and its one-instance metadata database.
The accepted local Kubernetes target is Kubernetes 1.36.

The Airflow image and task-pod template use the same Harbor image digest.

ADR 0035 accepts complete metadata loss during the experimental phase.
Longhorn replication is not a backup. Add an independent backup target and
test restoration before authoritative cutover.
