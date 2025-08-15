# 1Password Connect Base64 Encoding Issue

## Overview

**Status**: RESOLVED - Installation State Issue (June 11, 2025)  
**Root Cause**: Corrupted installation state, not software bug  
**Resolution**: Fresh reinstall using setup script  
**Impact**: Previously prevented External Secrets Operator from retrieving secrets from 1Password  
**Severity**: Was High - Now resolved through proper installation procedure

## Problem Description

1Password Connect experiences a base64 encoding issue when processing the `1password-credentials.json` file, resulting in the following error:

```
(E) Server: (unable to get credentials and initialize API, retrying in 30s), 
Wrapped: (failed to FindCredentialsUniqueKey), 
failed to loadCredentialsFile: Server: (LoadLocalAuthV2 failed to credentialsDataFromBase64), 
illegal base64 data at input byte 0
```

### Symptoms

- External Secrets Operator reports: `ClusterSecretStore "onepassword-connect" is not ready`
- 1Password Connect sync container logs show "illegal base64 data" errors
- ExternalSecret resources remain in `SecretSyncedError` state
- Status 500 errors when External Secrets attempts to validate the store

## Technical Details

### Affected Components

- **1Password Connect Sync Container**: Primary failure point
- **External Secrets Operator**: Cannot validate ClusterSecretStore
- **ExternalSecret Resources**: Cannot retrieve secrets from 1Password

### Error Manifestation

The error occurs in the `connect-sync` container during the credential bootstrap process:

```bash
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync
```

Expected output showing the error:
```json
{
  "log_message": "(E) Server: (unable to get credentials and initialize API, retrying in 30s), Wrapped: (failed to FindCredentialsUniqueKey), failed to loadCredentialsFile: Server: (LoadLocalAuthV2 failed to credentialsDataFromBase64), illegal base64 data at input byte 0",
  "timestamp": "2025-06-11T04:35:51.161090939Z",
  "level": 1
}
```

### Version Information

**Current Deployment** (as of June 2025):
- **Connect Version**: 1.7.3 (latest available)
- **Chart Version**: 1.17.0
- **Release Date**: July 2, 2024
- **Docker Images**:
  - `1password/connect-api:1.7.3`
  - `1password/connect-sync:1.7.3`

**Verified Affected Versions**:
- 1.7.3 (confirmed)
- 1.7.x series (reported by community)

## Root Cause Analysis

### Final Resolution (June 11, 2025)

**BREAKTHROUGH**: Issue was resolved through complete reinstall using the setup script.

### Investigation Findings

1. **Not a software bug**: 1Password Connect v1.7.3 works correctly when properly installed
2. **Installation state corruption**: Previous installation had corrupted credential mounting/authentication state
3. **Fresh install successful**: Complete uninstall and reinstall resolved all issues
4. **Validated functionality**: Both test database and Loki S3 credentials work perfectly after reinstall

### What Caused the Corruption

Likely causes of the corrupted installation state:
- **Pod restart cycles** during initial setup that corrupted authentication flow
- **Stale credential mounting** from previous installation attempts
- **Cached authentication failures** that persisted across pod restarts
- **Incomplete cleanup** from previous configuration changes

### Community Reports

- Multiple users report identical symptoms in Kubernetes environments
- Some users report success with "double base64 encoding" workarounds
- **Key insight**: Most users likely need fresh installation, not workarounds
- Issue appears specific to installation state, not software functionality

## Attempted Solutions

### ✅ SUCCESSFUL RESOLUTION

**Complete Reinstall**: Using the setup script to completely uninstall and reinstall
```bash
# Uninstall completely
./scripts/setup-1password-connect.ts --uninstall

# Fresh installation
./scripts/setup-1password-connect.ts
```
**Result**: ✅ **COMPLETE SUCCESS** - All functionality restored

### ✅ Validation Tests Post-Resolution

1. **ClusterSecretStore Ready**: Status shows `Ready: True` and `store validated`
2. **ExternalSecret Success**: Test database credentials retrieved successfully
3. **Multi-Item Success**: Both Loki S3 and database credentials work perfectly
4. **Secret Creation**: Kubernetes secrets properly created with correct data

### ❌ Previously Failed Workarounds (Before Root Cause Discovery)

1. **Pod Restart**: Deleting and recreating Connect pods
   ```bash
   kubectl delete pod -l app=onepassword-connect -n external-secrets
   ```
   **Result**: Error persisted (state corruption remained)

2. **Secret Recreation**: Recreating the credentials secret from original file
   ```bash
   kubectl delete secret onepassword-connect-secret -n external-secrets
   kubectl create secret generic onepassword-connect-secret \
     --from-file=1password-credentials.json=/path/to/original-file \
     -n external-secrets
   ```
   **Result**: Error persisted (Helm-managed secret state issues)

3. **Double Base64 Encoding**: Attempted community-reported workaround
   **Result**: Kubernetes rejects the malformed secret

4. **Version Downgrade**: No reliable older versions without security issues

## Impact Assessment

### ✅ Resolution Impact (June 11, 2025)

- **1Password Integration Restored**: Full functionality with External Secrets
- **Migration Unblocked**: Can now proceed with migrating plaintext secrets to 1Password
- **Validation Complete**: Both test cases (database and Loki S3) working perfectly
- **Setup Script Proven**: The uninstall/reinstall process is reliable and effective

### Previous Impact (Before Resolution)

- **1Password Integration Blocked**: Could not use 1Password as secret source
- **External Secrets Limited**: Had to use alternative secret management
- **Migration Blocked**: Could not migrate plaintext secrets to 1Password

### Current Migration Strategy

**Recommended Approach** (Post-Resolution):
1. **Proceed with 1Password migration**: Primary secret management solution
2. **Complete plaintext secret audit**: Identify all secrets needing migration
3. **Migrate systematically**: Start with test/dev, then production secrets
4. **Deprecate SOPS**: Transition to 1Password for new secret management

## Monitoring & Detection

### Health Check Commands

Check ClusterSecretStore status:
```bash
kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[0].message}'
```

Monitor Connect logs for errors:
```bash
kubectl logs -n external-secrets deployment/onepassword-connect -c connect-sync --tail=20
```

Verify ExternalSecret status:
```bash
kubectl get externalsecret -A
```

### Status Indicators

**Healthy State**:
- ClusterSecretStore status: `Ready: True`
- Connect logs: No base64 errors
- ExternalSecrets: `Ready: True`

**Bug Present**:
- ClusterSecretStore status: `ValidationFailed` with "status 500" message
- Connect logs: "illegal base64 data at input byte 0" errors
- ExternalSecrets: `SecretSyncedError` state

## Resolution Process (For Future Reference)

### Troubleshooting Steps for Similar Issues

If experiencing similar base64 encoding errors with 1Password Connect:

1. **First: Try Complete Reinstall**
   ```bash
   # Step 1: Complete uninstall
   ./scripts/setup-1password-connect.ts --uninstall
   
   # Step 2: Verify cleanup
   kubectl get pods -n external-secrets
   kubectl get clustersecretstore onepassword-connect
   
   # Step 3: Fresh installation
   ./scripts/setup-1password-connect.ts
   
   # Step 4: Verify success
   kubectl get clustersecretstore onepassword-connect
   ```

2. **If Reinstall Fails**: Check prerequisites
   - Ensure original `1password-credentials.json` and token files exist
   - Verify Kubernetes cluster connectivity
   - Confirm External Secrets Operator is running

3. **Validation Test**: Create a simple ExternalSecret to test functionality
   ```bash
   # Create test ExternalSecret (modify for your vault items)
   kubectl apply -f - <<EOF
   apiVersion: external-secrets.io/v1
   kind: ExternalSecret
   metadata:
     name: test-connection
     namespace: default
   spec:
     refreshInterval: 1h
     secretStoreRef:
       name: onepassword-connect
       kind: ClusterSecretStore
     target:
       name: test-connection
       creationPolicy: Owner
     data:
       - secretKey: test-field
         remoteRef:
           key: your-test-item
           property: your-test-property
   EOF
   ```

### Recommended Actions

### ✅ Current State (Post-Resolution)

1. **Complete Secret Migration**: Proceed with 1Password as primary source
2. **Migrate Plaintext Secrets**: Systematically move secrets to 1Password
3. **Update Documentation**: Reflect that 1Password integration is working
4. **Monitor Installation Health**: Use setup script for any future reinstalls

### For Community

1. **Share Resolution**: Document that fresh reinstall resolves base64 issues
2. **Recommend Setup Script**: Use proper installation tools, not manual setup
3. **Installation State Awareness**: Recognize when installation state is corrupted

## References

- **Setup Script**: `/scripts/setup-1password-connect.ts`
- **Current Configuration**: `/kubernetes/apps/external-secrets/onepassword-connect/`
- **Test Secret Example**: `/docs/secrets/test-secret.md`
- **External Secrets Documentation**: https://external-secrets.io/

## Related Issues

- Community reports of similar "LoadLocalAuthV2" failures
- External Secrets GitHub issues mentioning 1Password base64 errors
- **Resolution applies to**: Users experiencing installation state corruption
- **Key insight**: Most community workarounds unnecessary with proper reinstall

## Success Metrics (Post-Resolution)

### Validation Results

1. **ClusterSecretStore**: `Ready: True`, `Status: Valid`, `Capabilities: ReadOnly`
2. **Test Database ExternalSecret**: `Status: SecretSynced`, `Ready: True`
3. **Loki S3 ExternalSecret**: `Status: SecretSynced`, `Ready: True`
4. **Secret Data**: Correctly retrieved and base64 encoded in Kubernetes secrets

### Performance

- **Installation Time**: ~2 minutes for complete uninstall/reinstall
- **Sync Performance**: ExternalSecrets sync within 5-10 seconds
- **Reliability**: No further base64 errors observed post-reinstall

---

**Last Updated**: June 11, 2025  
**Status**: RESOLVED via fresh installation  
**Next Review**: Monitor for any installation state regression