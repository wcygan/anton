# logcli Usage Guide

logcli is the official command-line client for Loki, enabling you to query logs directly from the terminal. This guide covers installation, common queries, and integration with your homelab cluster.

## Installation

### macOS (Already Installed)
```bash
# Via Homebrew (if needed)
brew install loki

# Or download directly
curl -O -L "https://github.com/grafana/loki/releases/latest/download/logcli-darwin-amd64.zip"
unzip logcli-darwin-amd64.zip
chmod +x logcli-darwin-amd64
sudo mv logcli-darwin-amd64 /usr/local/bin/logcli
```

## Using the Wrapper Script

The homelab includes a convenient wrapper script that handles port-forwarding automatically:

```bash
# Basic usage
./scripts/logcli-wrapper.ts <command> [options]

# Examples
./scripts/logcli-wrapper.ts query '{namespace="storage"}' --limit 100
./scripts/logcli-wrapper.ts labels
./scripts/logcli-wrapper.ts query --tail '{app="rook-ceph-rgw"}'
```

## Common Queries

### Basic Label Queries

```bash
# List all available labels
./scripts/logcli-wrapper.ts labels

# List values for a specific label
./scripts/logcli-wrapper.ts labels namespace
./scripts/logcli-wrapper.ts labels pod

# Query by namespace
./scripts/logcli-wrapper.ts query '{namespace="storage"}'
./scripts/logcli-wrapper.ts query '{namespace="flux-system"}'
./scripts/logcli-wrapper.ts query '{namespace="monitoring"}'
```

### Error Detection

```bash
# Find all errors across namespaces
./scripts/logcli-wrapper.ts query '{namespace=~".+"} |~ "error|Error|ERROR"' --limit 100

# Specific namespace errors
./scripts/logcli-wrapper.ts query '{namespace="storage"} |~ "error|Error|ERROR"'

# Rook-Ceph specific errors
./scripts/logcli-wrapper.ts query '{app="rook-ceph-rgw"} |= "error"'

# Pod crashes and failures
./scripts/logcli-wrapper.ts query '{namespace=~".+"} |~ "CrashLoopBackOff|Error|Failed"'
```

### Time-Based Queries

```bash
# Last hour
./scripts/logcli-wrapper.ts query --from=1h '{namespace="monitoring"}'

# Last 24 hours
./scripts/logcli-wrapper.ts query --from=24h --to=now '{namespace="storage"}'

# Specific time range (RFC3339)
./scripts/logcli-wrapper.ts query \
  --from="2025-06-10T20:00:00Z" \
  --to="2025-06-10T21:00:00Z" \
  '{namespace="flux-system"}'

# Last 5 minutes with limit
./scripts/logcli-wrapper.ts query --from=5m --limit=50 '{job="monitoring/alloy"}'
```

### Streaming Logs (Tail)

```bash
# Stream all logs from a namespace
./scripts/logcli-wrapper.ts query --tail '{namespace="storage"}'

# Stream with filter
./scripts/logcli-wrapper.ts query --tail '{namespace="monitoring"} |= "error"'

# Stream from specific app
./scripts/logcli-wrapper.ts query --tail '{app="rook-ceph-rgw"}'

# Stream with delay (reduce load)
./scripts/logcli-wrapper.ts query --tail --delay-for=2s '{namespace="flux-system"}'
```

### Advanced LogQL Queries

```bash
# JSON parsing
./scripts/logcli-wrapper.ts query '{job="monitoring/alloy"} | json' --limit 10

# Extract specific JSON fields
./scripts/logcli-wrapper.ts query '{namespace="storage"} | json | level="error"'

# Pattern extraction
./scripts/logcli-wrapper.ts query '{namespace="flux-system"} |~ "reconciliation failed" | pattern "<_> reconciliation failed for <resource>"'

# Line format (reformat output)
./scripts/logcli-wrapper.ts query '{namespace="default"} | line_format "{{.namespace}} {{.pod}} {{.msg}}"'
```

### Aggregation Queries

```bash
# Count logs by namespace (last hour)
./scripts/logcli-wrapper.ts query --from=1h --stats \
  'sum by (namespace) (count_over_time({namespace=~".+"}[5m]))'

# Rate of errors
./scripts/logcli-wrapper.ts query --from=1h --stats \
  'rate({namespace="storage"} |~ "error" [5m])'

# Top 10 pods by log volume
./scripts/logcli-wrapper.ts query --from=1h --stats \
  'topk(10, sum by (pod) (count_over_time({pod=~".+"}[1h])))'
```

## Output Formats

```bash
# Default (human-readable with timestamps)
./scripts/logcli-wrapper.ts query '{namespace="storage"}' --limit 5

# Raw (log lines only)
./scripts/logcli-wrapper.ts query --output=raw '{namespace="storage"}' --limit 5

# JSON Lines (for processing)
./scripts/logcli-wrapper.ts query --output=jsonl '{namespace="storage"}' --limit 5
```

## Useful Flags

```bash
--limit <n>         # Limit number of entries (default 30)
--from <time>       # Start time (e.g., 1h, 2d, 2025-06-10T20:00:00Z)
--to <time>         # End time (default: now)
--tail              # Stream logs in real-time
--delay-for <time>  # Delay between queries when tailing (default 0s)
--forward           # Show oldest logs first (default: newest first)
--no-labels         # Don't print labels
--quiet             # Suppress info messages
--stats             # Show query statistics
--output <format>   # Output format: default, jsonl, raw
```

## Integration with Other Tools

### Export to File
```bash
# Export errors to file
./scripts/logcli-wrapper.ts query --output=raw --from=24h \
  '{namespace=~".+"} |~ "error"' > errors-$(date +%Y%m%d).log

# Export as JSON for analysis
./scripts/logcli-wrapper.ts query --output=jsonl --from=1h \
  '{namespace="storage"}' > storage-logs.jsonl
```

### Pipe to Analysis Tools
```bash
# Count unique errors
./scripts/logcli-wrapper.ts query --output=raw --from=1h \
  '{namespace="storage"} |~ "error"' | sort | uniq -c | sort -nr

# Extract and count HTTP status codes
./scripts/logcli-wrapper.ts query --output=raw --from=1h \
  '{app="ingress-nginx"} |~ "HTTP/[0-9.]+" [0-9]{3}' | \
  grep -oE 'HTTP/[0-9.]+" [0-9]{3}' | sort | uniq -c
```

### Watch for Specific Events
```bash
# Watch for pod deletions
./scripts/logcli-wrapper.ts query --tail \
  '{namespace="kube-system"} |= "Killing container"'

# Watch for Flux reconciliations
./scripts/logcli-wrapper.ts query --tail \
  '{namespace="flux-system"} |= "reconciliation finished"'
```

## Troubleshooting

### Connection Issues
```bash
# Test connectivity
logcli --addr=http://localhost:3100 labels

# Check if port-forward is active
lsof -i :3100

# Manual port-forward
kubectl port-forward -n monitoring svc/loki-gateway 3100:80
```

### No Results
```bash
# Check available time range
./scripts/logcli-wrapper.ts query --from=24h --limit=1 '{namespace=~".+"}'

# Verify labels exist
./scripts/logcli-wrapper.ts labels
./scripts/logcli-wrapper.ts labels namespace

# Check Alloy is collecting logs
kubectl logs -n monitoring -l app.kubernetes.io/name=alloy --tail=50
```

### Performance Tips

1. **Use Time Ranges**: Always specify `--from` to limit the search window
2. **Use Labels**: Filter by labels before using regex patterns
3. **Limit Results**: Use `--limit` to avoid overwhelming output
4. **Stream Carefully**: Use `--delay-for` when tailing to reduce load

## Testing

Run the integration tests:
```bash
# Test logcli functionality
./scripts/test-loki-logcli.ts

# Run complete logging tests
deno test tests/integration/logging-stack.test.ts
```

## Examples for Common Tasks

### Debug Failing Pods
```bash
# Find pods in error state
./scripts/logcli-wrapper.ts query --from=1h \
  '{namespace=~".+"} |~ "CrashLoopBackOff|Error|Failed|OOMKilled"'
```

### Monitor Deployments
```bash
# Watch new deployments
./scripts/logcli-wrapper.ts query --tail \
  '{namespace=~".+"} |= "Scaled up replica set"'
```

### Audit Security Events
```bash
# Failed authentication attempts
./scripts/logcli-wrapper.ts query --from=24h \
  '{namespace=~".+"} |~ "authentication failed|unauthorized|forbidden"'
```

### Storage Health
```bash
# Ceph health warnings
./scripts/logcli-wrapper.ts query --from=1h \
  '{namespace="storage"} |~ "HEALTH_WARN|slow requests|degraded"'
```