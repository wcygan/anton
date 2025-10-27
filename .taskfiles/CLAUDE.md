# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with Task workflows in this repository.

## Project Overview

Task workflows automate cluster lifecycle from initial configuration through deployment and ongoing management. Understanding the 4-stage linear flow is key to working effectively.

**Key Concept**: Tasks are organized by stage - init → configure → bootstrap → manage. Each stage depends on the previous completing successfully.

## The 4-Stage Workflow (Linear Path)

### Stage 1: Initialize (One-Time Setup)

**Goal**: Generate configuration files and encryption keys

**Command**: `task init`

**What it does**:
```
Generates 4 files:
1. cluster.yaml (from .sample)
2. nodes.yaml (from .sample)
3. age.key (SOPS encryption key)
4. github-deploy.key (Git SSH key for Flux)
```

**Next step**: Edit cluster.yaml and nodes.yaml with your values

**Common issues**:
- Files already exist → Task skips (idempotent)
- Age key conflicts with ~/.config/sops/age/keys.txt → Remove system key, use repo key

### Stage 2: Configure (Every Config Change)

**Goal**: Render templates, validate manifests, encrypt secrets

**Command**: `task configure`

**What it does** (5 substeps in order):
```
1. validate-schemas       → CUE validates cluster.yaml/nodes.yaml
2. render-configs         → Makejinja generates all manifests
3. encrypt-secrets        → SOPS encrypts *.sops.* files
4. validate-kubernetes    → Kubeconform checks K8s manifests
5. validate-talos         → talhelper checks Talos configs
```

**When to run**:
- After editing cluster.yaml or nodes.yaml
- After changing any template file
- Before every git commit (ensures secrets encrypted)

**Output**: All manifests rendered in bootstrap/, kubernetes/, talos/

**Next step**: Commit changes and push to Git

### Stage 3: Bootstrap (Cluster Creation)

**Goal**: Install Talos and deploy core services

**Commands** (in order):
```bash
task bootstrap:talos  # Install Talos OS on nodes
task bootstrap:apps   # Deploy CNI, DNS, Flux
```

**What bootstrap:talos does**:
```
1. Generate Talos secret (talsecret.sops.yaml)
2. Generate machine configs (talhelper genconfig)
3. Apply configs to nodes (talhelper apply --insecure)
4. Bootstrap etcd cluster
5. Generate kubeconfig file
```

**What bootstrap:apps does** (5 phases):
```
1. Wait for nodes to be Ready
2. Create namespaces
3. Apply SOPS secrets (encryption keys)
4. Install CRDs
5. Deploy apps: cilium → coredns → spegel → cert-manager → flux
```

**When to run**:
- Initial cluster setup only
- After full cluster rebuild

**Output**: Working Kubernetes cluster with Flux watching Git

**Next step**: Flux manages everything from now on

### Stage 4: Manage (Ongoing Operations)

**Goal**: Update cluster configuration and debug issues

**Common commands**:
```bash
task reconcile                          # Force Flux to sync Git
task template:debug                     # Show cluster status
task talos:apply-node IP=X MODE=auto    # Apply config to node
task talos:upgrade-node IP=X            # Upgrade Talos version
task talos:upgrade-k8s                  # Upgrade Kubernetes version
```

**When to run**:
- After pushing changes to Git (or wait for auto-sync)
- When debugging cluster issues
- During version upgrades

## Task Dependency Map

```
init (no dependencies)
    ↓
configure (needs: cluster.yaml, nodes.yaml, age.key)
    ↓
bootstrap:talos (needs: talconfig.yaml from configure)
    ↓
bootstrap:apps (needs: kubeconfig from bootstrap:talos)
    ↓
manage tasks (needs: running cluster)
```

**Key insight**: Can't skip stages. Must complete previous stage before next.

## When to Use Existing Tasks vs Create New

### Use Existing Tasks When

| Scenario | Task to Use |
|----------|-------------|
| Modified cluster.yaml | `task configure` |
| Modified nodes.yaml | `task configure` |
| Added new Kubernetes app | `task configure` then `task reconcile` |
| Changed Talos config | `task talos:generate-config` then `task talos:apply-node` |
| Debugging cluster | `task template:debug` |
| Flux not syncing | `task reconcile` |
| Upgrading Talos | `task talos:upgrade-node IP=X` |
| Upgrading Kubernetes | `task talos:upgrade-k8s` |
| Clean up after setup | `task template:tidy` |

### Create New Tasks When

**Add to .taskfiles/{category}/Taskfile.yaml** when:
- Automating repetitive manual operations
- Need pre/post conditions that don't exist
- Custom validation steps for your environment
- Cluster-specific operations (database backups, etc.)

**Pattern for new task**:
```yaml
tasks:
  your-task:
    desc: Clear one-line description
    cmd: your command here
    preconditions:
      - test -f {{required_file}}
    vars:
      DERIVED:
        sh: echo "calculated value"
```

**Example** (adding backup task):
```yaml
# In .taskfiles/manage/Taskfile.yaml
namespace: manage

tasks:
  backup-etcd:
    desc: Backup etcd data to local file
    cmd: |
      talosctl -n {{.CONTROLLER_IP}} etcd snapshot \
        backup/etcd-$(date +%Y%m%d-%H%M%S).db
    preconditions:
      - test -f {{.KUBECONFIG}}
      - test -d backup/
```

## Validation Pipeline Deep Dive

### Step 1: Schema Validation (CUE)

**What it checks**: cluster.yaml and nodes.yaml structure and constraints

**Example constraints**:
- IPs are valid (192.168.1.x format)
- CIDRs don't overlap
- Required fields present
- Node roles valid (controller/worker)

**Schema files**:
- `.taskfiles/template/resources/cluster.schema.cue`
- `.taskfiles/template/resources/nodes.schema.cue`

**When it fails**: Invalid values in cluster.yaml/nodes.yaml

**Fix**: Edit configs to match schema requirements

### Step 2: Template Rendering (Makejinja)

**What it does**: Processes Jinja2 templates with cluster.yaml/nodes.yaml values

**Custom filters** (from plugin.py):
- `age_key()` - Extract Age encryption keys
- `nthhost()` - Calculate IP from CIDR (e.g., 192.168.1.0/24 → 192.168.1.10)
- `talos_patches()` - Load node-specific patch files
- `basename()` - Extract filename from path

**Output directories**:
- `bootstrap/` - Helmfile bootstrap configs
- `kubernetes/` - Flux Kustomizations and HelmReleases
- `talos/` - Talos machine configs

**When it fails**: Template syntax errors or missing variables

**Fix**: Check template files for typos, ensure cluster.yaml has required variables

### Step 3: Secret Encryption (SOPS)

**What it does**: Encrypts all `*.sops.*` files with Age key

**How it works**:
```bash
# For each *.sops.* file:
sops --encrypt --in-place FILE
```

**Encryption config**: `.sops.yaml` defines which fields to encrypt

**When it fails**:
- Age key missing (SOPS_AGE_KEY_FILE not set)
- .sops.yaml invalid
- File already encrypted (runs again = no-op)

**Fix**: Ensure age.key exists, SOPS_AGE_KEY_FILE points to it

### Step 4: Kubernetes Validation (Kubeconform)

**What it does**: Validates all Kubernetes manifests against API schemas

**Script**: `.taskfiles/template/resources/kubeconform.sh`

**Validates**:
- Standalone manifests (yaml files)
- Kustomization outputs (runs kustomize build first)

**Skips** (custom CRDs not in schema):
- Gateway, HTTPRoute (Gateway API)
- HelmRelease, Kustomization (Flux)
- DNSEndpoint, Certificate (external-dns, cert-manager)

**When it fails**: Invalid Kubernetes resource definitions

**Fix**: Check manifest syntax, ensure required fields present

### Step 5: Talos Validation (talhelper)

**What it does**: Validates talconfig.yaml structure and patch files

**Command**: `talhelper validate talconfig talos/talconfig.yaml`

**Checks**:
- talconfig.yaml structure
- Patch files exist
- Node definitions complete
- Version compatibility

**When it fails**: Invalid Talos configuration

**Fix**: Check talconfig.yaml syntax, verify patches directory

## Template Rendering Pipeline

**Source templates**: `templates/config/`

**Makejinja configuration**: `makejinja.toml`

**Custom plugin**: `templates/scripts/plugin.py`

**Flow**:
```
cluster.yaml + nodes.yaml
    ↓
Makejinja reads templates/config/
    ↓
plugin.py provides filters/functions
    ↓
Jinja2 renders with #{ variable }# syntax
    ↓
Output to bootstrap/, kubernetes/, talos/
```

**Example template** (talconfig.yaml.j2):
```yaml
endpoint: https://#{ cluster_api_addr }#:6443
#% for node in nodes %#
  - hostname: "#{ node.name }#"
    ipAddress: "#{ node.address }#"
#% endfor %#
```

**Rendered output** (talconfig.yaml):
```yaml
endpoint: https://192.168.1.101:6443
  - hostname: "k8s-1"
    ipAddress: "192.168.1.10"
  - hostname: "k8s-2"
    ipAddress: "192.168.1.11"
```

## Talos Management Tasks

### Generate Config
**Command**: `task talos:generate-config`

**When**: After modifying talconfig.yaml or patch files

**What it does**: Regenerates machine configs from talconfig.yaml

**Output**: Updates talos/clusterconfig/*.yaml

### Apply to Node
**Command**: `task talos:apply-node IP=192.168.1.10 MODE=auto`

**When**: After config changes need applying to specific node

**Modes**:
- `auto` - Automatically determine changes
- `staged` - Stage config, apply on next reboot
- `no-reboot` - Apply without reboot (limited changes only)

**What it does**: Applies new configuration to node, optionally reboots

### Upgrade Node
**Command**: `task talos:upgrade-node IP=192.168.1.10`

**When**: Upgrading Talos OS version

**What it does**:
1. Reads `talosVersion` from talenv.yaml
2. Upgrades node to that version
3. Waits for node to be Ready
4. Preserves data (non-destructive)

### Upgrade Kubernetes
**Command**: `task talos:upgrade-k8s`

**When**: Upgrading Kubernetes version

**What it does**:
1. Reads `kubernetesVersion` from talenv.yaml
2. Upgrades all control plane nodes
3. Upgrades all worker nodes
4. Rolling upgrade (one node at a time)

**Precondition**: Update `kubernetesVersion` in talenv.yaml first

### Reset Cluster
**Command**: `task talos:reset`

**When**: Destructive - rebuilding cluster from scratch

**What it does**: Resets all nodes to maintenance mode (DELETES ALL DATA)

**Warning**: This is destructive! Only use when intentionally rebuilding cluster.

## Task File Structure

```
.taskfiles/
├── template/
│   ├── Taskfile.yaml         # Rendering and validation
│   └── resources/
│       ├── *.schema.cue      # CUE schemas
│       └── kubeconform.sh    # K8s validation script
├── talos/
│   └── Taskfile.yaml         # Talos operations
└── bootstrap/
    └── Taskfile.yaml         # Bootstrap operations
```

**Root Taskfile.yml** includes all via:
```yaml
includes:
  bootstrap: .taskfiles/bootstrap
  talos: .taskfiles/talos
  template: .taskfiles/template
```

**Namespace usage**: `task template:configure`, `task talos:upgrade-k8s`

## Common Task Scenarios

### Scenario 1: Adding new Kubernetes app

```bash
# 1. Create app manifests in kubernetes/apps/{namespace}/{app}/

# 2. Re-render and validate
task configure

# 3. Commit and push
git add -A && git commit -m "feat: add new app"
git push

# 4. Reconcile (or wait for auto-sync)
task reconcile
```

### Scenario 2: Changing Talos configuration

```bash
# 1. Edit talos/patches/ files

# 2. Regenerate configs
task talos:generate-config

# 3. Apply to specific node
task talos:apply-node IP=192.168.1.10 MODE=auto

# 4. Verify
talosctl -n 192.168.1.10 get config
```

### Scenario 3: Upgrading cluster versions

```bash
# 1. Edit talenv.yaml (update kubernetesVersion)

# 2. Upgrade Kubernetes
task talos:upgrade-k8s

# 3. Edit talenv.yaml (update talosVersion)

# 4. Upgrade each node
task talos:upgrade-node IP=192.168.1.10
task talos:upgrade-node IP=192.168.1.11
# ... repeat for all nodes
```

### Scenario 4: Debugging cluster issues

```bash
# Check overall status
task template:debug

# Check Flux status
flux check
flux get ks -A
flux get hr -A

# Check Talos health
talosctl -n 192.168.1.10 health

# Check node status
kubectl get nodes
kubectl get pods -A
```

## Security Considerations

### Never Run Destructive Tasks Without Review

**Destructive tasks**:
- `task talos:reset` - Deletes all cluster data
- `task template:reset` - Deletes all rendered configs

**Before running**:
1. Verify you're in correct repository
2. Check kubeconfig context
3. Understand impact (data loss)

### Always Encrypt Secrets Before Commit

**Safe workflow**:
```bash
# 1. Run configure (includes encryption)
task configure

# 2. Verify all *.sops.* files encrypted
find . -name "*.sops.*" -exec sops filestatus {} \;

# 3. Only commit if all encrypted
git add -A && git commit -m "..."
```

**Never**:
- Commit unencrypted `*.sops.*` files
- Push age.key to public repository
- Share SOPS_AGE_KEY_FILE in logs/messages

### Validate Before Applying

**Pattern**:
```bash
# 1. Render locally
task configure

# 2. Review changes
git diff

# 3. Test in dev cluster first (if available)

# 4. Apply to production
task reconcile
```

## Key Insights

1. **Linear workflow** - Can't skip stages (init → configure → bootstrap → manage)
2. **Configure is central** - Run before every commit (renders + validates + encrypts)
3. **Bootstrap is one-time** - After Flux takes over, use reconcile for changes
4. **Validation is multi-layered** - Schema → Render → Encrypt → K8s → Talos
5. **Talos tasks are powerful** - apply-node, upgrade-node can reboot nodes
6. **Destructive tasks need care** - reset, template:reset delete data
7. **Idempotent design** - Safe to re-run configure, bootstrap without breaking cluster

## Quick Reference

| Command | Purpose | Safe to re-run? |
|---------|---------|-----------------|
| `task init` | Generate initial configs | Yes (skips existing) |
| `task configure` | Render + validate + encrypt | Yes (idempotent) |
| `task bootstrap:talos` | Install Talos | Yes (skips if running) |
| `task bootstrap:apps` | Deploy core services | Yes (idempotent) |
| `task reconcile` | Force Flux sync | Yes |
| `task template:debug` | Show cluster status | Yes (read-only) |
| `task talos:apply-node` | Apply config to node | Yes (with MODE=auto) |
| `task talos:upgrade-node` | Upgrade Talos version | Yes (one node at a time) |
| `task talos:upgrade-k8s` | Upgrade Kubernetes | Yes (rolling upgrade) |
| `task talos:reset` | Reset cluster | **NO (destructive)** |
| `task template:reset` | Delete rendered files | **NO (destructive)** |
| `task template:tidy` | Archive templates | **NO (moves files)** |
