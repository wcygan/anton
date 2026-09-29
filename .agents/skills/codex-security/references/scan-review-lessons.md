# Scan review lessons

These rules capture recurring mistakes from Anton's September 2026 script
and public-exposure reviews. Current configuration and commands belong in the
[workspace guide](../../../../.codex-security/README.md); dated findings and
deployment evidence belong in the
[remediation record](../../../../context/notes/2026-09-29-codex-security-remediation.md).

## Reconcile counts and coverage before prioritizing

1. Read `report.md`, `findings.json`, `coverage.json`, and `scan-manifest.json`
   when available. Compare their scope/revision to the terminal summary. Use
   installed `scans`/`findings`/`export` help if the saved-output layout changes.
2. Separate new findings from previously found entries in the persistent
   workflow. One exposure run displayed eight findings (one new and seven
   previously found), while its run-local artifacts contained the one new
   finding. A repeat counter alone does not demonstrate regression or failed
   remediation.
3. Reconcile deferred candidates against the final candidate disposition table.
   Earlier coverage retained duplicate candidates and stale awaiting-validation
   text for candidates the final report rejected. Account for every candidate
   without promoting it to an additional confirmed vulnerability.
4. Preserve `partial` coverage even when all selected files were visited. Missing
   application code, failed runtime reproduction, external settings, omitted
   archive paths, or unavailable dependencies can still limit the assessment.
5. Record manual source validation separately from a new model-backed validation
   run. Passing fixtures, source edits, and a historical finding's status are
   different evidence. Total token counts can be dominated by cache reads;
   report the supplied breakdown without inferring dollars from total tokens.

## Trace attacker access through the actual boundary

For each accepted finding, name the starting capability, reachable input,
sensitive operation/resource, intervening protections, and concrete impact.
Distinguish unauthenticated visitor access, authenticated misuse, and access
that already requires a compromised pod or operator account. The edge-to-
Headlamp finding required an independent edge compromise; it established no
initial Internet compromise or Headlamp authentication bypass.

Public exposure has several independently owned surfaces:

| Surface | Evidence to collect |
| --- | --- |
| Application source | Input handling, authorization, static file serving, client rendering, build outputs and runtime entry point |
| Kubernetes intent | Tunnel origins, Gateway/HTTPRoute/backend selection, token mounts, RBAC, pod security and isolation |
| Applied runtime | Actual labels/ports, effective policies, controller readiness, positive and negative traffic behavior |
| Cloudflare account | Effective tunnel overrides, Access/WAF policies, DNS ownership, stale tunnels/origins |
| Network perimeter | Router NAT/UPnP, IPv6 firewall, direct-origin ingress and reachable NodePorts |

A Kubernetes manifest scan covers only its supplied source. Wildcard tunnel
routing, Gateway `allowedRoutes: All`, a LoadBalancer/NodePort, and public content
without login require contextual review; none alone proves an access exploit.
Build-time TanStack/Nitro dependencies are not automatically reachable SSR/API
code when the image ships only static nginx assets. Mutable action/image tags
are provenance gaps; verify actual SHAs, digests and shipped package versions
before accepting a supply-chain vulnerability.

For application scans, match the selected source revision to deployment leads
and distinguish tag identifiers from verified build provenance. Preserve dirty
work in other checkouts. Anonymous 404 responses are not evidence that a repo
is absent; use reviewed committed-source exports rather than importing GitHub
credentials into the scanner. Report `REVIEW_SOURCE.json` exclusions and use
fresh extraction directories so older files do not contaminate a new snapshot.

## Validate isolation and controller privileges deliberately

- Inspect the pinned chart render and applied pod labels, token mounts and
  container ports. A Service port may differ from its destination pod port;
  policies must reflect the actual packet path. Read Helm defaults rather than
  assuming that omitted `automountServiceAccountToken` disables credentials.
- Model selector conjunction correctly: namespace and pod selectors in one
  peer are AND; separate peers are OR. Check all additive Kubernetes/Cilium
  policies and host-network/node-origin exceptions. Selector fixtures explain
  intended semantics; they do not reproduce packet enforcement.
- Enumerate current public backends across namespaces before restricting edge
  traffic. Anton's source tree can omit externally owned applications such as
  CS2Plant. Account for DNS, origin listener ports, xDS, probes, metrics, and
  effective provider configuration. The
  [proposal guide](../../../../.codex-security/proposals/README.md) records the
  staged rollout; recheck its dated inventory before use.
- Prefer a narrow destination ingress repair when it addresses the confirmed
  path. Broad edge egress hardening needs a separate connectivity inventory and
  the one-workload-at-a-time acceptance in ADR 0029.
- A webhook Secret reference alone is not proof of authentication. Inspect the
  deployed implementation's nonempty-token/signature checks, event filtering,
  fixed reconciliation targets, request limits and replay behavior. Repeated
  signed requests requesting reconciliation do not demonstrate manifest
  injection. Establish runtime behavior only through approved tests.
- Audit effective controller RBAC through every Role/ClusterRole and binding.
  The notification controller's shared Flux role was a conditional impact
  concern discovered outside the new scanner finding. Separating its identity
  requires mapping cache watches, secrets, leader election and reconciliation
  targets; editing a shared role affects other controllers. RBAC verbs cannot
  constrain a patch to one field, so consider the impact of permitted spec
  changes as well as resource names.

## Define completion for the requested stage

Scanner setup is complete after frozen installation, saved-profile dry runs,
documented input preparation and required repository checks pass. A source fix
is complete after its diff and relevant regression checks pass. A live finding
also needs the intended Flux revision, applied object/generation, stable
workload/dependency state, and user-visible positive/negative acceptance.
Report missing evidence explicitly and return the operator handoff at any
remaining authority boundary. Keep raw reports, tokens, private addresses and
credential-derived webhook paths out of committed summaries and output.
