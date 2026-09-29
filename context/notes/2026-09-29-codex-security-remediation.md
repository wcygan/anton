# Codex Security remediation — 2026-09-29

Source: local scan `dcae33d8-382e-4f7c-843a-46d8de07161f`, output directory
`codex-security-anton-3Z8ML2`. The scan covered scripts with **partial** coverage.
Private raw reports remain outside Git. This record is manual source triage and
regression verification, not a new scanner validation or runtime security audit.

## Reported findings

| Finding | Disposition | Evidence |
| --- | --- | --- |
| Additive RBAC permissions hidden by duplicate rules | Fixed | `5067db7a`: aggregate permissions across rules; regression tests |
| Extra RBAC documents and unchecked roleRef | Fixed | `5067db7a`: exact document set and binding identity |
| Compound context change before mutation | Fixed | `5067db7a`: reject mixed target changes and mutations before probes; both agent adapters tested |
| Admission CEL checked only for tokens | Fixed | `b709c42d`: compare independent complete policy and binding specs; no claim of runtime CEL evaluation |
| ExternalSecret discovery bypass through YAML spelling | Fixed | `b709c42d`: parse all YAML documents before kind selection |
| Retained artifact path escape | Fixed | `b709c42d`: resolved containment checks; `ee84a92f`: bounded regular-file reads |
| Public internal node endpoints | Fixed in current source | Public inventory contains names only; endpoints moved to ignored `.private/cluster-targets.json`. Existing local fallback preserved. Fresh clones need live discovery or private setup. Previously published addresses remain in Git history. |

## All 19 deferred entries

The coverage file preserves duplicate candidates and stale “awaiting validation”
messages. The report's final candidate table rejects several of those candidates.
They are not 19 additional confirmed vulnerabilities.

| Candidate IDs | Disposition |
| --- | --- |
| `observation-forged-ledger` | Rejected security candidate: the supported CLI obtains observations from the target-verified live observer; no lower-trust mapping input was established. The local persistence API does not authenticate arbitrary caller data. |
| `ledger-write-limit`, `ledger-write-read-limit` | Fixed in `ee84a92f`: preview and atomic writes enforce the reader's encoded byte limit and preserve the old ledger on failure. |
| `task-injection-outside-scope`, `task-variable-command-injection` | Fixed in `ee84a92f`: environment values passed as quoted shell arguments; hostile values tested through the real Task engine with an inert script. |
| `airflow-shadow-trigger`, `airflow-shadow-trigger-target` | Retired helper now rejects execution and command previews before I/O. |
| `airflow-recovery-trigger`, `airflow-recovery-authoritative-trigger` | Removed obsolete recovery execution; historical plans remain readable and marked retired. Direct runtime trigger also rejects calls. |
| `airflow-shadow-gate-forgery` | Rejected security candidate: caller-owned historical evidence is not authenticated provenance; no automatic promotion or lower-trust producer was found. |
| `airflow-trino-fabrication`, `airflow-shadow-trino-fabrication` | Rejected security candidate: retained shadow simulation evidence is caller-owned and has no automatic promotion consumer. Do not interpret it as an independent live Trino check. |
| `baseline-bootstrap-target` | Rejected security candidate: supported Task supplies repository kubeconfig; direct script invocation relies on trusted operator-selected configuration. |
| `cluster-talos-env-target`, `cluster-kube-env-identity` | Rejected security candidates: intentional operator environment overrides, with no lower-trust setter established. |
| `cluster-talos-context-switch` | Duplicate of fixed compound-command finding (`5067db7a`). |
| `baseline-retained-path-traversal`, `airflow-retained-path-traversal` | Duplicates of fixed retained-path finding (`b709c42d`, `ee84a92f`). |
| `baseline-topology-exposure` | Duplicate of the endpoint disclosure fix above. |

## Final repository hardening

- Shadow retirement follows the completed cutover in
  [Plan 0023](../plans/0023-roll-out-airflow-spark-lakehouse.md): the shadow
  control plane was removed on 2026-08-14. The retired helper must not invoke
  the authoritative DAG under a shadow label.
- Malformed retained JSON now stops collection, preventing repeated invalid
  files from bypassing accounting of successfully decoded bytes.
- Spark and Airflow source-contract expectations now match already committed
  base-image and Hadoop upgrades. No runtime image or deployment was changed.
  Airflow still installs its explicitly selected 3.2.2 package over the newer
  base image; the validator continues checking that separate package pin.

## Verification and limits

Run `mise exec -- task contracts:validate` for all repository contracts and the
Python regression suite. No cluster apply, reconcile, credential changes, or
live recovery tests were performed. These checks do not prove deployed revision,
container compatibility, or complete vulnerability coverage. Retained local
evidence and operator environment configuration remain trusted inputs; neither
is a security boundary against an actor controlling the operator account.

## Endpoint privacy follow-up

The private fallback migration closes the last open source finding. Regression
checks cover complete live discovery and overrides without private state,
complete-set fallback, malformed/missing private files, and redacted output.
Validation uses synthetic addresses and does not require operator state. Copies
of the old endpoints were also redacted from 12 historical records in current
source, preserving node identity with placeholders.
No endpoint rotation or Git history rewrite was performed. Historic disclosure
cannot be undone by this source fix; an address is not an authentication token.

A bounded source inspection of public exposure found no additional confirmed
exploit: bakery and food-site declare Envoy-only ingress and DNS-only egress;
the Flux webhook declares GitHub event handling with a secret reference.
Wildcard tunnel routing and cross-namespace Gateway attachment remain review
subjects, not independently confirmed internet exploits. A dedicated exposure
scan, application-source review, rendered-chart inspection, Cloudflare policy
review, and live enforcement checks remain coverage gaps.

Verification: all repository contracts and 342 Python tests passed; scanner
frozen install and source dry run passed; Docusaurus production build passed.
The separate docs typecheck remains blocked by the existing TypeScript 6
`baseUrl` deprecation in its Docusaurus configuration, unrelated to these edits.

## Public exposure scan follow-up

Scan `8b033a60-ec0d-4581-8f78-f63e14e2c7f2` reviewed `kubernetes/apps` at
`222f51c2`. Its run-local artifacts contain one new low-severity finding,
`network-exposure.missing-edge-egress-isolation`, with partial coverage. It
describes conditional access from an independently compromised edge pod to
Headlamp; it does not establish an Internet compromise or authentication bypass.

Remediation adds `headlamp-isolation`, selecting only the Headlamp workload and
allowing ingress only from its exact managed Tailscale Ingress proxy in namespace
`tailscale`, on named TCP port `http`. The policy is wired into the Headlamp Flux
app. This closes the reported ordinary pod-to-Headlamp path in desired state
without restricting other `kube-system` workloads or changing gateway egress.

Read-only preflight verified the Anton context and endpoint, Headlamp's applied
labels and container port 4466, its Service mapping from port 80, and the dedicated
Tailscale proxy's four parent/managed labels. No NetworkPolicy existed in
`kube-system` at that evidence time. The pinned Headlamp 0.45.0 chart was rendered
with repository values and matched those labels and port. All contracts and 346
tests passed, including allowed/blocked selector cases and Kustomize inclusion.
These checks do not reproduce network enforcement or authentication behavior.

Status: source remediation complete; deployed enforcement verification pending.
Acceptance requires the applied Flux revision and policy, Headlamp readiness,
working Tailscale access/token login, blocked direct edge-to-Headlamp traffic,
and rejection of unauthenticated data requests. Live synthetic traffic requires
separate operator approval. Rollback and verification are documented in the
Headlamp README. No apply, reconcile, debug workload, or live traffic test was
performed during source remediation.

Broader public-edge egress isolation remains a separate improvement: first map
cloudflared upstream/DNS needs and Envoy backend and control-plane connections.
Website application source, Cloudflare policy, and other runtime coverage gaps
from the report remain unresolved.
