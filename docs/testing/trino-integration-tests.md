# Trino Integration Tests

## Overview

Comprehensive integration test suite for Trino that validates all aspects of functionality including web UI access, query execution, catalog integration, and performance benchmarks.

## Quick Start

```bash
# Run all tests (human-readable output)
deno task test:trino

# Quick tests only (skip advanced queries)
deno task test:trino:quick

# JSON output for CI/CD
deno task test:trino:json

# Verbose output for debugging
deno task test:trino:verbose
```

## Test Categories

### 1. Connectivity Tests
- **Web UI Access**: Validates HTTPS access without HTTP 406 errors
- **Coordinator Pod Health**: Ensures Trino coordinator is running
- **Service Connectivity**: Verifies Kubernetes service configuration

### 2. Basic Query Tests
- **Simple SELECT**: Basic SQL functionality (`SELECT 1`)
- **System Functions**: Current timestamp, basic operations
- **Catalog Discovery**: `SHOW CATALOGS` validation
- **System Introspection**: Node information queries

### 3. Catalog Functionality Tests
- **TPCH Catalog**: Validates built-in benchmark data
  - Schema exploration (`SHOW SCHEMAS IN tpch`)
  - Table listing (`SHOW TABLES FROM tpch.tiny`)
  - Data queries (customer/nation counts)
- **Iceberg Catalog**: Tests data lake integration
- **System Catalog**: Runtime information access

### 4. Advanced Query Tests *(Skipped in --quick mode)*
- **Complex Joins**: Multi-table joins with aggregations
- **Window Functions**: Ranking and analytical functions
- **JSON Operations**: JSON data type handling
- **Date Functions**: Date/time manipulation and extraction

### 5. Performance Benchmarks
- **Query Execution Times**: Validates performance thresholds
  - Quick SELECT: < 1 second
  - Catalog listing: < 2 seconds  
  - Small aggregation: < 3 seconds
  - Medium aggregation: < 5 seconds
- **Performance Metrics**: Execution time tracking and analysis

### 6. Configuration Validation
- **HTTP Forwarded Headers**: Verifies `http-server.process-forwarded=true` is set
- **No Header Rejection**: Confirms no X-Forwarded-For errors in logs
- **Security Configuration**: Validates proxy header trust settings

## Output Formats

### Human-Readable Output
```
🎯 TRINO INTEGRATION TEST RESULTS
============================================================

📊 Summary:
┌─────────────────────┬───────┐
│ Metric              │ Value │
├─────────────────────┼───────┤
│ Total Tests         │ 23    │
│ ✅ Passed           │ 22    │
│ ⚠️ Warnings         │ 1     │
│ ❌ Failed           │ 0     │
│ 💥 Errors           │ 0     │
│ Total Duration      │ 3450ms│
│ Average Query Time  │ 145ms │
└─────────────────────┴───────┘

📋 CONNECTIVITY Tests:
┌─────────────────────┬────────┬──────────┬─────────────────────────────┐
│ Test                │ Status │ Duration │ Details                     │
├─────────────────────┼────────┼──────────┼─────────────────────────────┤
│ Web UI Access       │ ✅ pass│ 234ms    │ HTTP 200 - UI accessible   │
│ Coordinator Pod     │ ✅ pass│ 45ms     │ Pod status: Running         │
│ Service Connectivity│ ✅ pass│ 23ms     │ Service IP: 10.43.123.45   │
└─────────────────────┴────────┴──────────┴─────────────────────────────┘
```

### JSON Output
```json
{
  "summary": {
    "totalTests": 23,
    "passed": 22,
    "warnings": 1,
    "failed": 0,
    "errors": 0,
    "totalDuration": 3450,
    "criticalIssues": [],
    "performanceMetrics": {
      "avgQueryTime": 145,
      "maxQueryTime": 892,
      "minQueryTime": 45
    }
  },
  "results": [
    {
      "name": "Web UI Access",
      "category": "connectivity",
      "status": "pass",
      "duration": 234,
      "details": "HTTP 200 - UI accessible",
      "metrics": {
        "httpStatus": 200,
        "responseTime": 234
      }
    }
  ],
  "timestamp": "2025-06-16T12:00:00.000Z"
}
```

## Exit Codes

- **0**: All tests passed successfully
- **1**: Tests passed with warnings (non-critical issues)
- **2**: Critical test failures detected
- **3**: Test execution errors (script/connectivity issues)

## Integration with Test Suite

The Trino test is automatically included in the comprehensive test suite:

```bash
# Run all cluster tests (includes Trino)
deno task test:all

# JSON output for CI/CD
deno task test:all:json
```

## Troubleshooting

### Common Issues

1. **HTTP 406 Error**
   - **Symptom**: Web UI test fails with 406 status
   - **Cause**: `http-server.process-forwarded=true` not set
   - **Fix**: Apply the ConfigMap patch or update HelmRelease

2. **Coordinator Pod Not Found**
   - **Symptom**: "No coordinator pod found" error
   - **Cause**: Trino deployment not running
   - **Fix**: Check Flux deployment status

3. **Query Timeouts**
   - **Symptom**: SQL queries fail with timeout
   - **Cause**: Coordinator overloaded or misconfigured
   - **Fix**: Check coordinator logs and resource usage

4. **Iceberg Catalog Warnings**
   - **Symptom**: Iceberg tests show warnings
   - **Cause**: Catalog not fully configured yet
   - **Fix**: Complete Iceberg/Nessie setup (non-critical)

### Debugging Commands

```bash
# Check coordinator pod status
kubectl get pods -n data-platform -l app.kubernetes.io/component=coordinator

# View coordinator logs
kubectl logs -n data-platform -l app.kubernetes.io/component=coordinator --tail=50

# Test direct SQL access
kubectl exec -n data-platform deployment/trino-coordinator -- trino --execute "SELECT 1"

# Check configuration
kubectl get configmap trino-coordinator -n data-platform -o yaml | grep -A 10 "config.properties"
```

## Test Development

### Adding New Tests

To add new test categories, modify `scripts/test-trino-integration.ts`:

1. Create new test method (e.g., `testNewFeature()`)
2. Add to test suites array in `runTests()`
3. Follow existing patterns for error handling and metrics
4. Update documentation with new test descriptions

### Performance Baselines

Update performance thresholds based on cluster capacity:

```typescript
const benchmarks = [
  { name: "Quick SELECT", sql: "SELECT 1", maxTime: 1000 },
  { name: "Your New Test", sql: "SELECT ...", maxTime: 3000 }
];
```

## Related Documentation

- [Trino HTTP 406 Fix](../troubleshooting/trino-http-406-fix.md)
- [Trino Discovery Queries](../data-platform/trino-discovery-queries.md)
- [Data Platform Health Monitoring](../monitoring/data-platform-health.md)