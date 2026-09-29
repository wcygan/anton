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

## Public workload credential minimization

Read-only inspection now confirms Headlamp's Kustomization has applied
`fe5c94f1` and `headlamp-isolation` exists. Headlamp remains ready. This is
deployment evidence, not a packet-level enforcement or login test.

The bakery, food-site, echo, and cloudflared pods had Kubernetes ServiceAccount
token mounts despite not needing the Kubernetes API. Set explicit
`defaultPodOptions.automountServiceAccountToken: false` in all four owning
HelmReleases. Homepage and both Envoy data planes already disable automount.
No extra RBAC permissions or exploit through these tokens was established.
Infrastructure controllers that use the API retain their tokens.

The exact app-template 4.6.2 chart rendered all four modified workloads with
automount disabled; all repository contracts and 346 tests passed. Natural
Flux reconciliation and absence of projected API-token mounts remain deployment
acceptance checks. No application images, credentials, or live commands changed.

Read-only deployment verification after natural reconciliation found all eight
replacement pods ready, with zero restarts, automount disabled, and zero API
token mounts. The cloudflared HelmRelease reports its latest generation ready.
No direct cluster mutation or force reconcile was performed.

## Remaining public exposure priorities

The edge egress proposals in `.codex-security/proposals/` are outside Flux and
remain inactive. They preserve observed CoreDNS, external Envoy listener,
Cloudflare transport, xDS, and all six public backend paths, including CS2Plant,
whose manifests are owned outside Anton. Seven source connectivity tests cover
required paths and forbidden private destinations, namespace/port boundaries,
and accidental activation. These are source semantics, not a runtime test.
Effective provider-side tunnel configuration must be checked before deployment.
ADR 0029 requires acceptance of each workload before expanding isolation.

A bounded manual review matched deployed image source identifiers to local
application revisions: bakery `cc273ca`, food-site `65d6411`, homepage `9d7a0a2`.
Bakery's existing local edits were preserved and excluded from review bundles.
Bakery and food-site Dockerfiles package only static `dist/client` into nginx;
their TanStack/Nitro server tooling is build-time. Homepage packages Vite `dist`
and a Bun file server with a lexical path-containment check. No confirmed
initial-access exploit was established. This is not a dependency audit, image
inventory, full model scan, symlink/runtime reproduction, or proof that image
contents match tags. Mutable nginx base tags and CI action tags remain build
provenance gaps, not evidence of a reachable CVE.

Prepared whole-application scanner configuration and prompt, and ignored
source-only bundles with original revision/digest manifests. All three source
configuration dry runs passed; an extracted food-site bundle also passed without
Git metadata. Frozen scanner installation passed. No model-backed application
scan ran: a disposable environment with only model authentication and no private
connectivity is still required. Anonymous requests returned 404 for all three
application repositories; no GitHub credential was accessed or source published.

The deployed Receiver is ready and selects only GitRepository `flux-system`
and Kustomization `flux-system`, for GitHub `ping`/`push`. Its deployed
notification-controller v1.9.4 [handler](https://github.com/fluxcd/notification-controller/blob/v1.9.4/internal/server/receiver_handlers.go)
calls signature validation before requesting reconciliation of those configured
resources. The [go-github v64 validator](https://github.com/google/go-github/blob/v64.0.0/github/messages.go)
requires a valid HMAC when the configured token is nonempty; an empty token does
not provide that guarantee. No Secret values were read. No webhook-path/delivery
replay cache was established in that handler; replay of an already signed
request can request reconciliation again but cannot select arbitrary resources
or inject manifests. Runtime invalid-signature/replay tests remain unperformed.

The notification-controller ServiceAccount is bound to the shared
`crd-controller-flux-system` ClusterRole: wildcard writes across Flux API groups
and read access to Secrets across namespaces. This is a significant conditional
impact if that Internet-facing process is independently compromised, not a new
confirmed initial exploit. Next hardening should separate its identity/role
from the other Flux controllers, scope its watched notification objects and
secrets to `flux-system`, and permit only the receiver's intended reconciliation
targets. First render the pinned Flux distribution and map actual controller
cache, secret-watch, leader-election, and alert/provider requirements; blindly
editing the shared role would affect unrelated controllers. No RBAC change was
made during this bounded review.

Cloudflare account Access/WAF/tunnel/DNS state and router NAT/UPnP/IPv6 firewall
remain unverified because this session has no established read-only provider or
router access. Gateway `allowedRoutes: All` and external LoadBalancer NodePorts
exist; they are review surfaces, not proof of Internet exposure. Check for
unexpected public hostnames/origins, retired tunnel DNS records, and a direct
origin route bypassing Cloudflare. Keep administrative interfaces tailnet-only.
Headlamp packet enforcement and token/login checks remain operator-gated live
verification. The committed source changes do not close these coverage gaps.

Final source validation: frozen scanner install, default source check, all three
application dry runs, extracted-bundle dry run, all repository contracts and
353 Python tests passed. `git diff --check` passed. Archives and manifests remain
ignored with owner-only file permissions. No model calls, provider changes,
cluster apply/reconcile, debug workloads, or synthetic traffic were performed.

## Reusable scan setup acceptance

`security:source-check` now validates all three saved profiles/prompts through
CLI dry runs; the application profile uses a harmless workspace placeholder.
`security:source-export REPOSITORY=... REVISION=...` regenerates allowlisted
application archives and manifests from an explicit committed revision into
ignored private storage. It preserves dirty work, rejects links/submodules and
recognized credential-like paths before reading their payloads, and records
actual exported files, source revision, and archive digest. It is not a detector
for credentials embedded in ordinary code. Excluded paths remain coverage gaps.

Regression fixtures exercise commit selection versus dirty/untracked/ignored
work, omitted operator files, new-revision regeneration, file permissions and
provenance, link/credential-like-file rejection, and literal Task argument
handling. Scanner setup acceptance is independent of the unresolved runtime,
provider, notification RBAC, and model-backed review work above.
