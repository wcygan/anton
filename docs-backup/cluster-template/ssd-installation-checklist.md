# SSD Installation Checklist

This checklist guides you through adding SSDs to your Talos Linux cluster nodes.

## Pre-Installation Phase

### 1. Verify Cluster Health
- [x] Run comprehensive health check: `deno task monitor:all`
- [x] Verify all nodes are Ready: `kubectl get nodes`
- [x] Check etcd health: `kubectl -n kube-system get pods -l component=etcd`
- [x] Ensure no pending Flux reconciliations: `flux get all -A`
- [x] Document any existing issues before proceeding

### 2. Backup Current Configuration
- [x] Backup Talos config: `cp -r talos/clusterconfig talos/clusterconfig.backup-$(date +%Y%m%d)`
- [x] Export current disk configuration:
  ```bash
  mkdir -p progress/ssd-installation
  for ip in 192.168.1.98 192.168.1.99 192.168.1.100; do
    echo "=== Node $ip ===" >> progress/ssd-installation/pre-ssd-disk-inventory.txt
    talosctl get disks -n $ip >> progress/ssd-installation/pre-ssd-disk-inventory.txt
  done
  ```
- [x] Save cluster state: `kubectl cluster-info dump --output-directory=progress/ssd-installation/cluster-state-$(date +%Y%m%d)`
- [x] Document current storage usage: `./scripts/storage-health-check.ts --json > progress/ssd-installation/pre-ssd-storage-state.json`

### 3. Prepare Node-Specific Information
- [x] Node order: k8s-3 → k8s-2 → k8s-1 (start with least critical)
- [x] Create tracking sheet with columns: Node Name | IP | Current Serial | New SSD Serial | Status

## Per-Node Installation Process

### Node: k8s-3 (192.168.1.100)

#### Pre-Installation
- [x] Set node variables:
  ```bash
  export NODE_NAME="k8s-3"
  export NODE_IP="192.168.1.100"
  ```
- [x] Verify node health: `kubectl describe node ${NODE_NAME}`
- [x] Check workloads on node: `kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A`
- [x] Cordon node: `kubectl cordon ${NODE_NAME}`
- [x] Drain node: `kubectl drain ${NODE_NAME} --ignore-daemonsets --delete-emptydir-data --force --timeout=600s`
- [x] Verify drain completed: `kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A`

#### Physical Installation
- [x] Power down node via Talos: `talosctl shutdown -n ${NODE_IP}`
- [x] Wait for complete shutdown (verify no ping response)
- [x] Physically install SSD in available slot
- [x] Power on node
- [x] Wait for node to boot: `talosctl health -n ${NODE_IP} --wait-timeout 10m`

#### Post-Installation Configuration
- [x] Get new disk information: `talosctl get disks -n ${NODE_IP}`
- [x] Record new SSD serial number: 251021801882 (nvme0n1), 251021800405 (nvme2n1)
- [x] Create storage patch file:
  ```bash
  cat > talos/patches/${NODE_NAME}/storage.yaml << EOF
  machine:
    volumes:
      - name: fast-storage
        mountpoint: /var/mnt/fast
        diskSelector:
          serial: "PASTE_NEW_SSD_SERIAL_HERE"
        filesystem:
          type: xfs
  EOF
  ```
- [x] Update serial in patch file with actual value
- [x] Generate new config: `task talos:generate-config`
- [x] Apply configuration: `task talos:apply-node IP=${NODE_IP} MODE=auto`
- [x] Wait for node ready: `kubectl wait --for=condition=Ready node/${NODE_NAME} --timeout=300s`
- [x] Verify SSD mounted: `talosctl read /proc/mounts -n ${NODE_IP} | grep fast`
- [x] Uncordon node: `kubectl uncordon ${NODE_NAME}`
- [x] Verify workloads scheduled back: `kubectl get pods --field-selector spec.nodeName=${NODE_NAME} -A`

#### Verification
- [x] Node status healthy: `kubectl get node ${NODE_NAME}`
- [x] Storage accessible: `talosctl ls /var/mnt/fast1,fast2 -n ${NODE_IP}`
- [x] No errors in logs: `talosctl logs -n ${NODE_IP} | grep -i error | tail -20`
- [x] Flux reconciliations successful: `flux get all -A | grep False`

### Node: k8s-2 (192.168.1.99)
*Repeat all steps above with:*
- [x] NODE_NAME="k8s-2"
- [x] NODE_IP="192.168.1.99"

### Node: k8s-1 (192.168.1.98)
*Repeat all steps above with:*
- [x] NODE_NAME="k8s-1"
- [x] NODE_IP="192.168.1.98"

## Post-Installation Tasks

### 1. Verify Cluster Health
- [ ] All nodes Ready: `kubectl get nodes`
- [ ] Run full health check: `deno task monitor:all`
- [ ] Compare storage state: `./scripts/storage-health-check.ts --json | diff progress/ssd-installation/pre-ssd-storage-state.json -`
- [ ] Check etcd cluster health: `kubectl -n kube-system exec -it etcd-k8s-1 -- etcdctl member list`

### 2. Configure Kubernetes Storage
- [ ] Create StorageClass for fast storage (if using CSI driver)
- [ ] Update PV/PVC configurations as needed
- [ ] Test storage with sample pod:
  ```yaml
  apiVersion: v1
  kind: Pod
  metadata:
    name: storage-test
  spec:
    containers:
    - name: test
      image: busybox
      command: ['sh', '-c', 'echo "Storage test successful" > /mnt/test/success.txt && cat /mnt/test/success.txt']
      volumeMounts:
      - name: fast-storage
        mountPath: /mnt/test
    volumes:
    - name: fast-storage
      hostPath:
        path: /var/mnt/fast
        type: Directory
    nodeSelector:
      kubernetes.io/hostname: k8s-1
  ```

### 3. Update Documentation
- [ ] Update hardware inventory in repository
- [ ] Commit talconfig changes: `git add talos/ && git commit -m "feat: add SSD storage to cluster nodes"`
- [ ] Document any issues encountered
- [ ] Update monitoring thresholds if needed

## Rollback Plan

If issues occur during installation:

1. **Node won't boot after SSD installation:**
   - Remove SSD and reboot
   - Apply original config without storage patch
   - Investigate hardware compatibility

2. **Configuration apply fails:**
   - Restore from backup: `cp -r talos/clusterconfig.backup-$(date +%Y%m%d)/* talos/clusterconfig/`
   - Regenerate and reapply: `task talos:generate-config && task talos:apply-node IP=${NODE_IP} MODE=auto`

3. **Cluster instability after changes:**
   - Check etcd health and quorum
   - Review logs: `talosctl logs -n ${NODE_IP} | grep -E "(error|fail|critical)"`
   - Consider reverting one node at a time

## Success Criteria

- [ ] All nodes report Ready status
- [ ] New SSDs mounted at `/var/mnt/fast` on all nodes
- [ ] No Flux reconciliation failures
- [ ] Storage test pod runs successfully
- [ ] Monitoring shows healthy cluster state
- [ ] No increase in error logs

## Notes Section

Use this space to document:
- Actual SSD models/serials installed
- Any deviations from the process
- Performance observations
- Lessons learned

---

**Started:** _______________  
**Completed:** _______________  
**Performed by:** _______________