# 1Password Vault Structure for Homelab Recovery

This document provides the recommended 1Password vault organization for storing all critical homelab infrastructure secrets and configurations.

## 🏗️ Vault Structure

### Primary Vault: `anton` (or your homelab name)

This vault contains all operational secrets used by the cluster via External Secrets Operator.

```
anton/
├── cluster-secrets                 # Main cluster secrets (synced to all namespaces)
├── cloudflare-credentials         # API tokens and tunnel configs
├── github-credentials             # Git access and webhook tokens
├── tailscale-credentials          # OAuth keys and auth tokens
├── grafana-credentials            # Admin passwords and API keys
├── prometheus-credentials         # Authentication and API tokens
├── storage-credentials            # Ceph and backup access keys
├── monitoring-credentials         # Loki, alerts, and notification configs
├── application-secrets/           # App-specific secrets
│   ├── kubeai-api-keys
│   ├── airflow-connections
│   └── database-credentials
└── external-integrations/         # Third-party service credentials
    ├── discord-webhooks
    ├── smtp-credentials
    └── backup-service-keys
```

### Recovery Vault: `homelab-recovery`

Separate vault for disaster recovery items that are not synced to the cluster.

```
homelab-recovery/
├── encryption-keys/
│   ├── sops-age-key              # CRITICAL: age.key for SOPS decryption
│   └── ssh-deploy-keys           # github-deploy.key for GitOps
├── infrastructure-configs/
│   ├── talos-cluster-config      # talsecret.yaml and cluster configs
│   ├── cloudflare-tunnel-config  # cloudflare-tunnel.json
│   └── network-configuration     # IP ranges, DNS settings
├── 1password-connect/
│   ├── connect-credentials       # 1password-credentials.json
│   └── connect-api-token         # API token for External Secrets
├── hardware-documentation/
│   ├── node-specifications       # Hardware configs, BIOS settings
│   ├── network-topology          # Switch configs, VLAN setup
│   └── storage-layout            # Disk layouts, RAID configs
└── emergency-procedures/
    ├── disaster-recovery-steps   # Step-by-step recovery process
    ├── vendor-support-contacts   # Hardware vendor information
    └── network-provider-details  # ISP and DNS provider info
```

## 📝 Item Templates

### Template: Cluster Secrets (`cluster-secrets`)
```yaml
# Basic cluster-wide secrets synced to all namespaces
Type: Secure Note

Fields:
- database_url: postgresql://...
- redis_url: redis://...
- smtp_host: smtp.gmail.com
- smtp_port: 587
- smtp_username: alerts@yourdomain.com
- smtp_password: [app password]
- webhook_discord: https://discord.com/api/webhooks/...
- backup_s3_endpoint: https://s3.amazonaws.com
- backup_s3_access_key: AKIA...
- backup_s3_secret_key: [secret]
- backup_s3_bucket: homelab-backups

Notes:
- These secrets are automatically synced to all namespaces
- Used by multiple applications across the cluster
- Update here to update everywhere via External Secrets Operator
```

### Template: SOPS Age Key (`sops-age-key`)
```yaml
Type: Secure Note

Fields:
- private_key: AGE-SECRET-KEY-1...
- public_key: age1...
- created_date: 2025-01-15
- key_purpose: SOPS encryption for homelab cluster secrets

Files:
- age.key (attach the private key file)

Notes:
- CRITICAL: This key is required to decrypt all cluster secrets
- Without this key, cluster recovery is impossible
- Store securely and never commit to git
- Consider creating a backup copy in separate secure location
```

### Template: 1Password Connect (`connect-credentials`)
```yaml
Type: Secure Note

Fields:
- api_token: [1Password API token]
- vault_name: anton
- vault_id: 1
- connect_host: http://onepassword-connect.external-secrets.svc.cluster.local:8080

Files:
- 1password-credentials.json (Connect server credentials)

Notes:
- Used by External Secrets Operator to sync secrets
- API token requires vault read permissions
- Credentials file enables Connect server authentication
```

### Template: Cloudflare Configuration (`cloudflare-credentials`)
```yaml
Type: Secure Note

Fields:
- api_token: [Cloudflare API token]
- account_id: [Account ID]
- domain: yourdomain.com
- tunnel_id: [UUID]
- tunnel_name: kubernetes
- zone_id: [Zone ID]

Files:
- cloudflare-tunnel.json (Tunnel credentials)

Notes:
- API token needs Zone DNS Edit + Cloudflare Tunnel Read permissions
- Tunnel provides secure ingress for external services
- Used by external-dns and cloudflared
```

### Template: Talos Configuration (`talos-cluster-config`)
```yaml
Type: Secure Note

Fields:
- cluster_name: anton
- cluster_endpoint: https://192.168.1.98:6443
- schematic_id: [Image Factory schematic]
- talos_version: v1.8.0
- kubernetes_version: v1.31.0
- node_ips: 192.168.1.98,192.168.1.99,192.168.1.100

Files:
- talsecret.yaml (Bootstrap secrets)
- talosconfig (Admin kubeconfig)

Notes:
- Bootstrap secrets are required for cluster initialization
- Store machine-specific configurations
- Include any custom Talos patches or extensions
```

## 🔐 Security Guidelines

### Access Control
- **Recovery Vault**: Limit access to primary administrators only
- **Operational Vault**: Accessible by External Secrets Operator
- **Regular Rotation**: Rotate API tokens and passwords quarterly
- **Audit Trail**: Monitor 1Password access logs regularly

### Backup Strategy
- **Primary**: 1Password vaults with secure sharing
- **Secondary**: Export encrypted vault backup monthly
- **Offline**: Print critical information (age key) and store securely
- **Geographic**: Consider storing backup in different physical location

### Emergency Access
- **Multiple Admins**: Ensure at least 2 people have recovery vault access
- **Emergency Kit**: Pre-configured laptop with tools and access
- **Contact List**: Vendor support numbers and escalation procedures
- **Documentation**: Physical copies of critical recovery steps

## 🔄 Maintenance Procedures

### Weekly
- [ ] Verify External Secrets are syncing successfully
- [ ] Check 1Password Connect ClusterSecretStore status
- [ ] Review any failed secret syncs or errors

### Monthly  
- [ ] Audit vault access and sharing permissions
- [ ] Update hardware documentation if changes made
- [ ] Verify disaster recovery vault accessibility
- [ ] Test sample secret decryption with SOPS

### Quarterly
- [ ] Rotate API tokens and credentials
- [ ] Update Talos and Kubernetes version documentation
- [ ] Review and update emergency procedures
- [ ] Test full disaster recovery process in lab

### Annually
- [ ] Complete disaster recovery drill
- [ ] Review and update security access controls  
- [ ] Archive old configurations and clean up vault
- [ ] Update vendor contact information and support contracts

## 🚨 Emergency Procedures

### If 1Password is Compromised
1. **Immediate**: Revoke all API tokens stored in 1Password
2. **Secure**: Change all cluster secrets and redeploy
3. **Restore**: Use offline backup to rebuild vault structure
4. **Verify**: Ensure no unauthorized access to cluster resources

### If Age Key is Lost
1. **Critical**: Cluster secrets cannot be decrypted or modified
2. **Recovery**: Requires complete secret regeneration
3. **Process**: Manual recreation of all encrypted secrets
4. **Prevention**: Maintain secure offline backup of age key

### If Cluster is Completely Lost
1. **Hardware**: Re-image nodes with Talos using stored schematic
2. **Bootstrap**: Follow pre-bootstrap requirements document
3. **Restore**: Use 1Password secrets for complete cluster rebuild
4. **Validate**: Verify all services and data are restored correctly