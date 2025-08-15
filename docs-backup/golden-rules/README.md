# Golden Rules for Homelab Operations

This directory contains **CRITICAL** rules that must be followed to avoid catastrophic failures in the homelab cluster. These rules are born from real incidents and mistakes.

## Why These Rules Exist

Each rule documents a real incident where a seemingly simple action caused massive cluster disruption. Following these rules will prevent:
- Accidental deletion of 100+ pods
- Hours of recovery time
- Data loss
- Service outages

## Rule Categories

### 1. [Kubernetes Operations](./kubernetes-operations.md)
Critical rules for working with Kubernetes resources, especially Flux GitOps.

**Key Rules:**
- NEVER delete Flux kustomizations without analysis
- Always use suspend/resume instead of delete
- Test all changes locally first
- Understand resource ownership chains

### 2. [GitOps Best Practices](./gitops-practices.md)
Rules for maintaining GitOps workflows and preventing sync issues.

**Key Rules:**
- All changes must go through Git
- Never apply manifests directly to cluster
- Respect Flux sync intervals
- Version pin all charts and images

### 3. [Storage Operations](./storage-operations.md)
Critical rules for Rook-Ceph and persistent storage management.

**Key Rules:**
- Never delete PVCs without backup
- Monitor Ceph health before changes
- Follow capacity thresholds (50%, 70%, 80%)
- Test recovery procedures monthly

### 4. [Network Changes](./network-operations.md)
Rules for modifying ingress, DNS, and network policies safely.

**Key Rules:**
- Test ingress changes before applying
- Never delete active ingress controllers
- Verify certificate expiration first
- Stage DNS changes gradually

### 5. [Secret Management](./secret-management.md)
Rules for handling secrets, SOPS, and 1Password integration.

**Key Rules:**
- Never commit unencrypted secrets
- Use External Secrets Operator for new apps
- Rotate compromised secrets immediately
- Audit secret access regularly

### 6. [Resource Management](./resource-management.md)
Rules for CPU, memory, quotas, and pod scheduling.

**Key Rules:**
- Always set resource requests
- Never use CPU limits (causes throttling)
- Set memory limits to prevent OOM
- Use PodDisruptionBudgets for HA

### 7. [Monitoring & Observability](./monitoring-observability.md)
Rules for metrics collection, retention, and alerting.

**Key Rules:**
- Never disable monitoring to save resources
- Set retention based on available storage
- Monitor the monitoring stack itself
- Test alert routing regularly

### 8. [Backup & Disaster Recovery](./backup-disaster-recovery.md)
Rules for backup strategies and disaster recovery.

**Key Rules:**
- Test restores monthly (untested backups don't exist)
- Follow 3-2-1 backup rule
- Version infrastructure with data
- Document actual restore times

### 9. [High Availability](./high-availability.md)
Rules for building resilient, highly available services.

**Key Rules:**
- Always use pod anti-affinity for critical services
- Define PodDisruptionBudgets for all HA apps
- Never rely on single node for stateful data
- Implement proper health checks

### 10. [Component Reusability](./component-reusability.md)
Rules for building maintainable, DRY configurations.

**Key Rules:**
- Never copy-paste configurations
- Use Kustomize components for shared functionality
- Version all shared components
- Provide sensible defaults

### 11. [Self-Healing & Remediation](./self-healing-remediation.md)
Rules for automated recovery and remediation strategies.

**Key Rules:**
- Never set infinite retries without circuit breakers
- Always use exponential backoff for retries
- Monitor remediation exhaustion
- Configure comprehensive health checks

### 12. [Talos Infrastructure](./talos-infrastructure.md)
Rules specific to Talos Linux operations and maintenance.

**Key Rules:**
- Test machine configs on single node first
- Never upgrade Talos and Kubernetes simultaneously
- Always backup etcd before infrastructure changes
- Preserve customizations during upgrades

### 13. [Maintenance Automation](./maintenance-automation.md)
Rules for automated updates and maintenance procedures.

**Key Rules:**
- Never allow unattended updates without rollback
- Pin versions with automated updates
- Schedule maintenance during off-peak hours
- Implement comprehensive notifications

## The Universal Golden Rules

### Rule #1: Think Before You Delete
> Deletion is often irreversible and triggers cascading failures

### Rule #2: Suspend, Don't Delete
> Flux resources should be suspended for debugging, not deleted

### Rule #3: Test Locally First
> Use `--dry-run`, `kustomize build`, and local validation

### Rule #4: Understand Dependencies
> Know what depends on the resource you're modifying

### Rule #5: Monitor the Impact
> Watch pod counts and resource status during any operation

## Quick Decision Tree

```
Need to fix a broken resource?
├── Is it a Flux-managed resource?
│   ├── Yes → SUSPEND it first
│   └── No → Safe to modify directly
├── Is it a parent resource (namespace, kustomization)?
│   ├── Yes → EXTREME CAUTION - check dependencies
│   └── No → Proceed with normal caution
└── Will deletion cause cascading effects?
    ├── Yes → Find alternative (suspend, patch, fix in git)
    └── No → Safe to proceed
```

## Incident Log

- **2025-06-12**: Deleted `cluster-apps` kustomization, causing 80+ pod deletions (Recovery: 3 hours)
- **[Date]**: [Incident description] - Add new incidents here

## Remember

> **Every rule here represents hours of recovery time someone had to endure. Learn from these mistakes.**