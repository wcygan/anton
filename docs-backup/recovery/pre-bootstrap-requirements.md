# Pre-Bootstrap Requirements: New Laptop Setup

This document details everything needed to bootstrap the Anton homelab cluster from a completely new laptop/workstation. All critical items should be stored in 1Password for secure access and disaster recovery.

## 🔐 Required 1Password Items

Store these items in your 1Password vault (`anton` or similar) for complete disaster recovery capability:

### 1. **Cloudflare Configuration** (`cloudflare-kubernetes-config`)
- **API Token**: Kubernetes API token with Zone DNS Edit + Cloudflare Tunnel Read permissions
- **Tunnel ID**: UUID of the kubernetes tunnel
- **Account ID**: Cloudflare account identifier
- **Domain**: Your registered domain name
- **Files to Download**:
  - `cloudflare-tunnel.json` - Tunnel credentials file

### 2. **1Password Connect Setup** (`1password-connect-homelab`)
- **Connect Credentials File**: `1password-credentials.json` - Connect server authentication
- **API Token**: 1Password API access token for External Secrets Operator
- **Vault Information**: 
  - Vault name: `anton` (or your vault name)
  - Vault ID: `1` (numerical ID)

### 3. **Git Repository Access** (`homelab-git-access`)
- **GitHub Personal Access Token**: For repository cloning and webhook setup
- **Deploy Key**: SSH private key (`github-deploy.key`) for Flux GitOps access
- **Repository URL**: `https://github.com/{username}/homelab` (your forked repo)

### 4. **SOPS Encryption** (`homelab-sops-encryption`)
- **Age Key**: `age.key` file - **CRITICAL** for decrypting cluster secrets
- **Public Key**: Corresponding public key for encryption

### 5. **Talos Configuration** (`talos-cluster-config`)
- **Talos Secret**: `talsecret.yaml` - Bootstrap secrets
- **Cluster Configuration**: Key Talos settings and certificates
- **Machine Information**:
  - Node IPs: `192.168.1.98`, `192.168.1.99`, `192.168.1.100`
  - Schematic ID: From Talos Image Factory
  - Hardware specs: MS-01 with 96GB RAM, 500GB NVMe per node

### 6. **Hardware Configuration** (`homelab-hardware-specs`)
- **Network Configuration**:
  - Cluster CIDR: `10.42.0.0/16`
  - Service CIDR: `10.43.0.0/16`
  - Node network: `192.168.1.0/24`
- **Storage Configuration**:
  - NVMe drive layout per node
  - Ceph storage requirements
- **BIOS/UEFI Settings**: Boot order, secure boot status

## 📋 Recovery Checklist

### Stage 1: Local Workstation Setup

1. **Install Core Dependencies**:
   ```bash
   # Install mise for tool management
   curl https://mise.jdx.dev/install.sh | sh
   
   # Clone the repository
   git clone https://github.com/{username}/homelab.git
   cd homelab
   
   # Install all required tools
   mise trust
   pip install pipx
   mise install
   ```

2. **Retrieve Critical Files from 1Password**:
   ```bash
   # Create secure directory for sensitive files
   mkdir -p ~/Downloads/homelab-recovery
   
   # Download these files from 1Password:
   # - 1password-credentials.json
   # - 1password-api-token.txt  
   # - cloudflare-tunnel.json
   # - age.key
   # - github-deploy.key
   ```

3. **Configure Git Access**:
   ```bash
   # Place deploy key for Flux GitOps
   cp ~/Downloads/homelab-recovery/github-deploy.key .github/
   
   # Set up git credentials if needed
   git config --global user.name "Your Name"
   git config --global user.email "your.email@domain.com"
   ```

### Stage 2: Encryption Setup

1. **SOPS Configuration**:
   ```bash
   # CRITICAL: Place age key for secret decryption
   cp ~/Downloads/homelab-recovery/age.key ./age.key
   
   # Verify SOPS can decrypt existing secrets
   sops -d kubernetes/flux/config/cluster-secrets.sops.yaml
   ```

### Stage 3: Cloud Services Configuration

1. **Cloudflare Setup**:
   ```bash
   # Place tunnel credentials
   cp ~/Downloads/homelab-recovery/cloudflare-tunnel.json ./
   
   # Verify tunnel exists
   cloudflared tunnel list
   ```

2. **1Password Connect Files**:
   ```bash
   # Place 1Password Connect files in expected location
   cp ~/Downloads/homelab-recovery/1password-credentials.json ~/Downloads/
   cp ~/Downloads/homelab-recovery/1password-api-token.txt ~/Downloads/
   ```

### Stage 4: Hardware and Network Verification

1. **Network Access**:
   ```bash
   # Verify nodes are accessible
   nmap -Pn -n -p 50000 192.168.1.98,192.168.1.99,192.168.1.100 -vv
   ```

2. **Talos Image Preparation** (if nodes need re-imaging):
   - Download Talos ISO from Image Factory using stored schematic ID
   - Flash to USB drives for each node if bare metal recovery needed

### Stage 5: Cluster Bootstrap

Follow the standard bootstrap process from README.md:

```bash
# Generate configs
task init
# Edit cluster.yaml and nodes.yaml with stored values
task configure

# Bootstrap Talos
task bootstrap:talos

# Push initial commit
git add -A
git commit -m "chore: initial recovery commit"
git push

# Bootstrap core apps
task bootstrap:apps

# Setup 1Password Connect
deno task 1p:install

# Complete cluster deployment
task reconcile
```

## 🔍 Verification Commands

After recovery, verify all systems:

```bash
# Cluster health
kubectl get nodes
cilium status

# GitOps functionality
flux check
flux get sources git flux-system

# Secret management
kubectl get clustersecretstore onepassword-connect
kubectl get externalsecret -A | grep cluster-secrets

# Storage
kubectl get cephcluster -n storage
kubectl get pv
```

## 🚨 Emergency Contacts & Resources

- **Talos Documentation**: https://www.talos.dev/
- **Flux Documentation**: https://fluxcd.io/
- **1Password Connect**: https://developer.1password.com/docs/connect/
- **Cluster Template**: https://github.com/onedr0p/cluster-template

## 📝 Notes

- **Critical Path**: The `age.key` file is absolutely essential - without it, encrypted secrets cannot be decrypted
- **Network Dependencies**: Ensure your network configuration matches the stored cluster configuration
- **Hardware Requirements**: Verify all nodes meet minimum requirements (4 cores, 16GB RAM, 256GB storage)
- **Timing**: Full bootstrap takes 15+ minutes - do not interrupt the process
- **Backup Strategy**: Consider storing a encrypted backup of this entire configuration in a separate secure location

## 🔄 Regular Maintenance

- **Monthly**: Verify 1Password items are accessible and up-to-date
- **Before Major Changes**: Export current configurations to 1Password
- **After Hardware Changes**: Update hardware configuration documentation
- **Quarterly**: Test disaster recovery process in lab environment