# Grafana Dashboard Launcher

Interactive CLI tool for discovering and opening Grafana dashboards from the homelab monitoring stack with automatic URL detection and dashboard selection.

## Overview

The Dashboard Launcher provides a seamless way to access Grafana dashboards without hardcoding URLs or manually navigating the web interface. It automatically discovers all available dashboards from the GitOps configuration and presents them in an interactive selection interface.

## Features

- **Auto-discovery**: Scans monitoring stack configuration for dashboard JSON files
- **Dynamic URL detection**: Finds Grafana URL from Kubernetes ingress (supports Tailscale)
- **Interactive selection**: Uses fzf for user-friendly dashboard picker
- **Alphabetical ordering**: Lists dashboards in sorted order for easy browsing
- **Cross-platform browser**: Opens dashboards in default browser (macOS/Linux/Windows)
- **Proper URL generation**: Uses dashboard UIDs when available, falls back to title slugs
- **GitOps integration**: Works with the existing dashboard deployment pipeline

## Installation

The dashboard launcher is included in the homelab repository and requires:

- **Deno runtime**: For script execution
- **kubectl**: Configured to access the homelab cluster
- **fzf**: For interactive dashboard selection

```bash
# Install fzf if not already available
brew install fzf  # macOS
apt install fzf    # Ubuntu/Debian
```

## Usage

### Quick Start

```bash
# Launch interactive dashboard selector
deno task dashboard
```

### Direct Execution

```bash
# Run script directly
./scripts/dashboard-launcher.ts
```

### Example Session

```
🔍 Discovering Grafana dashboards...
Found 5 dashboards
Grafana URL: https://grafana.walleye-monster.ts.net

📊 Available dashboards:
  1. Ceph - OSD (Single) (ceph-osd.json)
  2. Ceph - Pools (ceph-pools.json)
  3. Ceph Cluster (ceph-cluster.json)
  4. Homelab Critical Apps Monitoring (loki-dashboard.json)
  5. Homelab Logging Overview (homelab-logging.json)

> Select dashboard: [fzf interface appears]
```

## How It Works

### 1. Dashboard Discovery

The tool scans the GitOps configuration directory:
```
kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/
```

It automatically detects JSON files and extracts:
- Dashboard UID (preferred for URLs)
- Dashboard title
- File name for reference

### 2. Grafana URL Detection

Dynamically finds the Grafana URL by querying Kubernetes:

```bash
# Checks ingress status for hostname
kubectl get ingress -n monitoring grafana-tailscale-ingress -o json
```

Supports multiple ingress types:
- **Tailscale ingress**: Reads hostname from `status.loadBalancer.ingress[].hostname`
- **Standard ingress**: Uses `spec.rules[].host`
- **Service discovery**: Falls back to service status if needed

### 3. URL Generation

Creates proper Grafana dashboard URLs:

```
https://grafana.walleye-monster.ts.net/d/{uid}/{uid}
```

Examples:
- `https://grafana.walleye-monster.ts.net/d/homelab-logging/homelab-logging`
- `https://grafana.walleye-monster.ts.net/d/tbO9LAiZK/tbO9LAiZK`

### 4. Browser Integration

Opens dashboards using platform-specific commands:
- **macOS**: `open {url}`
- **Linux**: `xdg-open {url}`
- **Windows**: `start {url}`

## Current Dashboards

The homelab monitoring stack includes these dashboards:

| Dashboard | Description | Folder | UID |
|-----------|-------------|--------|-----|
| **Ceph Cluster** | Overall Ceph cluster health and performance | Ceph | `tbO9LAiZK` |
| **Ceph - OSD (Single)** | Individual OSD monitoring and troubleshooting | Ceph | `Fj5fAfzik` |
| **Ceph - Pools** | Ceph storage pool utilization and performance | Ceph | `-gtf0Bzik` |
| **Homelab Critical Apps Monitoring** | Key application and service monitoring | Logging | `homelab-critical-apps-v2` |
| **Homelab Logging Overview** | Logging stack health and log volume metrics | Homelab | `homelab-logging` |

## Configuration

### Dashboard Integration

Dashboards are automatically discovered from the Kustomize configuration:

```yaml
# kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/kustomization.yaml
configMapGenerator:
  - name: grafana-dashboard-ceph-cluster
    files:
      - ceph-cluster.json
    options:
      labels:
        grafana_dashboard: "1"        # Required for Grafana sidecar
      annotations:
        grafana_folder: "Ceph"        # Dashboard organization
```

### Adding New Dashboards

To add a new dashboard to the launcher:

1. **Place JSON file** in the dashboards directory:
   ```
   kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/my-dashboard.json
   ```

2. **Add to kustomization.yaml**:
   ```yaml
   - name: grafana-dashboard-my-dashboard
     files:
       - my-dashboard.json
     options:
       labels:
         grafana_dashboard: "1"
       annotations:
         grafana_folder: "Custom"
   ```

3. **Commit and deploy** via GitOps - the launcher will automatically discover it

### Supported Dashboard Formats

The launcher expects standard Grafana dashboard JSON with these fields:

```json
{
  "uid": "unique-dashboard-id",           // Preferred for URL generation
  "title": "Dashboard Display Name",      // Used for listing and fallback URLs
  "description": "Dashboard description",  // Optional
  "tags": ["monitoring", "homelab"],      // Optional
  // ... rest of dashboard configuration
}
```

## Troubleshooting

### Common Issues

**Dashboard not found**:
```
No dashboards found in the monitoring stack
```
- Verify JSON files exist in the dashboards directory
- Check file permissions and JSON syntax

**Grafana URL detection failed**:
```
Failed to find Grafana URL: Grafana ingress not found
```
- Ensure kubectl is configured and connected to the cluster
- Verify the monitoring namespace exists
- Check that the Grafana ingress is deployed and has a hostname

**fzf not available**:
```
fzf selection failed: command not found
```
- Install fzf: `brew install fzf` (macOS) or `apt install fzf` (Linux)

**Browser opening failed**:
```
Failed to open browser: permission denied
```
- The URL will be displayed for manual copying
- Check default browser configuration

### Debugging

Enable verbose output by running the script directly:

```bash
# Check dashboard discovery
ls kubernetes/apps/monitoring/kube-prometheus-stack/app/dashboards/*.json

# Verify Grafana ingress
kubectl get ingress -n monitoring grafana-tailscale-ingress -o yaml

# Test fzf functionality
echo "test" | fzf --prompt="Test: "
```

## Integration with Homelab

### GitOps Workflow

The dashboard launcher integrates with the existing GitOps deployment pipeline:

1. **Dashboard JSON files** stored in Git
2. **Kustomize** generates ConfigMaps with proper labels
3. **Flux** deploys ConfigMaps to the cluster
4. **Grafana sidecar** discovers and loads dashboards
5. **Dashboard launcher** finds and opens dashboards

### Monitoring Stack Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Dashboard JSON  │───▶│ Kustomize        │───▶│ Kubernetes      │
│ Files (Git)     │    │ ConfigMaps       │    │ ConfigMaps      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        │
┌─────────────────┐    ┌──────────────────┐            │
│ Browser         │◄───│ Dashboard        │◄───────────┘
│ (User)          │    │ Launcher CLI     │
└─────────────────┘    └──────────────────┘
                                │
                       ┌──────────────────┐
                       │ Grafana Instance │
                       │ (Tailscale)      │
                       └──────────────────┘
```

### Script Location

The dashboard launcher is part of the homelab script collection:

```
scripts/
├── dashboard-launcher.ts          # Main dashboard launcher
├── cli/homelab.ts                # Central CLI entrypoint
└── README.md                     # Script documentation
```

Integrated into the Deno task runner:

```json
{
  "tasks": {
    "dashboard": "deno run --allow-all scripts/dashboard-launcher.ts"
  }
}
```

## Future Enhancements

Potential improvements for the dashboard launcher:

- **Dashboard favorites**: Remember frequently accessed dashboards
- **Time range support**: Open dashboards with specific time ranges
- **Search functionality**: Filter dashboards by keywords or tags
- **Dashboard thumbnails**: Preview dashboard content before opening
- **Bulk operations**: Open multiple related dashboards simultaneously
- **Custom URLs**: Support for custom dashboard parameters and variables