# Disaster Recovery Runbook

**Status**: Production Ready  
**Last Updated**: 2025-06-13  
**RTO**: 4 hours (Recovery Time Objective)  
**RPO**: 24 hours (Recovery Point Objective)

This runbook provides step-by-step procedures for recovering the Anton homelab cluster from various disaster scenarios.

## 🚨 Emergency Response Matrix

| Scenario | Severity | RTO | Recovery Method |
|----------|----------|-----|-----------------|
| Single Node Failure | Low | 30 min | Node replacement + rejoin |
| Multiple Node Failure | Medium | 2 hours | Partial cluster rebuild |
| Complete Cluster Loss | High | 4 hours | Full bootstrap from backups |
| Network/Storage Loss | High | 4 hours | Infrastructure + cluster rebuild |
| Secret/Config Loss | Critical | 6 hours | Recovery from 1Password |

## 📋 Pre-Disaster Preparation

### Ensure Ready State
- [ ] 1Password vault `homelab-recovery` accessible
- [ ] Hardware documentation current
- [ ] Network topology documented
- [ ] Recent backup verification completed

### Quick Access Information
- **Primary Contact**: [Your contact info]
- **1Password Account**: [Account details]
- **Hardware Vendor**: [Support contact]
- **Network Provider**: [ISP contact]

## 🔥 Scenario 1: Single Node Failure

**Symptoms**: One k8s node shows NotReady, pods rescheduling

### Assessment (5 minutes)
```bash
# Check cluster status
kubectl get nodes -o wide
kubectl get pods --all-namespaces --field-selector=status.phase!=Running

# Check Talos node status
talosctl -n 192.168.1.{98,99,100} version
```

### Recovery Steps (20-30 minutes)
```bash
# 1. Identify failed node
FAILED_NODE_IP="192.168.1.XX"

# 2. Check if node can be recovered
talosctl -n $FAILED_NODE_IP dmesg | tail -50
talosctl -n $FAILED_NODE_IP logs kubelet

# 3. If hardware failure, physically replace node
# 4. Re-image with Talos ISO (using stored schematic ID)

# 5. Apply Talos configuration
task talos:apply-node IP=$FAILED_NODE_IP MODE=auto

# 6. Wait for node to join cluster
kubectl get nodes --watch

# 7. Verify workloads redistribute
kubectl get pods --all-namespaces -o wide | grep $FAILED_NODE_IP
```

### Validation
- [ ] Node shows Ready status
- [ ] All pods successfully rescheduled
- [ ] Ceph cluster healthy (if storage node)
- [ ] No persistent errors in logs

## 🔥 Scenario 2: Complete Cluster Loss

**Symptoms**: All nodes unreachable, cluster completely down

### Assessment (10 minutes)
```bash
# Check network connectivity
nmap -Pn -n -p 50000 192.168.1.98,192.168.1.99,192.168.1.100

# Attempt Talos connection
talosctl -n 192.168.1.98,192.168.1.99,192.168.1.100 version

# Check if nodes need re-imaging
# Physical console access may be required
```

### Recovery Steps (3-4 hours)

#### Phase 1: Infrastructure Recovery (30 minutes)
```bash
# 1. Retrieve recovery files from 1Password
mkdir -p ~/recovery
# Download: age.key, 1password-credentials.json, cloudflare-tunnel.json, talsecret.yaml

# 2. Setup local workstation
git clone https://github.com/{username}/homelab.git
cd homelab
mise trust && mise install

# 3. Restore critical configuration files
cp ~/recovery/age.key ./age.key
cp ~/recovery/1password-credentials.json ~/Downloads/
cp ~/recovery/cloudflare-tunnel.json ./
```

#### Phase 2: Hardware Recovery (30-60 minutes)
```bash
# 1. If nodes need re-imaging:
# - Download Talos ISO with stored schematic ID
# - Flash to USB drives
# - Boot each node from USB
# - Complete Talos installation

# 2. Verify nodes are accessible
nmap -Pn -n -p 50000 192.168.1.98,192.168.1.99,192.168.1.100
```

#### Phase 3: Cluster Bootstrap (60-90 minutes)
```bash
# 1. Generate configuration
task init
# Edit cluster.yaml and nodes.yaml with 1Password values

# 2. Template configurations
task configure

# 3. Bootstrap Talos
task bootstrap:talos

# 4. Commit initial state
git add -A
git commit -m "disaster recovery: initial bootstrap"
git push

# 5. Bootstrap applications
task bootstrap:apps

# 6. Setup 1Password Connect
deno task 1p:install

# 7. Complete deployment
task reconcile
```

#### Phase 4: Validation (30 minutes)
```bash
# Verify cluster health
kubectl get nodes
cilium status
flux check

# Verify applications
kubectl get pods --all-namespaces
kubectl get pv
kubectl get externalsecret -A

# Check monitoring
curl -k https://grafana.yourdomain.com
```

### Expected Recovery Time
- **Hardware replacement**: 1-2 hours
- **Software bootstrap**: 1-2 hours  
- **Application deployment**: 30-60 minutes
- **Total**: 3-4 hours

## 🔥 Scenario 3: Secret Management Failure

**Symptoms**: External Secrets failing, 1Password Connect unreachable

### Assessment (5 minutes)
```bash
# Check External Secrets Operator
kubectl get clustersecretstore onepassword-connect
kubectl get externalsecret -A | grep -v "SecretSynced.*True"

# Check 1Password Connect
kubectl logs -n external-secrets deployment/onepassword-connect
kubectl get pods -n external-secrets
```

### Recovery Steps (30-60 minutes)

#### Option A: 1Password Connect Recovery
```bash
# 1. Uninstall and reinstall 1Password Connect
deno task 1p:uninstall
deno task 1p:install

# 2. Verify ClusterSecretStore
kubectl get clustersecretstore onepassword-connect -o yaml

# 3. Force secret reconciliation
kubectl delete externalsecret -A --all
flux reconcile kustomization cluster-apps
```

#### Option B: Manual Secret Recreation
```bash
# 1. Extract secrets from 1Password manually
op item get "cluster-secrets" --format json

# 2. Create Kubernetes secrets directly
kubectl create secret generic cluster-secrets \
  --from-literal=key1=value1 \
  --from-literal=key2=value2 \
  -n namespace

# 3. Repeat for all namespaces needing secrets
```

### Validation
- [ ] ClusterSecretStore shows Ready
- [ ] All ExternalSecrets show SecretSynced: True
- [ ] Applications can access required secrets
- [ ] No authentication errors in logs

## 🔥 Scenario 4: Storage Catastrophic Failure

**Symptoms**: Ceph cluster down, PVs unavailable, data loss risk

### Assessment (10 minutes)
```bash
# Check Ceph cluster status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph health detail

# Check persistent volumes
kubectl get pv
kubectl get pvc --all-namespaces

# Check OSD status
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd status
```

### Recovery Steps (2-4 hours)

#### Option A: Ceph Recovery (if possible)
```bash
# 1. Check for recoverable OSDs
kubectl -n storage exec deploy/rook-ceph-tools -- ceph osd tree

# 2. Restart Ceph components
kubectl rollout restart deployment -n storage
kubectl rollout restart daemonset -n storage

# 3. Force Ceph reconstruction if needed
kubectl -n storage exec deploy/rook-ceph-tools -- ceph pg repair
```

#### Option B: Complete Storage Rebuild
```bash
# 1. Delete Ceph cluster
kubectl delete cephcluster storage -n storage

# 2. Clean nodes (DESTRUCTIVE - DATA LOSS)
# SSH to each node and clear Ceph data
for node in 192.168.1.{98,99,100}; do
  ssh root@$node "rm -rf /var/lib/rook"
done

# 3. Redeploy Ceph
flux reconcile helmrelease rook-ceph-cluster -n storage

# 4. Restore from backups (if available)
# Follow application-specific restore procedures
```

### Validation
- [ ] Ceph cluster shows HEALTH_OK
- [ ] All PVs bound and available
- [ ] Applications can write to storage
- [ ] No data corruption detected

## 📦 Data Recovery Procedures

### Application-Specific Recovery

#### PostgreSQL Databases
```bash
# If using CNPG (CloudNative PostgreSQL)
kubectl get postgresql -A
kubectl describe postgresql app-postgres -n namespace

# Restore from backup
kubectl apply -f backup-restore-manifest.yaml
```

#### Grafana Dashboards
```bash
# Dashboards stored in ConfigMaps
kubectl get configmaps -n monitoring | grep grafana

# Or restore from backup
kubectl apply -f grafana-backup-configmaps.yaml
```

#### Application Data
```bash
# Most application data should be in persistent volumes
# Check backup schedules with Volsync
kubectl get replicationsource -A
kubectl get replicationdestination -A
```

## 🧪 Recovery Testing

### Monthly Testing (30 minutes)
- [ ] Verify 1Password vault access
- [ ] Test SOPS secret decryption
- [ ] Validate backup accessibility
- [ ] Check recovery documentation currency

### Quarterly Testing (2 hours)
- [ ] Single node failure simulation
- [ ] Secret management failure test
- [ ] Storage failure recovery test
- [ ] Network connectivity issues

### Annual Testing (1 day)
- [ ] Complete cluster rebuild test
- [ ] Full disaster recovery simulation
- [ ] Update recovery procedures
- [ ] Train additional team members

## 📞 Escalation Procedures

### Internal Escalation
1. **Primary Administrator**: [Your contact]
2. **Secondary Contact**: [Backup person]
3. **On-call Schedule**: [If applicable]

### External Escalation
1. **Hardware Vendor Support**: [Vendor contact]
2. **Network Provider Support**: [ISP contact]
3. **Cloud Services**: [1Password, Cloudflare support]

### Communication
- **Status Updates**: Every 30 minutes during incident
- **Documentation**: Record all actions and outcomes
- **Post-Mortem**: Conduct review within 48 hours

## 📝 Post-Recovery Checklist

### Immediate (0-2 hours)
- [ ] All services operational
- [ ] Data integrity verified
- [ ] Security audit completed
- [ ] Monitoring alerts resolved

### Short-term (2-24 hours)
- [ ] Performance monitoring
- [ ] Backup verification
- [ ] Documentation updates
- [ ] Team notification

### Long-term (1-7 days)
- [ ] Post-mortem completed
- [ ] Process improvements identified
- [ ] Recovery procedures updated
- [ ] Preventive measures implemented

Remember: **Document everything during recovery** - this information improves future response times and procedures.