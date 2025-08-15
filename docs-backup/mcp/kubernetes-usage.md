# MCP Server Kubernetes Usage Guide

This guide explains how to use the MCP (Model Context Protocol) Server for Kubernetes with Claude Code in the Anton homelab cluster.

## Overview

The MCP Server Kubernetes provides Claude with direct access to kubectl commands and Kubernetes management capabilities. This enables Claude to help with cluster operations, troubleshooting, and deployments without you having to manually run commands and paste outputs.

## Setup Status

✅ **Already Configured**: The Kubernetes MCP server is installed in your project:
```bash
$ claude mcp list
kubernetes: npx mcp-server-kubernetes
```

## Available Tools

When using Claude Code with MCP enabled, Claude has access to these Kubernetes tools:

### Resource Management
- **kubectl_get**: Retrieve resources (pods, services, deployments, etc.)
- **kubectl_describe**: Get detailed information about resources
- **kubectl_list**: List resources in namespaces
- **kubectl_create**: Create new resources from YAML
- **kubectl_apply**: Apply configuration changes
- **kubectl_delete**: Remove resources (if not in non-destructive mode)
- **kubectl_logs**: View container logs
- **kubectl_scale**: Scale deployments
- **kubectl_patch**: Update specific resource fields
- **kubectl_rollout**: Manage deployment rollouts

### Cluster Operations
- **kubectl_context**: Switch between clusters/contexts
- **explain_resource**: Get documentation for resource types
- **list_api_resources**: Discover available APIs
- **port_forward**: Forward local ports to pods/services

### Helm Operations (if installed)
- **helm_install**: Install Helm charts
- **helm_upgrade**: Upgrade releases
- **helm_list**: List installed releases

## Usage with Claude

### Enable MCP in Your Session

Start Claude Code with MCP support:
```bash
claude
```

Then use the `/mcp` command to interact with Kubernetes:
```
/mcp
```

### Example Interactions

Here are practical examples for your Anton cluster:

#### Check Cluster Health
Ask Claude: "Check the health of all nodes and critical system pods"

Claude can then use:
- `kubectl_get` to check node status
- `kubectl_get` to verify system pods in kube-system
- `kubectl_describe` for any unhealthy resources

#### Debug Failed Deployments
Ask Claude: "Why is the echo-2 deployment failing in the default namespace?"

Claude can:
- Use `kubectl_get` to check deployment status
- Use `kubectl_describe` to get events and conditions
- Use `kubectl_logs` to check pod logs
- Use `kubectl_get` to check HelmRelease status

#### Monitor Resources
Ask Claude: "Show me the resource usage across all namespaces"

Claude can:
- Use `kubectl_get` with resource metrics
- List pods with resource requests/limits
- Check PVC usage

#### Flux GitOps Operations
Ask Claude: "Check the status of all Flux resources and reconcile if needed"

Claude can:
- Use `kubectl_get` to check Kustomizations
- Use `kubectl_get` to check HelmReleases
- Use `kubectl_describe` for failed resources
- Suggest reconciliation commands

## Safety Modes

### Full Access Mode (Current)
Your current configuration allows all operations:
```json
{
  "env": {
    "ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS": "false"
  }
}
```

### Non-Destructive Mode (Safer)
To prevent accidental deletions, update to:
```bash
claude mcp remove kubernetes -s local
claude mcp add kubernetes npx mcp-server-kubernetes --env ALLOW_ONLY_NON_DESTRUCTIVE_TOOLS=true
```

This allows:
- ✅ All read operations (get, describe, list, logs)
- ✅ Create and update operations
- ❌ Delete operations

## Practical Workflows

### 1. Deployment Troubleshooting
```
You: "The airflow deployment isn't starting properly"

Claude will:
1. Check HelmRelease status
2. Examine pod events
3. Review container logs
4. Check resource constraints
5. Verify dependencies
```

### 2. Resource Monitoring
```
You: "Monitor Ceph storage health"

Claude will:
1. Check Ceph cluster pods
2. Examine PVC usage
3. Review storage class configuration
4. Check for any storage-related events
```

### 3. GitOps Verification
```
You: "Verify all Flux resources are synced"

Claude will:
1. List all Kustomizations
2. Check Git repository sync status
3. Identify any failed HelmReleases
4. Suggest reconciliation steps
```

### 4. Quick Diagnostics
```
You: "Why can't I access the Grafana dashboard?"

Claude will:
1. Check ingress configuration
2. Verify service endpoints
3. Examine pod health
4. Review tailscale-operator status
5. Check DNS resolution
```

## Best Practices

### 1. Be Specific
Instead of: "Check the cluster"
Use: "Check if all pods in the monitoring namespace are healthy"

### 2. Provide Context
Instead of: "Debug the error"
Use: "Debug why the external-secrets pod is in CrashLoopBackOff"

### 3. Use for Verification
After manual changes, ask: "Verify that my Ceph storage configuration was applied correctly"

### 4. Combine with Local Knowledge
Claude has access to your CLAUDE.md and project structure, so you can ask: "Use the monitoring scripts to check cluster health and compare with live kubectl data"

## Limitations

1. **No Interactive Commands**: Can't run interactive shells or edit modes
2. **No Direct File Edits**: Can't edit files on cluster nodes
3. **Timeout Constraints**: Long-running operations may timeout
4. **Context Bound**: Uses your current kubectl context (admin@anton)

## Advanced Usage

### Custom Contexts
If you need to work with multiple clusters:
```bash
# Add a context-specific server
claude mcp add k8s-staging npx mcp-server-kubernetes --env KUBECONFIG=/path/to/staging/config
```

### Debugging MCP Issues
If MCP isn't working:
1. Check kubectl works: `kubectl get nodes`
2. Verify MCP config: `claude mcp get kubernetes`
3. Restart Claude Code
4. Check for npx/npm issues: `npx mcp-server-kubernetes --version`

## Integration with Homelab Scripts

Claude can combine MCP kubectl access with your existing scripts:
- Run monitoring scripts and cross-verify with live data
- Use kubectl to check resources before running maintenance scripts
- Validate Talos node status alongside Kubernetes health

## Security Notes

1. **Cluster Access**: MCP uses your existing kubeconfig and permissions
2. **Audit Trail**: All kubectl commands are logged by the cluster
3. **No Credential Storage**: MCP doesn't store any credentials
4. **Context Isolation**: Only accesses the current kubectl context

## Quick Reference Card

```bash
# Common Claude + MCP requests for Anton cluster:

"Check all flux resources and their sync status"
"Why is the Ceph dashboard not accessible?"
"Show me resource usage for all nodes"
"Debug the failing pod in the airflow namespace"
"List all PVCs and their usage percentage"
"Check if all critical system components are healthy"
"Verify the external-secrets operator is working"
"Show recent events in the storage namespace"
"Check ingress configuration for all namespaces"
"Monitor the rollout of the latest deployment"
```

## Troubleshooting

### MCP Not Available
```bash
# Verify installation
claude mcp list

# Re-add if missing
claude mcp add kubernetes npx mcp-server-kubernetes
```

### Kubectl Errors
```bash
# Verify kubectl config
kubectl config current-context
kubectl auth can-i --list
```

### Permission Denied
- Check your kubeconfig has proper permissions
- Verify the cluster role bindings
- Ensure Talos node certificates are valid

---

This MCP integration significantly enhances Claude's ability to help with your Kubernetes operations, making it a powerful assistant for managing your Anton homelab cluster.