# Adding NVMe Storage to MS-01 Nodes

This document outlines the procedure for safely adding NVMe storage to MS-01
nodes in a running Talos Linux cluster.

## Prerequisites

- 3-node control plane cluster (maintains quorum during single node downtime)
- Physical access to MS-01 hardware
- New NVMe drives ready for installation

## Safety Considerations

**Critical**: Only upgrade one node at a time to maintain cluster availability
and etcd quorum (2/3 nodes).

## Procedure

### 1. Pre-upgrade Preparation

Before touching any hardware:

```bash
# Check cluster health
kubectl get nodes
kubectl get pods --all-namespaces | grep -v Running

# Verify etcd health
kubectl -n kube-system get pods -l component=etcd
```

### 2. Per-Node Upgrade Process

Repeat this process for each MS-01 node:

#### Step 1: Drain the Node

```bash
# Replace <node-name> with actual node name
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force
```

#### Step 2: Verify Node is Drained

```bash
kubectl get pods --all-namespaces --field-selector spec.nodeName=<node-name>
```

#### Step 3: Power Down and Hardware Upgrade

1. Gracefully shutdown the node:
   ```bash
   talosctl shutdown --nodes <node-ip>
   ```
2. Wait for complete shutdown
3. Power off and unplug the MS-01
4. Install NVMe drives following hardware guide
5. Reassemble and power on

#### Step 4: Verify Node Rejoins Cluster

```bash
# Wait for node to appear
kubectl get nodes -w

# Check node status
kubectl describe node <node-name>

# Verify etcd pod is running
kubectl -n kube-system get pods -l component=etcd --field-selector spec.nodeName=<node-name>
```

#### Step 5: Uncordon the Node

```bash
kubectl uncordon <node-name>
```

#### Step 6: Validate Pod Scheduling

```bash
# Wait for pods to be scheduled back
kubectl get pods --all-namespaces --field-selector spec.nodeName=<node-name>

# Check overall cluster health
kubectl get nodes
kubectl get pods --all-namespaces | grep -v Running
```

### 3. Post-Upgrade Configuration

If you need to configure the new NVMe drives in Talos:

1. Update machine configuration to include new storage
2. Apply the updated configuration:
   ```bash
   task talos:apply-node IP=<node-ip> MODE=auto
   ```

### 4. Validation Commands

After all nodes are upgraded:

```bash
# Full cluster health check
./scripts/k8s-health-check.ts --verbose

# Check storage availability
kubectl get pv
kubectl get pvc --all-namespaces

# Verify Flux is healthy
flux check
flux get ks -A
```

## Troubleshooting

### Node Fails to Rejoin

```bash
# Check Talos logs
talosctl logs --nodes <node-ip>

# Reset and rejoin if necessary
talosctl reset --nodes <node-ip>
# Then re-bootstrap the node
```

### etcd Issues

```bash
# Check etcd member status
kubectl -n kube-system exec -it etcd-<node-name> -- etcdctl member list

# If etcd member is unhealthy, may need to remove and re-add
```

## Timeline Expectations

- **Per node**: 30-60 minutes (including hardware work)
- **Total for 3 nodes**: 2-4 hours
- **Cluster downtime**: None (rolling upgrade)

## References

- [MS-01 Storage Addition Guide](https://blog.pcfe.net/hugo/posts/2024-12-24-minisforum-ms-01-add-storage/)
- [Talos Machine Configuration](https://www.talos.dev/v1.5/reference/configuration/)
- [Kubernetes Node Maintenance](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
