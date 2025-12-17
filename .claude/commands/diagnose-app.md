---
description: Troubleshoot a failing or unhealthy application in the cluster
---

Help diagnose issues with a Kubernetes application. The user will specify which app/namespace to investigate.

**Information gathering (run in parallel):**

1. **Pod status and events:**
   ```bash
   kubectl get pods -n {namespace} -l app.kubernetes.io/name={app}
   kubectl describe pods -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get events -n {namespace} --sort-by='.lastTimestamp' | tail -20
   ```

2. **Logs (recent and previous if crashed):**
   ```bash
   kubectl logs -n {namespace} -l app.kubernetes.io/name={app} --tail=100
   kubectl logs -n {namespace} -l app.kubernetes.io/name={app} --previous --tail=50
   ```

3. **Flux/GitOps status:**
   ```bash
   kubectl get kustomization -n {namespace} {app} -o wide
   kubectl get helmrelease -n {namespace} {app} -o wide
   kubectl describe helmrelease -n {namespace} {app}
   ```

4. **Service and networking:**
   ```bash
   kubectl get svc -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get httproute -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get endpoints -n {namespace}
   ```

5. **Resource status:**
   ```bash
   kubectl top pod -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get pvc -n {namespace}
   ```

**Analysis checklist:**

- [ ] **Pods running?** Check STATUS column, restart count
- [ ] **Resources OK?** OOMKilled, CPU throttling, pending due to resources
- [ ] **Image pull?** ImagePullBackOff, wrong tag, registry auth
- [ ] **Config/Secrets?** Missing ConfigMaps, Secrets not found
- [ ] **Storage?** PVC pending, mount failures
- [ ] **Probes failing?** Readiness/liveness probe errors
- [ ] **Network?** Service selector mismatch, port misconfig
- [ ] **HelmRelease?** Upgrade failed, values error, chart not found
- [ ] **Dependencies?** Database not ready, upstream service down

**Common issues and fixes:**

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `CrashLoopBackOff` | App error, bad config | Check logs, verify env vars |
| `ImagePullBackOff` | Wrong image/tag, no auth | Verify image exists, check registry secret |
| `Pending` | No resources, no nodes | Check node capacity, resource requests |
| `OOMKilled` | Memory limit too low | Increase memory limit in HelmRelease |
| HelmRelease `False` | Chart error, bad values | `kubectl describe hr`, check values syntax |
| Probe warnings | Wrong path/port | Verify health endpoint, check app logs |

**Output format:**

1. **Status summary:** One-line health assessment
2. **Root cause:** What's actually wrong
3. **Evidence:** Relevant log lines, events, or status
4. **Fix:** Specific steps to resolve
5. **Prevention:** How to avoid this in future

**If unclear, ask:**
- Which namespace and app name?
- When did it start failing?
- Any recent changes (deployments, config updates)?
