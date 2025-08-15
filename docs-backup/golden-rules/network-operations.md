# Network Operations Golden Rules

## The Golden Rule

**Never modify production ingress without testing the configuration first.** A single typo in an ingress rule can take down all external access to your cluster.

## Critical Rules

### 1. Never Delete Ingress Controllers Without Analysis

**WRONG:**
```bash
kubectl delete deployment nginx-controller -n network
```

**RIGHT:**
```bash
# First, check what's using the ingress
kubectl get ingress -A | grep nginx

# Create a new ingress controller first
# Then migrate traffic
# Only then remove the old one
```

**Why:** Deleting an ingress controller immediately breaks all services using it. Always migrate traffic first.

### 2. Always Test DNS Changes in Stages

**WRONG:**
```bash
# Changing DNS for all services at once
kubectl apply -f new-dns-config.yaml
```

**RIGHT:**
```bash
# Test with a single non-critical service first
kubectl apply -f test-service-dns.yaml

# Verify resolution
nslookup test.home.arpa

# Then roll out to other services gradually
```

**Why:** DNS propagation issues can cascade. Test with non-critical services first.

### 3. Never Modify Network Policies Without Understanding Dependencies

**WRONG:**
```bash
# Applying a deny-all policy without exceptions
kubectl apply -f deny-all-network-policy.yaml
```

**RIGHT:**
```bash
# First, audit existing traffic
kubectl exec -n monitoring netshoot -- nmap -sn 10.0.0.0/16

# Document required flows
# Create policy with explicit allows
# Test in a non-production namespace first
```

**Why:** Overly restrictive network policies can break inter-service communication.

### 4. Always Verify Certificate Expiration Before Changes

**WRONG:**
```bash
# Deleting a certificate without checking expiration
kubectl delete certificate prod-cert -n network
```

**RIGHT:**
```bash
# Check certificate status first
kubectl get certificate -A
kubectl describe certificate prod-cert -n network

# If expired, trigger renewal instead
kubectl annotate certificate prod-cert -n network \
  cert-manager.io/issue-temporary-certificate="true"
```

**Why:** Deleting certificates can cause immediate TLS failures. Renewal is safer.

### 5. Never Change LoadBalancer IPs Without Notice

**WRONG:**
```bash
# Modifying LoadBalancer service directly
kubectl edit svc nginx-external -n network
# Changing spec.loadBalancerIP
```

**RIGHT:**
```bash
# Create a new LoadBalancer service
# Update DNS to point to both IPs
# Monitor traffic shift
# Remove old service after TTL expiry
```

**Why:** External clients cache IPs. Sudden changes cause connectivity loss.

## Recovery Procedures

### Ingress Controller Down

```bash
# Quick recovery - reinstall from Flux
flux suspend kustomization nginx-external
flux resume kustomization nginx-external

# If Flux is broken, apply backup
kubectl apply -f /backups/ingress-controller-backup.yaml
```

### DNS Resolution Broken

```bash
# Check CoreDNS
kubectl -n kube-system rollout restart deployment coredns

# Check k8s-gateway
kubectl -n network logs -l app.kubernetes.io/name=k8s-gateway

# Fallback to manual DNS
kubectl -n network edit configmap k8s-gateway
```

### Certificate Expired

```bash
# Force renewal
kubectl -n network delete secret prod-cert-tls
kubectl -n network delete certificaterequest -l cert-manager.io/certificate-name=prod-cert

# Monitor renewal
kubectl -n network describe certificate prod-cert
```

## Pre-Operation Checklist

- [ ] Current ingress rules documented
- [ ] DNS TTLs checked and reduced if needed
- [ ] Certificate expiration dates verified
- [ ] Network policy dependencies mapped
- [ ] Backup of current configuration taken
- [ ] Monitoring alerts acknowledged
- [ ] Change window communicated

## Incidents

### 2024-11-15: Cloudflare Tunnel Outage
- **What happened:** Deleted cloudflared deployment to "clean up"
- **Impact:** All external access lost for 2 hours
- **Root cause:** Didn't realize it was the only external ingress
- **Lesson:** Document critical path components

### 2024-12-20: Wrong Ingress Class
- **What happened:** Changed ingress class from 'internal' to 'external' on monitoring
- **Impact:** Internal monitoring exposed to internet
- **Root cause:** Misunderstood ingress class purpose
- **Lesson:** Always use 'internal' class unless explicitly required