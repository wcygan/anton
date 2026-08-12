# 04 — Run the Airflow Kubernetes foundation

**What to build:** Run a small Flux-managed Airflow control plane with isolated Kubernetes task pods and a recoverable external metadata database.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The custom image uses Airflow 3.2.2, Python 3.12, Kubernetes provider 10.21.0, and official constraints.
- [ ] The image contains the Workflow Run source and its tested Spark adapter package.
- [ ] Flux owns Airflow chart 1.22.0 with KubernetesExecutor.
- [ ] One API server, scheduler, DAG processor, and triggerer run within the accepted learning ceilings.
- [ ] KubernetesExecutor starts isolated task pods with bounded resources.
- [ ] A dedicated one-instance CNPG cluster stores Airflow metadata in the Airflow namespace.
- [ ] The shared CNPG operator remains in the platform database namespace.
- [ ] Airflow database credentials arrive through External Secrets Operator.
- [ ] The metadata database has a scheduled backup and a successful restore drill.
- [ ] Airflow starts and retains metadata after the approved restore drill.
- [ ] Kubernetes 1.36 is recorded as a local acceptance target.
- [ ] Repository validation passes without applying unmanaged live state.

## Comments
