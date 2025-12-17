---
description: Get Kubernetes best-practice answers tailored to your cluster setup
---

Answer the user's Kubernetes question with idiomatic, production-ready guidance.

**Your cluster context:**
- **Platform:** Talos Linux (immutable, API-driven)
- **GitOps:** Flux with HelmReleases and Kustomizations
- **CNI:** Cilium with Gateway API, L2 announcements, kube-proxy replacement
- **Storage:** Rook-Ceph (ceph-block StorageClass)
- **Ingress:** Envoy Gateway (envoy-internal, envoy-external)
- **External access:** Cloudflare tunnel
- **Secrets:** SOPS with Age encryption

**Response structure:**

### 1. Direct Answer
Provide the recommended approach clearly and concisely.

### 2. Why This Is Best Practice
Explain the reasoning - what problems does this solve? Reference industry consensus.

### 3. Implementation Example
Provide YAML or commands tailored to the user's Flux/GitOps workflow when applicable.

### 4. Anti-Patterns to Avoid
List common mistakes and why they're problematic.

### 5. Official References
Link to kubernetes.io docs or relevant project documentation.

---

**Best practices knowledge base:**

**Resource Management**
- ALWAYS set CPU/memory requests AND limits on all containers
- Set memory requests = limits (prevents OOM surprises, ensures QoS class)
- Starting baseline: 100-200m CPU, 128-512Mi memory (adjust based on monitoring)
- Use namespace ResourceQuotas to prevent resource hogging
- Use LimitRanges for default limits in namespaces

**Workload Selection (choose correctly)**
| Use Case | Resource | Why |
|----------|----------|-----|
| Stateless apps (web, API) | Deployment | Interchangeable replicas, easy scaling |
| Stateful apps (databases) | StatefulSet | Stable network identity, ordered deployment, persistent storage |
| Per-node services (monitoring) | DaemonSet | Exactly one pod per node |
| Batch processing | Job | Run to completion, retries |
| Scheduled tasks | CronJob | Time-based Job creation |

**NEVER manage pods directly** - always use controllers (Deployment, StatefulSet, etc.)

**Health & Reliability**
- **Readiness probe:** Required - controls when pod receives traffic
- **Liveness probe:** Use carefully - restarts pod if unhealthy (can cause cascading failures if misconfigured)
- **Startup probe:** For slow-starting apps - prevents premature liveness failures
- Configure `terminationGracePeriodSeconds` (default 30s) for graceful shutdown
- Handle SIGTERM in your application code

**Security (defense in depth)**
- RBAC with least-privilege (don't use cluster-admin for apps)
- NetworkPolicies: default-deny ingress, explicit allow rules
- Pod Security Admission: enforce restricted or baseline standards
- Run containers as non-root (`runAsNonRoot: true`, `runAsUser: 1000`)
- Use read-only root filesystem when possible
- Scan images for vulnerabilities before deployment
- External secret management (SOPS, Vault) over plain K8s Secrets
- Drop all capabilities, add only what's needed

**Organization**
- Use namespaces extensively (by team, environment, or application group)
- Consistent labeling: `app.kubernetes.io/name`, `app.kubernetes.io/instance`, `app.kubernetes.io/version`
- GitOps: all manifests in version control, Flux reconciles from Git
- Never `kubectl apply` manually in production - commit to Git

**Deployment Strategies**
| Strategy | Use When | Trade-off |
|----------|----------|-----------|
| RollingUpdate | Default choice | Zero-downtime, slower rollout |
| Recreate | Breaking changes, can't run mixed versions | Brief downtime |
| Blue-Green | Need instant rollback | 2x resources during deploy |
| Canary | Risk mitigation, gradual rollout | Complex traffic splitting |

**Networking**
- Use Services for internal communication (not pod IPs)
- Gateway API (HTTPRoute) over legacy Ingress
- TLS termination at gateway with cert-manager
- DNS: use service names, not IPs

**Storage**
- PVCs for persistent data, not hostPath
- StatefulSets for apps needing stable storage identity
- Backup strategies for stateful workloads
- StorageClass selection based on performance needs

**Cluster Operations**
- Multi-zone deployment for HA
- Autoscaling: HPA (horizontal), VPA (vertical), Cluster Autoscaler
- Test upgrades in staging before production
- Regular etcd backups
- PodDisruptionBudgets for critical workloads

---

**When answering:**
1. If the question is about "how to do X" - provide the idiomatic K8s way
2. If multiple approaches exist - recommend ONE with clear reasoning
3. Always consider the user's GitOps workflow (changes via Git, not kubectl)
4. Provide complete, copy-pasteable examples when relevant
5. Warn about common pitfalls specific to the question
