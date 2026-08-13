# 04 — Run the Airflow Kubernetes foundation

**What to build:** Run a small Flux-managed Airflow control plane with isolated Kubernetes task pods and a recoverable external metadata database.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] The custom image uses Airflow 3.2.2, Python 3.12, Kubernetes provider 10.21.0, and official constraints.
- [x] The image contains the Workflow Run source and its tested Spark adapter package.
- [x] Flux owns Airflow chart 1.22.0 with KubernetesExecutor.
- [x] One API server, scheduler, DAG processor, and triggerer run within the accepted learning ceilings.
- [x] KubernetesExecutor starts isolated task pods with bounded resources.
- [x] A dedicated one-instance CNPG cluster stores Airflow metadata in the Airflow namespace.
- [x] The shared CNPG operator remains in the platform database namespace.
- [x] Airflow database credentials arrive through External Secrets Operator.
- [x] Backup and restore are explicitly deferred for the experimental learning phase.
- [x] Loss of the CNPG volume is accepted as complete Airflow metadata loss.
- [x] Kubernetes 1.36 is recorded as a local acceptance target.
- [x] Repository validation passes without applying unmanaged live state.

## Comments

- Source revision `ac2c31e1` adds the Airflow image, Helm release, CNPG cluster, ESO credentials, and Longhorn backup target.
- Harbor published `airflow-runtime:3.2.2-ticket04.1` at digest `sha256:9ccd3dcff1f11535c3915434c40602f443c4d5f160673c7f9ced4af094957065`.
- The Linux AMD64 image passed three embedded tests. All 179 repository contract tests passed.
- The required 1Password items exist with the expected field labels. No credential value was printed.
- Flux applied `ac2c31e1`, but the first rollout stopped at the exhausted 1Password quota.
- Revisions `415eed92` and `97bfd370` remove the Helm-hook migration deadlock and use one URL-encoded, consumer-shaped database Secret.
- Flux applied `97bfd370`. The migration Job completed in 19 seconds, and all four control-plane Deployments became Ready.
- Manual run `manual__ticket04_acceptance_20260812T2329Z` succeeded in one `airflow-task` pod with the accepted resource limits.
- The task emitted `airflow-foundation-pass` with Airflow 3.2.2, Python 3.12.13, and Kubernetes provider 10.21.0.
- Scheduler pod replacement preserved the successful DAG run in CNPG metadata.
- All 197 repository tests passed. Scheduled ESO traffic is estimated at 24 operations daily.
- Scheduler replacement proved ordinary metadata persistence. It did not prove backup or disaster recovery.
- ADR 0035 accepts complete Airflow metadata loss during the experimental phase. Backup and restore remain required before authoritative cutover.
- Revision `eafc25d3` removes the unused Barman controller, source, RBAC, certificates, and CRD.
- Pre-removal checks found no `ObjectStore`, CNPG plugin reference, backup, or scheduled backup.
- Flux applied `eafc25d3`. Airflow, CNPG, and Longhorn remained Ready after removal.
- Two orphaned Barman TLS Secrets were deleted after their certificate owners were pruned.
- Ticket 04 closes without a backup or disaster-recovery claim.
- 2026-08-13: Published `airflow-runtime:3.2.2-ticket08.1` at digest `sha256:033982a99d850a01f35c7dc98638db9aa4769eb7e228e182b103b89a42b7e80d`; this supersedes the Ticket 04.1 image pin for the Ticket 08 workflow.
