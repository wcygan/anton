# Tailscale Troubleshooting Guide

This guide covers common issues and solutions for Tailscale in the homelab cluster.

## Tailscale Ingress Lockout

### Symptoms

- Tailscale-exposed services (Grafana, Airflow, KubeAI, etc.) are inaccessible
- Services show as "locked out" in Tailscale admin console
- Tailscale proxy pods are running but connections are blocked
- URLs like `https://grafana.walleye-monster.ts.net` don't load

### Root Causes

1. **Network Lock (Tailnet Lock)**: Tailscale's network lock feature requires device signatures
2. **ACL Policy Changes**: Access Control List updates blocking the Kubernetes operator
3. **Authentication Issues**: Expired or invalid operator credentials
4. **Device Authorization**: New devices need explicit authorization in some configurations

### Diagnosis

1. **Check Tailscale Operator Status**:
   ```bash
   kubectl get pods -n tailscale
   kubectl logs -n tailscale deployment/operator --tail=50
   ```

2. **Verify Proxy Pod Logs**:
   ```bash
   # Example for Grafana
   kubectl logs -n tailscale ts-grafana-tailscale-ingress-<pod-suffix> --tail=30
   ```

3. **Look for Network Lock Messages**:
   ```bash
   kubectl logs -n tailscale deployment/operator | grep -i "network lock"
   ```
   Common error: "Network lock is dropping peer ... due to missing signature"

4. **Check Service Connectivity**:
   ```bash
   # Verify the backend service is running
   kubectl get svc -n monitoring kube-prometheus-stack-grafana
   kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
   ```

### Resolution Steps

#### Option 1: Disable Network Lock (Quick Fix)

1. Access Tailscale Admin Console at https://login.tailscale.com/admin
2. Navigate to "Settings" → "Network lock"
3. Temporarily disable network lock
4. Wait 2-3 minutes for changes to propagate
5. Test service access

#### Option 2: Add Device Signatures (Secure Fix)

1. In Tailscale Admin Console, go to "Machines"
2. Find the Kubernetes operator devices (usually named after ingress resources)
3. Click on each device and authorize/sign it
4. Enable network lock if it was disabled

#### Option 3: Restart Tailscale Components

```bash
# Restart the operator
kubectl rollout restart deployment/operator -n tailscale

# If needed, delete and recreate proxy pods
kubectl delete pods -n tailscale -l tailscale.com/parent-resource-type=ingress

# Force reconciliation
flux reconcile hr tailscale-operator -n tailscale
```

#### Option 4: Re-authenticate Operator

```bash
# Generate new auth key from Tailscale admin console
# Then update the secret
kubectl delete secret operator-oauth -n tailscale
kubectl create secret generic operator-oauth \
  -n tailscale \
  --from-literal=client-id="<your-client-id>" \
  --from-literal=client-secret="<your-client-secret>"

# Restart operator
kubectl rollout restart deployment/operator -n tailscale
```

### Prevention

1. **Document Auth Keys**: Keep OAuth credentials documented in 1Password
2. **Monitor Expiration**: Set reminders for credential rotation
3. **ACL Testing**: Test ACL changes in staging before production
4. **Regular Health Checks**: Monitor Tailscale operator logs for early warnings

## Common Issues

### Issue: "failed to get service: Service not found"

These errors in operator logs are often harmless and occur when:
- Services are deleted but endpoints still exist
- During cluster reconciliation
- When Flux is updating resources

**Action**: Usually no action needed unless services are actually inaccessible.

### Issue: Ingress Shows No Address

**Symptoms**:
```bash
kubectl get ingress -A | grep tailscale
# Shows no ADDRESS column populated
```

**Resolution**:
1. Check if IngressClass exists: `kubectl get ingressclass tailscale`
2. Verify operator is watching ingresses: Check operator logs
3. Ensure ingress has correct annotation: `ingressClassName: tailscale`

### Issue: Certificate Errors

**Symptoms**: Browser shows certificate warnings when accessing services

**Resolution**:
1. Tailscale handles certificates automatically for `*.ts.net` domains
2. Ensure you're using the correct URL format: `https://<service>.walleye-monster.ts.net`
3. Check if MagicDNS is enabled in Tailscale settings

## Monitoring Tailscale Health

### Quick Health Check Script

Create `scripts/check-tailscale-health.ts`:

```typescript
#!/usr/bin/env -S deno run --allow-all

import { $ } from "jsr:@david/dax@0.42.0";

console.log("🔍 Checking Tailscale health...\n");

// Check operator status
console.log("📊 Operator Status:");
await $`kubectl get deployment -n tailscale operator -o wide`.printCommand();

// Check all Tailscale ingresses
console.log("\n🌐 Tailscale Ingresses:");
await $`kubectl get ingress -A -o wide | grep -E "CLASS|tailscale"`.printCommand();

// Check proxy pods
console.log("\n🔧 Proxy Pods:");
await $`kubectl get pods -n tailscale -l tailscale.com/parent-resource-type=ingress`.printCommand();

// Recent operator errors
console.log("\n⚠️  Recent Operator Errors:");
await $`kubectl logs -n tailscale deployment/operator --tail=20 | grep -i error || echo "No recent errors"`.printCommand();
```

### Integration with Monitoring Stack

Add Prometheus alerts for Tailscale health:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: tailscale-alerts
  namespace: tailscale
spec:
  groups:
    - name: tailscale
      rules:
        - alert: TailscaleOperatorDown
          expr: up{job="tailscale-operator"} == 0
          for: 5m
          annotations:
            summary: "Tailscale operator is down"
            
        - alert: TailscaleIngressNotReady
          expr: |
            kube_ingress_info{ingress_class="tailscale"} 
            unless on(namespace, ingress) 
            kube_ingress_status_condition{condition="Ready", status="true"}
          for: 10m
          annotations:
            summary: "Tailscale ingress {{ $labels.namespace }}/{{ $labels.ingress }} not ready"
```

## Related Documentation

- [Install Tailscale](./install-tailscale.md) - Initial setup guide
- [Expose Grafana](./expose-grafana.md) - Example service exposure
- [Kubernetes Operator Docs](https://tailscale.com/kb/1236/kubernetes-operator) - Official documentation
- [Network Lock Guide](https://tailscale.com/kb/1226/tailnet-lock) - Understanding Tailnet lock

## Support Resources

- **Tailscale Status**: https://status.tailscale.com/
- **Admin Console**: https://login.tailscale.com/admin
- **Community Forum**: https://forum.tailscale.com/