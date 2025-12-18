---
description: Guide for deploying workloads outside GitOps (non-Flux managed)
---

Help the user deploy and manage Kubernetes workloads that should NOT be committed to the anton GitOps repository.

**Context:**
The user's cluster has:
- Envoy Gateway with `envoy-external` (internet-facing via Cloudflare tunnel) and `envoy-internal` (cluster-internal)
- cert-manager for automatic TLS
- external-dns for automatic DNS records
- Domain: `milkyway.haus` (set `external-dns.alpha.kubernetes.io/target: external.milkyway.haus` for public access)

**When the user asks for help deploying a scratch workload:**

1. **Recommend the `scratch` namespace** for isolation from GitOps-managed resources
2. **Generate complete manifests** including:
   - Namespace (if not exists)
   - Deployment with proper resource limits and security context
   - Service
   - HTTPRoute pointing to `envoy-external` (for internet) or `envoy-internal` (for internal)

3. **Provide management commands:**
   ```bash
   # Apply manifests
   kubectl apply -f ~/scratch-workloads/

   # Check status
   kubectl -n scratch get pods,svc,httproute

   # View logs
   kubectl -n scratch logs -l app=<app-name> -f

   # Cleanup
   kubectl delete namespace scratch
   ```

**HTTPRoute template for internet exposure:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: <app-name>
  namespace: scratch
  annotations:
    external-dns.alpha.kubernetes.io/target: external.milkyway.haus
spec:
  parentRefs:
    - name: envoy-external
      namespace: network
      sectionName: https
  hostnames:
    - <app-name>.milkyway.haus
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: <app-name>
          port: 80
```

**When the user asks questions about this pattern:**

Answer questions about:
- How traffic flows (Cloudflare → tunnel → envoy-external → Service → Pod)
- When to use `envoy-external` vs `envoy-internal`
- How cert-manager and external-dns integrate automatically
- Best practices for resource limits, security contexts, health probes
- How to debug connectivity issues
- When this pattern is appropriate vs. when to use GitOps

**Key guidance:**
- Keep scratch workloads in `~/scratch-workloads/` or a separate private Git repo
- Always set resource requests/limits (prevents starving GitOps workloads)
- Use `app.kubernetes.io/managed-by: manual` label for easy identification
- Clean up promptly - scratch workloads shouldn't live indefinitely
- For anything long-lived, commit to the GitOps repo instead

**If the user provides $ARGUMENTS:**
Process their specific request - whether it's generating manifests for a particular app, answering a question about the pattern, or debugging an issue.

ARGUMENTS: $ARGUMENTS
