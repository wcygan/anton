# Internal service boundaries

## Harbor PostgreSQL ingress candidate

**Status:** Review candidate only. The policy is under `staged/` and is not in
the active Harbor config Kustomize tree.

**Outcome:** Limit inbound connections to the Harbor-owned PostgreSQL pods to
Harbor, CNPG replication peers, the CNPG operator status/backup endpoint, and
the Prometheus scrape client. Keep all egress policy unchanged.

**Baseline:** The cluster intake inventory reports five public workloads with
bidirectional policies and ten public pods without token mounts under restricted
PSA. Registries currently has no policy selecting CNPG PostgreSQL pods; its
existing policy selects Dragonfly only. Read-only live inventory on 2026-10-19
found Harbor and all three CNPG instances Ready, one primary, generated CNPG
instance labels, Harbor's database target `harbor-postgres-rw:5432`, the
CNPG-generated PodMonitor, and no `Backup` or `ScheduledBackup` objects in the
registries namespace. There is no observed existing outage to repair.

| Client owner | Source selector | Destination port | Evidence |
| --- | --- | ---: | --- |
| Harbor | `registries`, `app.kubernetes.io/instance=harbor` | TCP 5432 | Harbor Helm values point to `harbor-postgres-rw:5432`; live pod labels match. |
| CNPG peers | `registries`, `cnpg.io/cluster=harbor-postgres`, `cnpg.io/podRole=instance` | TCP 5432 | Live CNPG labels and three-member cluster; PostgreSQL peer traffic uses the operand port. |
| CNPG operator | `databases`, `app.kubernetes.io/instance=cloudnative-pg`, `app.kubernetes.io/name=cloudnative-pg` | TCP 8000 | Live Deployment identity; [CNPG 1.30 security docs](https://cloudnative-pg.io/docs/1.30/security/) document this as the instance-manager status port, including sensitive backup operations. |
| Prometheus | `observability`, `app.kubernetes.io/instance=kube-prometheus-stack-prometheus`, `app.kubernetes.io/name=prometheus` | TCP 9187 | Live Prometheus pod identity and CNPG PodMonitor selector/`metrics` endpoint; [CNPG 1.30 security docs](https://cloudnative-pg.io/docs/1.30/security/) list instance metrics on 9187. |
| Backup destination | No ingress peer | None | No Backup or ScheduledBackup CR exists in `registries`; the candidate is ingress-only and leaves database egress unrestricted. Existing continuous archiving status is not evidence of an ingress client. |

The candidate selects the live CNPG labels and uses Kubernetes' immutable
namespace-name label for cross-namespace peers. It is intentionally not wired
to the active Kustomization because source-level client ownership does not prove
that Cilium enforces the expected policy behavior or that every cluster
controller path remains healthy.

### Activation gate

Before adding the candidate to `app/kustomization.yaml`, the operator must
confirm the exact change in a review and collect before/after evidence during an
approved maintenance window:

1. Record the current Flux source revision, `harbor-config` and `harbor`
   Kustomization/HelmRelease readiness, the three CNPG instance roles, the
   Harbor API health result, and Prometheus targets for the CNPG PodMonitor.
2. Confirm the live selectors and version still match the table above. Check
   whether any policy already isolates the target pods and whether any client
   is outside the named service owners.
3. Add only `./staged/networkpolicy-harbor-postgres.yaml` to the app
   Kustomization, reconcile through the normal GitOps path, and observe CNPG
   primary/replica readiness, Harbor API health and registry push/pull, the
   CNPG scrape target, and operator-managed backup/maintenance behavior through
   at least one known operation window. Do not infer completeness from a quiet
   flow capture.
4. Accept only if all positive paths succeed and an unauthorized in-cluster
   client cannot connect to port 5432. Retain timestamps, identities, resource
   generations, and the user-visible checks with the change review.

The manifest is ingress-only. If a required client or port is missing, remove
the policy from the active app Kustomization and let Flux prune it; do not
broaden selectors or ports without new owner evidence. If the candidate has not
been activated, rollback is simply to leave it staged. The source-level test
renders the active Kustomize tree and enforces that boundary.
