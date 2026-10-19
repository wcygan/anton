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

The candidate commit and any future activation commit are separate. Candidate
commit `b7b7e2c861236958f0eae542adbbe3aff6aebee6` only adds this staged file,
its source contract, and this runbook; it does not change the active policy set
or provide an active isolation benefit. An operator reviewing activation must
make a new commit that adds exactly
`./staged/networkpolicy-harbor-postgres.yaml` to
`kubernetes/apps/registries/harbor-config/app/kustomization.yaml`. The resource
identity is `NetworkPolicy/harbor-postgres-ingress-candidate` in namespace
`registries`, selecting `cnpg.io/cluster=harbor-postgres` and
`cnpg.io/podRole=instance`.

Before that separate activation commit is approved, run these read-only
preflight checks from the intended repository revision and operator context:

```sh
git rev-parse HEAD
mise exec -- kubectl config current-context
mise exec -- kubectl get namespaces registries databases observability
mise exec -- kubectl -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}{"\n"}'
mise exec -- flux get ks -n flux-system harbor-config harbor
mise exec -- flux get hr -n registries harbor
mise exec -- kubectl -n registries get cluster harbor-postgres
mise exec -- kubectl -n registries get pods -l cnpg.io/cluster=harbor-postgres --show-labels
mise exec -- kubectl -n registries get networkpolicy
mise exec -- kubectl -n registries get podmonitor harbor-postgres -o yaml
mise exec -- kubectl -n observability get pods -l app.kubernetes.io/name=prometheus --show-labels
mise exec -- kubectl -n databases get pods -l app.kubernetes.io/name=cloudnative-pg --show-labels
```

The current context must be the Tailscale operator proxy for Anton. Stop if the
context, source revision, namespace, owner resources, selectors, three CNPG
instance roles, or baseline readiness differs from the recorded evidence.
Confirm no new policy selects the PostgreSQL pods and ask each named owner
whether an additional client exists. Do not activate based on a quiet traffic
capture.

During an approved maintenance window, apply the activation commit through the
normal GitOps publication path. Do not force a reconcile. Start the 15-minute
convergence timer only after the source artifact contains the activation
revision; if the source or `harbor-config` `lastAppliedRevision` has not reached
that commit within 15 minutes, stop and return to Flux diagnosis without
continuing traffic checks. After apply, allow at most 15 minutes for the
acceptance observation and one prearranged operator operation. Stop immediately
if any CNPG instance is not Ready, Harbor API/HelmRelease readiness regresses,
the CNPG scrape target goes down, the operator operation fails, or the observed
source identity/port differs from the matrix. Record each condition's
timestamp, reason, message, and generation.

Positive checks for Harbor registry push/pull, operator backup/maintenance,
and negative connection attempts are traffic-producing actions. They require
separate approval naming the exact client and operation. If a temporary Job or
other diagnostic workload is proposed, obtain approval for its image,
namespace, service account, command, timeout, and cleanup command before
creating it. This runbook does not authorize or perform those checks. Accept
only after the approved positive operations succeed and a separately approved
unauthorized client cannot connect to TCP 5432; keep the evidence with the
activation review.

If a stop trigger fires, create a rollback commit by reverting the **activation
commit hash**, never the staged-candidate commit:

```sh
git revert --no-edit <activation-commit>
```

Publish that revert through the normal GitOps path. Confirm the source artifact
and `harbor-config` `lastAppliedRevision` include the revert, then verify the
ready condition and prune result:

```sh
mise exec -- kubectl -n flux-system get gitrepository flux-system -o jsonpath='{.status.artifact.revision}{"\n"}'
mise exec -- kubectl -n flux-system get kustomization harbor-config -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason} message={.message}{"\n"}{end}'
mise exec -- kubectl -n flux-system get kustomization harbor-config -o jsonpath='{.status.lastAppliedRevision}{"\n"}'
mise exec -- kubectl -n registries get networkpolicy harbor-postgres-ingress-candidate
```

The last command must report `NotFound`; if it returns an object, or the
Kustomization is not Ready at the revert revision, stop and continue Flux
diagnosis. Recheck CNPG, Harbor, and Prometheus readiness before closing the
rollback. If activation never occurred, leave the policy staged; the candidate
commit itself has no cluster rollback to perform. The source-level test renders
the active Kustomize tree and enforces this inactive boundary.
