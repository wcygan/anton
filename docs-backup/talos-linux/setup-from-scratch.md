# Setting Up Anton Homelab from Scratch

This guide walks through setting up the Anton Kubernetes homelab cluster from a fresh repository clone, including all secrets, configuration files, and bootstrapping steps.

## Prerequisites

Before starting, ensure you have:

- **Hardware**: 3x MS-01 mini PCs (or similar) with at least 4 cores, 16GB RAM, and 256GB SSD each
- **Cloudflare account** with a domain configured
- **GitHub account** for GitOps repository
- **Workstation** with internet access for running setup commands

## Overview

The setup process involves 5 main stages:

1. **Machine Preparation** - Creating Talos Linux images and booting nodes
2. **Local Workstation Setup** - Installing tools and cloning repository
3. **Cloudflare Configuration** - Setting up API tokens and tunnels
4. **Cluster Configuration** - Creating config files and secrets
5. **Bootstrap** - Installing Talos, Kubernetes, and applications

## Stage 1: Machine Preparation

### 1.1 Create Talos Linux Images

1. Visit [Talos Linux Image Factory](https://factory.talos.dev)
2. Select your hardware platform (bare-metal for MS-01)
3. Choose minimal system extensions (avoid extras that need configuration)
4. Note the **schematic ID** - you'll need this for `nodes.yaml`
5. Download the ISO image (or RAW for SBCs)

### 1.2 Flash and Boot Nodes

1. Flash the Talos image to USB drives
2. Boot each node from the USB drive
3. Talos will install to the system disk automatically
4. Note the IP address of each node as they boot

### 1.3 Verify Network Connectivity

```bash
# Replace with your network range
nmap -Pn -n -p 50000 192.168.1.0/24 -vv | grep 'Discovered'
```

## Stage 2: Local Workstation Setup

### 2.1 Clone Repository

```bash
git clone https://github.com/wcygan/anton.git
cd homelab
```

### 2.2 Install Required Tools

```bash
# Install mise (tool version manager)
curl https://mise.run | sh
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
source ~/.bashrc

# Trust repository configuration
mise trust

# Install Python tools
pip install pipx

# Install all required CLI tools
mise install
```

Required tools installed by mise:
- `talosctl` - Talos cluster management
- `kubectl` - Kubernetes CLI
- `flux` - GitOps operator
- `cloudflared` - Cloudflare tunnel client
- `age` - Encryption for secrets
- `sops` - Secret management
- `talhelper` - Talos config templating

## Stage 3: Cloudflare Configuration

### 3.1 Create API Token

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token" → Use "Edit zone DNS" template
3. Configure token:
   - **Token name**: `kubernetes`
   - **Permissions**: 
     - Zone → DNS → Edit
     - Account → Cloudflare Tunnel → Read
   - **Zone Resources**: Include your domain
4. Create token and **save it securely**

### 3.2 Create Cloudflare Tunnel

```bash
# Login to Cloudflare
cloudflared tunnel login

# Create tunnel and save credentials
cloudflared tunnel create --credentials-file cloudflare-tunnel.json kubernetes

# Note the tunnel ID from the output
```

## Stage 4: Cluster Configuration

### 4.1 Generate Configuration Files

```bash
# Creates cluster.yaml and nodes.yaml from samples
task init
```

### 4.2 Create age.key for Encryption

```bash
# Generate encryption key
age-keygen -o age.key

# IMPORTANT: Back up this key securely!
# Without it, you cannot decrypt secrets
```

### 4.3 Configure cluster.yaml

Edit `cluster.yaml` with your network settings:

```yaml
# Network configuration
node_cidr: "192.168.1.0/24"              # Your network range
cluster_api_addr: "192.168.1.200"        # Unused IP for K8s API
cluster_dns_gateway_addr: "192.168.1.201" # Unused IP for DNS
cluster_ingress_addr: "192.168.1.202"    # Unused IP for internal ingress
cloudflare_ingress_addr: "192.168.1.203" # Unused IP for external ingress

# Cloudflare settings
cloudflare_domain: "wcygan.net"         # Your domain
cloudflare_token: "your-api-token"       # From step 3.1

# GitHub repository
repository_name: "wcygan/anton"      # Your repo
```

### 4.4 Configure nodes.yaml

Get hardware information for each node:

```bash
# For each node, get disk and network info
NODE_IP="192.168.1.98"  # Replace with your node IP

# Get disk information
talosctl get disks -n $NODE_IP --insecure

# Get network interface information
talosctl get links -n $NODE_IP --insecure
```

Edit `nodes.yaml` with discovered hardware:

```yaml
nodes:
  - name: "k8s-1"
    address: "192.168.1.98"
    controller: true
    disk: "/dev/disk/by-id/ata-Samsung_SSD_850_EVO_500GB_S21HNXAG806040L"
    mac_addr: "00:e2:69:5a:1c:7d"
    schematic_id: "your-schematic-id-from-factory"
  - name: "k8s-2"
    address: "192.168.1.99"
    controller: true
    disk: "/dev/disk/by-id/ata-Samsung_SSD_850_EVO_500GB_S21HNXAG806041M"
    mac_addr: "00:e2:69:5a:1c:7e"
    schematic_id: "your-schematic-id-from-factory"
  - name: "k8s-3"
    address: "192.168.1.100"
    controller: true
    disk: "/dev/disk/by-id/ata-Samsung_SSD_850_EVO_500GB_S21HNXAG806042N"
    mac_addr: "00:e2:69:5a:1c:7f"
    schematic_id: "your-schematic-id-from-factory"
```

### 4.5 Generate Talos and Kubernetes Configs

```bash
# Template out all configuration files
task configure
```

This creates:
- `talos/clusterconfig/*.yaml` - Node-specific Talos configs
- `talos/clusterconfig/talosconfig` - Talos client config
- `kubernetes/**/*.yaml` - Kubernetes manifests

### 4.6 Commit Initial Configuration

```bash
# Verify SOPS encryption is working
# All *.sops.yaml files should be encrypted

git add -A
git commit -m "chore: initial cluster configuration"
git push
```

## Stage 5: Bootstrap Cluster

### 5.1 Bootstrap Talos

```bash
# Install Talos on all nodes
# This takes 10+ minutes
task bootstrap:talos
```

This will:
1. Generate Talos secrets (stored in `talsecret.sops.yaml`)
2. Apply configuration to each node
3. Bootstrap the Kubernetes cluster
4. Generate kubeconfig at `~/.kube/config`

### 5.2 Commit Talos Secrets

```bash
git add -A
git commit -m "chore: add talhelper encrypted secrets"
git push
```

### 5.3 Bootstrap Applications

```bash
# Install core Kubernetes applications
task bootstrap:apps
```

This installs:
- **Cilium** - Container networking (CNI)
- **CoreDNS** - Cluster DNS
- **Spegel** - Container image mirror
- **Flux** - GitOps operator

### 5.4 Monitor Deployment

```bash
# Watch pods come online
kubectl get pods --all-namespaces --watch

# Check Flux synchronization
flux get all -A
```

## Post-Installation Verification

### Check Core Services

```bash
# Cilium networking
cilium status

# Flux GitOps
flux check
flux get sources git -A
flux get ks -A
flux get hr -A

# Ingress connectivity
nmap -Pn -n -p 443 192.168.1.202 192.168.1.203

# DNS resolution
dig @192.168.1.201 echo.wcygan.com
```

### Configure GitHub Webhook (Optional)

For instant GitOps updates on push:

```bash
# Get webhook URL
kubectl -n flux-system get receiver github-webhook -o jsonpath='{.status.webhookPath}'

# Add to GitHub repository settings:
# https://flux-webhook.example.com/hook/<webhook-path>
```

## Secrets Management

### Using 1Password (Recommended)

The cluster includes External Secrets Operator for 1Password integration:

1. Store secrets in 1Password vault
2. Create `OnePasswordItem` resources to sync secrets
3. Reference synced secrets in applications

Example:
```yaml
apiVersion: onepassword.com/v1
kind: OnePasswordItem
metadata:
  name: app-credentials
  namespace: default
spec:
  itemPath: "vaults/Homelab/items/my-app"
```

### Legacy SOPS Encryption

For infrastructure secrets, SOPS encryption is automatic:
- Files matching `*.sops.yaml` are encrypted
- Uses `age.key` for encryption/decryption
- Flux decrypts automatically during deployment

## Maintenance Commands

### Force Flux Reconciliation
```bash
task reconcile
```

### Update Node Configuration
```bash
task talos:apply-node IP=192.168.1.98 MODE=auto
```

### Upgrade Talos
```bash
task talos:upgrade-node IP=192.168.1.98
```

### Upgrade Kubernetes
```bash
task talos:upgrade-k8s
```

### Reset Cluster (Destructive!)
```bash
task talos:reset
```

## Troubleshooting

### Common Issues

1. **Pods stuck in Pending/CrashLoop**
   ```bash
   kubectl describe pod <pod-name> -n <namespace>
   kubectl logs <pod-name> -n <namespace>
   ```

2. **Flux not syncing**
   ```bash
   flux logs --follow
   kubectl -n flux-system get events --sort-by='.lastTimestamp'
   ```

3. **Network connectivity issues**
   ```bash
   cilium connectivity test
   kubectl get svc -A
   ```

### Debug Scripts

The repository includes helpful debugging scripts:
```bash
./scripts/k8s-health-check.ts        # Cluster health overview
./scripts/flux-deployment-check.ts   # GitOps deployment status
./scripts/flux-monitor.ts           # Real-time Flux monitoring
```

## Next Steps

With the cluster running, you can:

1. **Add applications** - See [Adding New Applications](../add-app.md)
2. **Configure storage** - Consider Rook-Ceph, Longhorn, or democratic-csi
3. **Set up monitoring** - Prometheus and Grafana are pre-installed
4. **Enable Renovate** - Automated dependency updates

Remember:
- All changes should be made via Git commits (GitOps)
- Use `task` commands for cluster operations
- Keep `age.key` backed up securely
- Monitor [Flux Dependency Dashboard](https://github.com/yourusername/homelab/issues) for updates