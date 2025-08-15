# Trino HTTP 406 X-Forwarded-For Header Fix

## TLDR

**Problem**: Trino web UI showed "HTTP ERROR 406 Server configuration does not allow processing of the X-Forwarded-For header" when accessed through Tailscale ingress.

**Root Cause**: Trino rejects X-Forwarded-* headers by default as a security feature. Tailscale ingress automatically adds these headers for proxy identification.

**Solution**: Enable `http-server.process-forwarded=true` in Trino configuration to allow processing of forwarded headers from trusted proxies.

**Quick Fix**: Direct ConfigMap patch + pod restart (immediate resolution)
**Permanent Fix**: Update Helm chart configuration for GitOps compliance

---

## Problem Description

### Symptoms
- HTTP 406 error when accessing Trino web UI at `https://trino.walleye-monster.ts.net`
- Error message: "Server configuration does not allow processing of the X-Forwarded-For header"
- Stack trace showing `RejectForwardedRequestCustomizer.customize()` rejection

### Environment
- **Platform**: Kubernetes cluster with Talos Linux
- **Ingress**: Tailscale Kubernetes Operator with ingress class `tailscale`
- **Deployment**: Trino Helm chart v1.39.1 deployed via Flux GitOps
- **Network Path**: Client → Tailscale → Trino Coordinator Pod

### Security Context
This is a **security feature** introduced in Trino to prevent:
- IP address spoofing attacks
- Authentication bypass via header manipulation
- Compliance violations in corporate environments

## Debugging Analysis

### Investigation Timeline

#### 1. Initial Problem Identification
```bash
# Symptom observed
curl -I https://trino.walleye-monster.ts.net
# HTTP/1.1 406 Not Acceptable
```

**Key Insight**: Error occurs only through Tailscale ingress, not in direct pod access.

#### 2. Network Path Analysis
```bash
# Direct pod access (works)
kubectl exec -n data-platform trino-coordinator-xxx -- trino --execute "SELECT 1"
# ✅ Success

# Tailscale ingress path (fails)
# Browser → Tailscale → Trino Pod = 406 error
```

**Key Insight**: Problem is specific to proxy/ingress layer, not Trino itself.

#### 3. Header Investigation
Tailscale ingress automatically injects headers:
- `X-Forwarded-For`: Client IP identification
- `X-Forwarded-Proto`: Protocol (HTTPS)
- `X-Forwarded-Host`: Original hostname

**Key Insight**: Trino's security model rejects these headers by default.

#### 4. Configuration Research
From official Trino documentation and GitHub issues:
- Issue #6552: "Reject X-Forwarded-* headers by default"
- Issue #22865: "Reject X-Forwarded-* headers behaviour breaks requests"
- Solution: `http-server.process-forwarded=true` configuration property

#### 5. Helm Chart Configuration Challenges

**First Attempt**: `additionalConfigProperties` as object
```yaml
additionalConfigProperties:
  http-server.process-forwarded: "true"  # ❌ Object format
```
**Result**: Failed - Helm chart expects array format

**Second Attempt**: `additionalConfigProperties` as array with wrong indentation
```yaml
additionalConfigProperties:
  - http-server.process-forwarded=true  # ❌ Wrong indentation
```
**Result**: Failed - YAML parsed as object due to indentation

**Third Attempt**: `coordinatorExtraConfig`
```yaml
coordinator:
  extraConfig: |
    http-server.process-forwarded=true  # ❌ Wrong field name
```
**Result**: Failed - Field doesn't exist in chart

**Analysis Tools Used**:
```bash
# Check actual deployed values
kubectl get helmrelease trino -n data-platform -o yaml

# Examine generated ConfigMap
kubectl get configmap trino-coordinator -n data-platform -o yaml

# Monitor pod crashes
kubectl describe pod trino-coordinator-xxx -n data-platform
```

#### 6. Root Cause Discovery

**Critical Finding**: Even with correct YAML syntax, Flux was parsing `additionalConfigProperties` as an object instead of an array:

```json
// What Flux deployed (wrong)
"additionalConfigProperties": {
    "http-server.process-forwarded": "true"
}

// What chart expects (correct)
"additionalConfigProperties": [
    "http-server.process-forwarded=true"
]
```

**Evidence**: ConfigMap showed just `true` at end of config.properties instead of full property name.

#### 7. Configuration Parsing Analysis

**Helm Chart Template Behavior**:
1. Chart expects array of strings: `["key=value", "key2=value2"]`
2. Template processes each array item as a property line
3. When object provided, template extracts only the value (`"true"`)
4. Result: Invalid property line breaks Trino startup

**Pod Crash Pattern**:
```
ERROR: Configuration property 'true' was not used
```

This confirmed the template parsing issue.

## Solution Implementation

### Phase 1: Immediate Fix (ConfigMap Patch)

**Approach**: Direct Kubernetes resource modification for immediate resolution.

```bash
# 1. Suspend failing HelmRelease
flux suspend hr trino -n data-platform

# 2. Patch ConfigMap directly
kubectl patch configmap trino-coordinator -n data-platform --type='merge' \
  -p='{"data":{"config.properties":"coordinator=true\nnode-scheduler.include-coordinator=false\nhttp-server.http.port=8080\nquery.max-memory=4GB\nquery.max-memory-per-node=1GB\ndiscovery.uri=http://localhost:8080\nhttp-server.process-forwarded=true\n"}}'

# 3. Restart coordinator pod
kubectl delete pod trino-coordinator-xxx -n data-platform

# 4. Verify fix
curl -I https://trino.walleye-monster.ts.net
# HTTP/1.1 200 OK ✅
```

**Result**: Immediate resolution of HTTP 406 error.

**Trade-offs**:
- ✅ **Pros**: Instant fix, no GitOps complications
- ⚠️ **Cons**: Manual change outside GitOps, will be overwritten on next Helm upgrade

### Phase 2: Permanent GitOps Solution (Planned)

**Research Required**: Find correct Helm chart configuration method:

**Option A**: Fix YAML parsing issue
```yaml
# Ensure proper list format
additionalConfigProperties:
- "http-server.process-forwarded=true"  # Quoted string
```

**Option B**: Alternative configuration method
```yaml
# Use coordinator-specific config files
coordinator:
  additionalConfigFiles:
    config.properties: |
      http-server.process-forwarded=true
```

**Option C**: Server-level configuration
```yaml
# If chart supports server-wide properties
server:
  config:
    http-server.process-forwarded: true
```

## Security Considerations

### Risk Assessment

**Enabling `http-server.process-forwarded=true`**:

**Security Implications**:
1. **Header Trust**: Trino will trust X-Forwarded-* headers from proxies
2. **IP Spoofing Risk**: Malicious clients could forge X-Forwarded-For headers
3. **Authentication Impact**: Affects IP-based access controls and logging

**Mitigation Strategies**:
1. **Network Isolation**: Ensure only Tailscale can reach Trino pods
2. **Kubernetes NetworkPolicies**: Restrict ingress traffic sources
3. **Tailscale Security**: Leverage Tailscale's built-in authentication and encryption
4. **Monitoring**: Monitor for suspicious X-Forwarded-For values in logs

### Trust Boundary Analysis

```
[Client] → [Tailscale Network] → [Tailscale Operator] → [Trino Pod]
         ✅ Authenticated      ✅ Trusted Proxy     ✅ Secured
```

**Justified Trust**: Tailscale provides authenticated network access with automatic header injection for legitimate proxy identification.

## Verification Steps

### 1. Web UI Access Test
```bash
# Test web interface
open https://trino.walleye-monster.ts.net
# Should load Trino web UI without 406 error
```

### 2. Functionality Test
```sql
-- Test basic query execution
SELECT 1 as test;

-- Test catalog access
SHOW CATALOGS;

-- Test TPCH benchmark data
SELECT COUNT(*) FROM tpch.tiny.nation;
```

### 3. Header Processing Verification
```bash
# Check Trino logs for header processing
kubectl logs -n data-platform trino-coordinator-xxx | grep -i "forwarded"
# Should show no rejection errors
```

### 4. Security Audit
```bash
# Verify network policies
kubectl get networkpolicies -n data-platform

# Check Tailscale ingress status
kubectl get ingress trino -n data-platform
```

## Long-term Maintenance

### GitOps Integration Plan

1. **Research Phase**: Determine correct Helm chart configuration syntax
2. **Testing Phase**: Validate configuration in development environment
3. **Implementation Phase**: Update HelmRelease with proper GitOps configuration
4. **Monitoring Phase**: Ensure future deployments maintain the fix

### Documentation Updates

- Update CLAUDE.md with Trino configuration patterns
- Document Tailscale ingress requirements for backend services
- Add troubleshooting guide for similar proxy header issues

## References

### Trino Documentation
- [HTTP Server Properties](https://trino.io/docs/current/admin/properties-http-server.html)
- [TLS and HTTPS Configuration](https://trino.io/docs/current/security/tls.html)

### GitHub Issues
- [Issue #6552: Reject X-Forwarded-* headers by default](https://github.com/trinodb/trino/issues/6552)
- [Issue #22865: Reject X-Forwarded-* headers behaviour breaks requests](https://github.com/trinodb/trino/issues/22865)

### Helm Chart Documentation
- [Trino Helm Chart README](https://github.com/trinodb/charts/blob/main/charts/trino/README.md)
- [Trino Helm Chart Values](https://github.com/trinodb/charts/blob/main/charts/trino/values.yaml)

### Tailscale Documentation
- [Kubernetes Operator Cluster Ingress](https://tailscale.com/kb/1439/kubernetes-operator-cluster-ingress)

## Lessons Learned

1. **Security Features Can Break Proxied Deployments**: Modern applications often reject proxy headers by default for security
2. **Helm Chart Syntax Matters**: YAML indentation and data types must match chart expectations exactly
3. **GitOps vs. Emergency Fixes**: Sometimes manual intervention is needed for immediate resolution
4. **Documentation Research is Critical**: Official documentation and GitHub issues provide authoritative solutions
5. **Incremental Debugging**: Systematic analysis of network path, configuration, and deployment pipeline leads to root cause

## Related Issues

- **Similar Pattern**: Any service behind Tailscale ingress that rejects forwarded headers
- **Other Proxies**: NGINX, Traefik, Envoy may require similar configuration
- **Authentication Services**: Services with IP-based restrictions may need proxy header trust