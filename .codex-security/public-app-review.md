# Public application initial-access review

Review the selected application repository for unintended access by an
unauthenticated Internet visitor. This is report-only source review. Do not
edit source, deploy, run live probes, retrieve credentials, or contact private
resources. Use only the isolated environment described in Anton's scan README.

Establish the assessed commit and deployment shape from Dockerfile, build
workflow, lockfile, serving entry point, and route configuration. Distinguish
static client artifacts from a runtime SSR/API server. Build-time framework
dependencies are not automatically reachable production server code. Report
when the assessed commit differs from the source identifier in the deployed
image, and do not infer image contents or package versions from a mutable tag.

Trace visitor input to file reads, path resolution, redirects, proxy/upstream
selection, server functions, command execution, HTML rendering, and browser
storage. Assess path traversal, symlink escapes, malformed URL decoding,
unintended file/source-map exposure, XSS, open redirects, SSRF, unsafe server
functions, missing authorization, and exposed admin/debug endpoints where
those mechanisms actually exist. Distinguish crashes or resource exhaustion
from unintended data access or execution. A static website can still expose
private build artifacts or execute unsafe client code.

Inspect the production packaging boundary for unexpected files, environment
or secret material copied into client bundles, runtime credentials, writable
directories, user/capabilities, development servers, and unnecessary API access.
Do not request or print secret values. Evaluate CI/build supply-chain inputs
separately from a request-triggered exploit: check pinned lockfile resolution,
actual action SHAs, runtime image provenance, and whether claimed dependency
advisories affect code that is actually shipped and reachable. Mutable tags
and missing evidence are coverage/reproducibility gaps, not confirmed CVEs.

Anton provides Cloudflare tunnel -> external Envoy -> application Service.
Static bakery and food-site images package dist/client under nginx on port
8000. Homepage packages Vite dist plus a custom Bun static server on port 3000.
Treat these as deployment leads to verify against this repository, not proof
that the running cluster matches the source. Intended sites are public; lack
of login for published content is not a vulnerability. Kubernetes isolation,
router/firewall state, Cloudflare Access/WAF/DNS, signed Flux webhooks, image
package inventory, and running-container contents are separate coverage areas.

For each finding, provide the attacker prerequisite, exact source location,
reachable input-to-sensitive-action path, concrete impact, confidence, and
smallest practical correction. Explicitly identify required preexisting
compromise or account access. Keep rejected hypotheses and unresolved runtime
checks separate from confirmed findings. Do not describe speculative lateral
movement as a demonstrated Internet entry point.
