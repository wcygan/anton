---
description: Perform comprehensive read-only health check on the Talos Kubernetes cluster
---

Run a comprehensive health check on the cluster using only read-only commands.

**Health check categories:**

1. **Node Health**
   - `kubectl get nodes -o wide` - Node status, versions, IPs
   - `kubectl top nodes` - Resource utilization (if metrics available)

2. **Pod Health**
   - `kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded` - Find unhealthy pods
   - `kubectl get pods -A | grep -E "CrashLoopBackOff|Error|ImagePullBackOff|Pending"` - Problem pods

3. **Flux GitOps Status**
   - `kubectl get kustomizations -A` - Kustomization sync status
   - `kubectl get helmreleases -A` - HelmRelease status
   - `kubectl get gitrepositories -A` - Git source status

4. **Storage Health**
   - `kubectl get pvc -A` - PVC binding status
   - `kubectl get cephclusters -A` - Ceph cluster health (if applicable)

5. **Networking**
   - `kubectl get gateways -A` - Gateway status
   - `kubectl get httproutes -A` - HTTPRoute status
   - `kubectl get certificates -A` - Certificate validity

6. **Recent Events**
   - `kubectl get events -A --sort-by='.lastTimestamp' | grep -i "warning\|error\|failed" | tail -20` - Recent warnings

**Output format:**

Organize findings into:
- **Healthy**: Components operating normally (brief summary)
- **Issues Found**: Problems requiring attention (with details and severity)
- **Recommendations**: Suggested actions for any issues

**Constraints:**
- Use ONLY read-only commands (get, describe, top, logs --tail)
- Never use apply, delete, patch, edit, or any mutating operations
- Run checks in parallel where possible for efficiency
- Keep output concise - focus on problems, not verbose healthy status
