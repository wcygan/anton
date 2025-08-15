# Secrets Management Documentation

This directory contains comprehensive documentation for secret management in the homelab Kubernetes cluster, focusing on the migration from plaintext and SOPS-encrypted secrets to 1Password + External Secrets Operator.

## Overview

The homelab cluster uses a hybrid approach to secret management with a clear migration path toward centralized 1Password integration:

### Primary Strategy: 1Password + External Secrets Operator

- **Modern Integration**: ExternalSecret resources automatically sync from 1Password vaults
- **Centralized Management**: All application secrets stored in 1Password for better security
- **Automatic Rotation**: Secrets update automatically when changed in 1Password
- **Audit Trail**: Complete access logging through 1Password's audit system

### Legacy Strategy: SOPS Encryption

- **Bootstrap Secrets**: System-level credentials that enable the cluster (AGE keys, Flux webhook)
- **High-Security Tokens**: Cloudflare tunnel tokens and other infrastructure access credentials
- **Git-Stored**: Encrypted at rest in the repository using AGE encryption

## Quick Reference

### Common Operations

```bash
# Check 1Password Connect health
kubectl get clustersecretstore onepassword-connect

# View ExternalSecret status across cluster
kubectl get externalsecret -A

# Force secret refresh
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite

# Decrypt SOPS secret for migration
sops -d kubernetes/path/to/secret.sops.yaml
```

### Setup Commands

```bash
# Install/reinstall 1Password Connect
./scripts/setup-1password-connect.ts

# Create test secret for validation
# See test-secret.md for detailed steps

# Migrate plaintext secret
# See 1password-connect-setup.md for migration patterns
```

## Documentation Files

### [1password-connect-setup.md](./1password-connect-setup.md)
Complete setup guide for 1Password Connect with External Secrets Operator including:
- Architecture overview and authentication flow
- Step-by-step deployment instructions
- Common patterns for ExternalSecret resources
- Troubleshooting guide and debugging commands
- Migration strategies from other secret solutions

### [test-secret.md](./test-secret.md)  
Step-by-step validation guide for testing 1Password integration:
- Prerequisites verification
- Creating test items in 1Password
- Deploying test ExternalSecret resources
- Validation commands and success criteria
- Troubleshooting common setup issues

### [1password-connect-base64-bug.md](./1password-connect-base64-bug.md)
Comprehensive documentation of a resolved installation issue:
- **Status**: RESOLVED via fresh installation (June 11, 2025)
- Root cause analysis: Installation state corruption
- Resolution process: Complete uninstall/reinstall cycle
- Prevention: Use setup script for reliable deployment
- Historical reference for troubleshooting similar issues

## Migration Status

### ✅ Successfully Migrated to 1Password

| Secret | Source | 1Password Item | Status |
|--------|--------|----------------|---------|
| Loki S3 Credentials | Plaintext YAML | `loki-s3-credentials` | ✅ Production |
| Test Database | Plaintext YAML | `test-postgres-credentials` | ✅ Production |
| Cert-Manager Token | SOPS Encrypted | `cloudflare-api-credentials` | ✅ Production |
| External-DNS Token | SOPS Encrypted | `cloudflare-api-credentials` | ✅ Production |
| Cluster Domain | SOPS Encrypted | `cluster-config` | ✅ Production |

### 🔐 Retained as SOPS (Recommended)

| Secret | Type | Reasoning |
|--------|------|-----------|
| AGE Encryption Key | Bootstrap | Required for SOPS operation |
| Flux Webhook Secret | Bootstrap | System-level GitOps credentials |
| Cloudflared Tunnel Token | Infrastructure | High-security tunnel access |

## Architecture

### Secret Flow Diagram

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   1Password     │    │ External Secrets │    │   Kubernetes    │
│     Vault       │    │    Operator      │    │    Secrets      │
│                 │◄───┤                  │◄───┤                 │
│ • Application   │    │ • ClusterSecret  │    │ • Auto-generated│
│   Credentials   │    │   Store          │    │ • Base64 encoded│
│ • API Keys      │    │ • ExternalSecret │    │ • Pod-consumable│
│ • Passwords     │    │   Resources      │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  1Password       │
                       │  Connect Server  │
                       │                  │
                       │ • REST API       │
                       │ • Authentication │
                       │ • Vault Access   │
                       └──────────────────┘
```

### Component Responsibilities

**1Password Vault (`anton`)**:
- Centralized secret storage
- Access control and audit logging  
- Secret versioning and rotation

**1Password Connect**:
- Kubernetes-deployed bridge service
- REST API for External Secrets Operator
- Secure vault authentication

**External Secrets Operator**:
- Watches ExternalSecret resources
- Polls 1Password Connect for changes
- Creates/updates Kubernetes secrets automatically

**ExternalSecret Resources**:
- Declarative secret mapping configuration
- Defines which 1Password items to sync
- Specifies field mappings and refresh intervals

## Security Considerations

### 1Password Integration Benefits

1. **Centralized Access Control**: RBAC through 1Password teams and vaults
2. **Audit Logging**: Complete access trails for all secret operations  
3. **Secure Transit**: TLS-encrypted communication between all components
4. **Credential Isolation**: 1Password Connect only accesses designated vaults
5. **Automatic Rotation**: Updates propagate automatically without manual intervention

### SOPS Retention Rationale

1. **Bootstrap Independence**: AGE keys must exist before External Secrets can operate
2. **Cluster Recovery**: Critical for disaster recovery and initial deployment
3. **Air-Gapped Capability**: SOPS works without external dependencies
4. **Infrastructure Tokens**: Some credentials are too sensitive for automated systems

### Best Practices

1. **Use Least Privilege**: Grant minimal vault access to 1Password Connect
2. **Monitor Secret Access**: Review 1Password audit logs regularly
3. **Implement Secret Rotation**: Update secrets in 1Password, let ESO sync automatically
4. **Test Recovery Procedures**: Validate that SOPS-encrypted bootstrap secrets work
5. **Secure the Setup Script**: Protect `1password-credentials.json` and access tokens

## Troubleshooting Quick Reference

### Common Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| ClusterSecretStore not Ready | 1Password Connect connectivity | Check Connect pod logs |
| ExternalSecret SecretSyncedError | Item/field not found | Verify 1Password item names |
| "illegal base64 data" errors | Installation state corruption | Complete reinstall via setup script |
| Secret not updating | Refresh interval too long | Force refresh with annotation |

### Key Debugging Commands

```bash
# Check overall health
kubectl get clustersecretstore,externalsecret -A

# View detailed status
kubectl describe clustersecretstore onepassword-connect
kubectl describe externalsecret <name> -n <namespace>

# Check logs
kubectl logs -n external-secrets deployment/onepassword-connect
kubectl logs -n external-secrets deployment/external-secrets

# Force resync
kubectl annotate externalsecret <name> -n <namespace> \
  force-sync=$(date +%s) --overwrite
```

## Related Documentation

- **Setup Scripts**: `/scripts/setup-1password-connect.ts`
- **Configuration**: `/kubernetes/apps/external-secrets/`
- **Examples**: `/kubernetes/apps/*/app/externalsecret.yaml`
- **Project Guidelines**: `/CLAUDE.md` (Secrets Management section)

## Next Steps

1. **Monitor Production Performance**: Track secret sync latency and reliability
2. **Implement Secret Rotation**: Establish regular rotation schedules in 1Password
3. **Expand Coverage**: Identify additional plaintext secrets for migration
4. **Documentation Maintenance**: Update guides as 1Password Connect evolves
5. **Backup Strategy**: Ensure SOPS bootstrap secrets have proper backup procedures

---

**Last Updated**: June 11, 2025  
**Migration Status**: Complete for identified plaintext secrets  
**Next Review**: Monitor performance and identify additional migration candidates