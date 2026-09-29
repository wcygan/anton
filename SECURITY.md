# Anton security policy

## What this codebase does

Anton is a hand-edited Talos Linux and Kubernetes homelab repository. The
committed source of truth is split across `kubernetes/` (GitOps-managed
manifests), `talos/` (machine configuration and patches), and `bootstrap/`
(the initial installation layer), with operator scripts under `scripts/`.
The repository is public; this file intentionally describes architecture and
security boundaries without naming credentials, private endpoints, addresses,
or operator-only access details.

## Auth shape

There is no application login system in this repository. The important
security boundaries are Kubernetes RBAC and ServiceAccount tokens, the GitOps
controller identity, encrypted bootstrap secrets, an external secret-manager
integration, and a separate operator-mediated path for Kubernetes API access.
Public application traffic enters through Gateway API resources and a tunnel;
internal administration is deliberately separate from public ingress.

## Threat model

The highest-impact failures are unauthorized Kubernetes API access, privilege
escalation through broad RBAC or ServiceAccounts, accidental exposure of
private services through public Gateway/HTTPRoute configuration, and leakage
of encrypted-secret material or operator credentials. A compromised public
workload must not reach cluster-admin capabilities, platform control planes,
or unrelated namespaces. Findings must distinguish committed intent from live
cluster state: this scan cannot prove that the cluster currently matches Git.

## Project-specific patterns to flag

- Inspect `Role`, `ClusterRole`, bindings, and ServiceAccount usage for
  unnecessary wildcard verbs/resources, cross-namespace access, or token
  automounting on workloads that do not call the Kubernetes API.
- Inspect Flux `Kustomization`, `HelmRelease`, source, and dependency
  configuration for privilege boundaries, unsafe substitutions, and paths
  that could cause a low-trust change to control platform resources.
- Inspect Gateway API, `HTTPRoute`, `DNSEndpoint`, and external tunnel
  configuration for unintended public exposure or routes crossing the
  internal/public boundary.
- Inspect Pod security context, host networking, host paths, privileged
  containers, broad capabilities, and node-facing tooling, especially in
  CNI, storage, logging, and monitoring workloads.
- Inspect encrypted-secret references and scripts for plaintext secret
  handling, secret values in logs, or accidental use of operator credentials.

## Known false-positives

- Talos, Cilium, Multus, Longhorn, storage-vxlan, node logging, and other
  platform components may intentionally require privileged, host-network,
  host-path, or node-level access; verify the narrowest required scope.
- Encrypted secret files are ciphertext by design. Do not request decryption
  or treat encrypted values as plaintext credentials.
- The operator-mediated API path and public tunnel are intentional access
  paths, but their exposure and RBAC bindings still require review against the
  documented internal/public split.
- Bootstrap manifests may contain one-time cluster-admin setup needed before
  Flux takes ownership; distinguish bootstrap privilege from steady-state
  workload privilege.
- The repository's security audit scripts intentionally invoke read-only
  `kubectl`, Trivy, and Kubescape checks; they do not themselves prove a
  vulnerability in the cluster.

## Review and verification policy

Codex Security is the source-review tool; see `.codex-security/README.md` for
setup and `.agents/skills/codex-security/SKILL.md` for the agent workflow.
The scanner reviews committed intent, not the running cluster. Findings need
cited source, attacker prerequisites, affected boundaries, and explicit coverage
limits. Runtime validation must use an isolated test environment; static
reasoning alone must not be labeled a reproduced exploit.

Use the narrowest necessary privileges. Infrastructure exceptions require a
specific operational reason and bounded scope. Compare network isolation with
ADR 0029, while treating its desired posture separately from deployment proof.
Keep raw findings private; publish only reviewed, sanitized summaries.

Remediate at the authoritative owner and validate the change with relevant
repository contracts. For live findings, record the fix revision, Flux
reconciliation, applied configuration, controller readiness, and user-visible
verification before marking the issue resolved. A merged patch is insufficient.
