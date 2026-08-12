# 04 — Run the Airflow Kubernetes foundation

**What to build:** Run a small Flux-managed Airflow control plane with isolated Kubernetes task pods and a recoverable external metadata database.

**Blocked by:** None — can start immediately.

**Status:** in-progress

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

- Source revision `ac2c31e1` adds the Airflow image, Helm release, CNPG cluster, ESO credentials, and Longhorn backup target.
- Harbor published `airflow-runtime:3.2.2-ticket04.1` at digest `sha256:9ccd3dcff1f11535c3915434c40602f443c4d5f160673c7f9ced4af094957065`.
- The Linux AMD64 image passed three embedded tests. All 179 repository contract tests passed.
- The required 1Password items exist with the expected field labels. No credential value was printed.
- Flux applied `ac2c31e1`. The rollout is waiting for 1Password to accept ESO reads after its current rate limit.
