---
description: Analyze cluster state and recommend 1-3 high-impact improvements
---

Analyze the current state of the Talos Kubernetes cluster and provide 1-3 actionable recommendations for improvement.

**Analysis phase (read-only):**

Run these diagnostic commands in parallel to gather cluster state:

1. **Resource utilization**
   - `kubectl top nodes` - Node CPU/memory usage
   - `kubectl top pods -A --sort-by=memory | head -20` - Top memory consumers

2. **Configuration health**
   - `kubectl get helmreleases -A -o wide` - HelmRelease versions and status
   - `kubectl get kustomizations -A` - GitOps sync status

3. **Storage state**
   - `kubectl get pvc -A` - PVC sizes and utilization patterns
   - `kubectl get cephclusters -A -o jsonpath='{.items[*].status.ceph.health}'` - Ceph health

4. **Workload patterns**
   - `kubectl get pods -A -o wide` - Pod distribution across nodes
   - `kubectl get hpa -A` - Autoscaling configurations

5. **Security posture**
   - `kubectl get certificates -A` - Certificate expiration
   - `kubectl get networkpolicies -A` - Network policy coverage

6. **Recent issues**
   - `kubectl get events -A --sort-by='.lastTimestamp' | tail -30` - Recent events

**Recommendation categories to consider:**

- **Reliability**: HA configurations, backup strategies, resource limits
- **Performance**: Resource optimization, caching, scaling policies
- **Security**: Network policies, RBAC, secret management, certificate rotation
- **Cost efficiency**: Right-sizing, unused resources, storage optimization
- **Observability**: Monitoring gaps, alerting rules, logging retention
- **Maintainability**: Version updates, deprecated APIs, configuration drift

**Output format:**

For each recommendation (1-3 total, prioritized by impact):

### Recommendation N: [Title]

**Current state:** What you observed that prompted this recommendation

**Why it matters:** Business/operational impact if not addressed

**Recommendation:** Specific improvement to make

**Next steps:**
1. First action (specific command or file to modify)
2. Second action
3. Verification step

**Effort:** Low / Medium / High

**Risk:** What could go wrong and how to mitigate

---

**Constraints:**
- Limit to 1-3 recommendations (quality over quantity)
- Focus on high-impact, actionable items
- Reference specific files in `kubernetes/apps/` when suggesting changes
- Align with patterns in CLAUDE.md and project conventions
- Do NOT make changes - only recommend
