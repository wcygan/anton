# Public exposure attack-path review

Review Anton for unintended access originating from publicly exposed HTTP
services. Focus on concrete attack paths rather than generic hardening advice.

## Attacker and boundaries

The initial attacker is an unauthenticated Internet client. They have no
repository write access, Kubernetes credentials, Cloudflare account access,
operator credentials, or tailnet membership. Do not assume they can create
routes, change labels, or modify policy.

Separately evaluate the consequences of a compromised public workload. Label
that prerequisite explicitly; a post-compromise weakness is not proof that an
Internet attacker can compromise the workload.

Public websites intentionally serve anonymous visitors. Private administration,
storage, unrelated workloads, cluster control planes, and operator credentials
must remain outside that public access boundary.

## Trace the complete path

Inventory public entrypoints and trace:

Internet -> Cloudflare tunnel ingress -> Envoy Gateway listeners -> HTTPRoutes
-> Services -> workloads -> reachable private resources.

Start with cloudflare-tunnel, cloudflare-dns, envoy-gateway, bakery-site,
food-site, default/homepage, default/echo, and the Flux webhook receiver.
Discover other exposure paths across kubernetes/apps rather than treating this
list as exhaustive. Include chart-generated routes and services, namespace
configuration, ReferenceGrants, and network policy definitions where relevant.

Prioritize:

- Accidental private-service exposure through wildcard or catch-all routing,
  incorrect Gateway attachment, cross-namespace backends, and missing
  authorization. Establish who can configure a route before claiming a bypass.
- Hostname, path, rewrite, and proxy-header confusion that can select an
  unintended backend or bypass a real authorization decision. Establish which
  component trusts attacker-controlled input and how it changes the outcome.
- Alternate origin paths that could bypass edge authorization. Do not infer
  Internet reachability from a private LoadBalancer address alone.
- Public webhook authentication, accepted events, replay handling, and the
  operations reachable through forged or unauthorized requests.
- Post-compromise access: network policy selectors, additive policies,
  ingress/egress reachability, DNS, ServiceAccount tokens and RBAC, mounted
  credentials, host privileges, and access to private services or nodes.
- Isolation of cloudflared and the Envoy data plane themselves, distinguishing
  necessary forwarding privileges from unnecessarily broad access.

Verify policy selectors against workload labels and examine chart defaults
where source is available. Neither a policy file nor a passing source contract
proves that a live workload is isolated.

## Application and external configuration gaps

Do not assume a static site has SSRF, upload handling, or code execution without
application source evidence. Identify the image/source relationship and the
application repositories that need separate review of server configuration,
Dockerfiles, dependencies, build output, and any dynamic endpoints. Do not
claim those applications were scanned merely because their manifests were.

Treat Cloudflare dashboard Access/WAF settings, actual tunnel configuration,
router forwarding, rendered Helm defaults, deployed versions, and live network
policy enforcement as unknown unless evidence is available. Separate absent
evidence from a confirmed missing control. Do not decrypt secret substitutions.

## Required results

Produce an entrypoint inventory with intended audience, routing chain, backend,
declared authentication, declared isolation, and unknowns. For each finding,
provide attacker prerequisites, a concrete request or execution path, the
crossed trust boundary, the unintended resource reached, source citations,
existing defenses and counterevidence, severity rationale, minimal remediation,
and a safe verification approach.

Distinguish confirmed source defects, conditional post-compromise weaknesses,
hardening suggestions, and unresolved coverage gaps. Static reasoning must not
be described as a reproduced exploit. A missing local dependency or incomplete
render is inconclusive, not evidence that a path is safe.

Finish with prioritized follow-up checks and application repositories needing
review. Retain the revision and partial-coverage limitations in the report.

## Execution limits

Source review only. Do not contact deployed sites, probe networks, run cluster
or provider commands, access operator credentials, decrypt secrets, modify the
assessed checkout, or perform live exploit tests. Do not launch deployment,
bootstrap, recovery, or reconciliation scripts. Any reproduction must use an
isolated local fixture without private connectivity. Report findings without
patching, creating PRs, publishing reports, or starting post-scan automation.
