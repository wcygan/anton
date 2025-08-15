# Airflow Elasticsearch Logging Integration

> **📝 NOTE**: This is an alternative approach that was not implemented.  
> We chose Alloy + Loki instead for better integration with our existing logging stack.  
> See [Airflow Alloy Logging](./airflow-alloy-logging.md) for the actual implementation.

---

# Alternative Approach: Airflow Elasticsearch Logging Integration

## Overview

This document covers how to enhance your Airflow deployment to use Elasticsearch
for centralized logging. Elasticsearch integration provides several advantages
over local file logging:

- **Centralized Log Management**: All logs are stored in a searchable,
  centralized location
- **Log Retention**: Configurable retention policies and index lifecycle
  management
- **Advanced Search**: Powerful query capabilities through Kibana or
  Elasticsearch APIs
- **Scalability**: Handle large volumes of logs across multiple Airflow
  components
- **Integration**: Works well with existing log aggregation pipelines

## Logging Strategies

Airflow supports multiple approaches for Elasticsearch logging:

### 1. Direct Write to Elasticsearch

Airflow writes logs directly to Elasticsearch without intermediate log shippers.

**Pros:**

- Simple configuration
- Real-time log availability
- No additional infrastructure needed

**Cons:**

- Direct coupling between Airflow and Elasticsearch
- Potential performance impact on tasks
- No log buffering or retry mechanisms

### 2. Log Shipping Approach

Logs are written to stdout/files and shipped to Elasticsearch by external agents
(Fluentd, Filebeat, etc.).

**Pros:**

- Decoupled architecture
- Better error handling and buffering
- Can process/transform logs before indexing
- Works with existing log aggregation pipelines

**Cons:**

- More complex setup
- Additional infrastructure components
- Potential log delivery delays

### 3. Hybrid Approach

Combination of persistent volume logging (as fallback) and Elasticsearch
integration.

**Pros:**

- Best of both worlds
- Fallback mechanism if Elasticsearch is unavailable
- Gradual migration path

**Cons:**

- Higher storage requirements
- More complex configuration

## Configuration Options

### Helm Chart Configuration

The Airflow Helm chart provides built-in support for Elasticsearch logging
through the `elasticsearch` values section.

#### Basic Elasticsearch Setup

```yaml
# In your helmrelease.yaml values section
elasticsearch:
  enabled: true
  # Option 1: Use Kubernetes Secret for connection details (Recommended)
  secretName: "airflow-elasticsearch-secret"

  # Option 2: Direct connection configuration
  connection:
    scheme: http # or https for TLS
    host: "elasticsearch-master.elastic-system.svc.cluster.local"
    port: 9200
    # user: "elastic"  # if authentication is enabled
    # pass: "your-password"  # if authentication is enabled
```

#### Airflow Configuration Override

```yaml
config:
  logging:
    remote_logging: "True" # Enable remote logging
  # delete_local_logs: "True"  # Optional: delete local logs after ES write

  elasticsearch:
    host: "elasticsearch-master.elastic-system.svc.cluster.local:9200"
    write_stdout: "False" # Set to True for log shipping approach
    json_format: "True" # Enable structured JSON logging
    write_to_es: "True" # Enable direct write to Elasticsearch
    target_index: "airflow-task-logs" # Elasticsearch index name
    log_id_template: "{dag_id}-{task_id}-{execution_date}-{try_number}"

  # Optional: Elasticsearch client configuration
  elasticsearch_configs:
    max_retries: 3
    timeout: 30
    retry_timeout: "True"
```

#### TLS/SSL Configuration

For secure Elasticsearch connections:

```yaml
config:
  elasticsearch:
    host: "https://elasticsearch-master.elastic-system.svc.cluster.local:9200"
    # ... other settings ...

  elasticsearch_configs:
    use_ssl: "True"
    verify_certs: "True"
    ca_certs: "/opt/airflow/certs/elasticsearch-ca.pem"
    # client_cert: "/opt/airflow/certs/client.pem"
    # client_key: "/opt/airflow/certs/client-key.pem"
```

### Kibana Integration

To enable direct links from Airflow UI to Kibana:

```yaml
config:
  elasticsearch:
    # ... other settings ...
    frontend: "http://kibana.elastic-system.svc.cluster.local:5601/app/discover#/?_g=(time:(from:now-2d,to:now))&_a=(query:(language:kuery,query:'log_id:%22{log_id}%22'))"
```

## Complete Example Configuration

Here's a complete example for your `helmrelease.yaml`:

```yaml
# kubernetes/apps/airflow/airflow/app/helmrelease.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: airflow
spec:
  # ... existing spec ...
  values:
    # ... existing values ...

    # Elasticsearch Configuration
    elasticsearch:
      enabled: true
      secretName: "airflow-elasticsearch-secret" # Create this secret separately

    # Airflow Configuration Overrides
    config:
      logging:
        remote_logging: "True"
        logging_level: "INFO"
        fab_logging_level: "WARN"
        # delete_local_logs: "False"  # Set to True if you want to delete local logs

      elasticsearch:
        write_stdout: "False"
        json_format: "True"
        write_to_es: "True"
        target_index: "airflow-task-logs"
        log_id_template: "{dag_id}-{task_id}-{execution_date}-{try_number}"
        frontend: "http://kibana.elastic-system.svc.cluster.local:5601/app/discover#/?_g=(time:(from:now-2d,to:now))&_a=(query:(language:kuery,query:'log_id:%22{log_id}%22'))"

      elasticsearch_configs:
        max_retries: 3
        timeout: 30
        retry_timeout: "True"

    # Keep persistent volumes as fallback (optional)
    logs:
      persistence:
        enabled: true
        size: 5Gi # Reduced size since ES is primary
        storageClassName: local-path
        accessMode: ReadWriteOnce
```

## Elasticsearch Secret Creation

Create a Kubernetes secret for Elasticsearch connection details:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: airflow-elasticsearch-secret
  namespace: airflow
type: Opaque
stringData:
  connection: |
    {
      "scheme": "http",
      "host": "elasticsearch-master.elastic-system.svc.cluster.local",
      "port": 9200,
      "user": "elastic",
      "pass": "your-elasticsearch-password"
    }
```

## Log Shipping Alternative

If you prefer the log shipping approach, configure Airflow to output structured
logs to stdout:

```yaml
config:
  logging:
    remote_logging: "True"

  elasticsearch:
    host: "elasticsearch-master.elastic-system.svc.cluster.local:9200"
    write_stdout: "True" # Output to stdout for log shippers
    json_format: "True" # Structured JSON for easier parsing
    write_to_es: "False" # Disable direct write
    json_fields: "asctime,filename,lineno,levelname,message"
```

Then deploy a log shipper like Filebeat or Fluentd to forward container logs to
Elasticsearch.

## Index Lifecycle Management

Configure Elasticsearch ILM policies for log retention:

```json
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "10GB",
            "max_age": "7d"
          }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "allocate": {
            "number_of_replicas": 0
          }
        }
      },
      "delete": {
        "min_age": "30d"
      }
    }
  }
}
```

## Monitoring and Troubleshooting

### Common Issues

1. **Connection Failures**
   - Verify Elasticsearch service is reachable
   - Check network policies and firewall rules
   - Validate authentication credentials

2. **Performance Impact**
   - Monitor task execution times
   - Consider using log shipping instead of direct write
   - Optimize Elasticsearch cluster resources

3. **Log Missing**
   - Check Airflow configuration for `remote_logging = True`
   - Verify Elasticsearch index exists and is writable
   - Review Airflow logs for error messages

### Verification Commands

```bash
# Check Airflow configuration
kubectl exec -n airflow deployment/airflow-webserver -- airflow config get-value logging remote_logging

# Check Elasticsearch connectivity
kubectl exec -n airflow deployment/airflow-webserver -- curl -X GET "elasticsearch-master.elastic-system.svc.cluster.local:9200/_cluster/health"

# Check if logs are being indexed
kubectl exec -n airflow deployment/airflow-webserver -- curl -X GET "elasticsearch-master.elastic-system.svc.cluster.local:9200/airflow-task-logs/_search?size=5"
```

### Test Script Integration

Update your existing test script to include Elasticsearch verification:

```typescript
// In scripts/test-airflow-logging.ts
async function checkElasticsearchLogs() {
  console.log("🔍 Checking Elasticsearch integration...");

  try {
    const webserverPod =
      await $`kubectl get pods -n airflow -l component=webserver -o jsonpath='{.items[0].metadata.name}'`
        .text();

    if (webserverPod) {
      // Check ES connectivity
      await $`kubectl exec -n airflow ${webserverPod} -- curl -f -X GET "elasticsearch-master.elastic-system.svc.cluster.local:9200/_cluster/health"`;

      // Check for recent log entries
      await $`kubectl exec -n airflow ${webserverPod} -- curl -X GET "elasticsearch-master.elastic-system.svc.cluster.local:9200/airflow-task-logs/_search?size=5&sort=@timestamp:desc"`;
    }
  } catch (error) {
    console.error(
      "❌ Elasticsearch check failed:",
      error instanceof Error ? error.message : String(error),
    );
    throw error;
  }
}
```

## Best Practices

1. **Security**
   - Use Kubernetes secrets for credentials
   - Enable TLS encryption for production
   - Implement proper RBAC for Elasticsearch access

2. **Performance**
   - Monitor Elasticsearch cluster performance
   - Use appropriate index sharding and replication
   - Consider log sampling for high-volume environments

3. **Reliability**
   - Implement proper error handling and retries
   - Use log shipping for better fault tolerance
   - Keep persistent volumes as fallback option

4. **Maintenance**
   - Set up proper index lifecycle management
   - Monitor disk usage and performance
   - Regular backup of important log data

## Migration from Persistent Volume Logging

If migrating from the existing persistent volume logging:

1. **Phase 1**: Enable Elasticsearch with `delete_local_logs: False`
2. **Phase 2**: Verify Elasticsearch logging works correctly
3. **Phase 3**: Set `delete_local_logs: True` or disable PVC persistence
4. **Phase 4**: Optimize Elasticsearch cluster and index settings

This approach ensures a smooth transition with fallback capabilities during the
migration period.

## References

- [Airflow Elasticsearch Provider Documentation](https://airflow.apache.org/docs/apache-airflow-providers-elasticsearch/stable/logging/index.html)
- [Airflow Helm Chart Logging Management](https://airflow.apache.org/docs/helm-chart/stable/manage-logs.html)
- [Elasticsearch Index Lifecycle Management](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
- [Elastic Integration Examples](https://www.elastic.co/search-labs/blog/apache-airflow-elasticsearch-ingest-data)
