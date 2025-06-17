# Spark Iceberg Client

This directory contains the Spark client configuration for interacting with Iceberg tables via the Nessie catalog.

## Current Implementation

The current implementation uses runtime JAR downloads via an `initContainer`. This is an interim solution that works but is not optimal for production use.

## Recommended Improvement: Pre-built Image

For better GitOps compliance and faster startup times, build a custom image with all dependencies pre-installed:

### Building the Custom Image

```bash
# Build the image with all Iceberg dependencies
docker build -t homelab/spark-iceberg:3.5.5 .

# Tag for your registry
docker tag homelab/spark-iceberg:3.5.5 your-registry.com/homelab/spark-iceberg:3.5.5

# Push to registry
docker push your-registry.com/homelab/spark-iceberg:3.5.5
```

### Using the Custom Image

After building and pushing the image, update the Pod specification:

```yaml
spec:
  containers:
  - name: spark
    image: your-registry.com/homelab/spark-iceberg:3.5.5  # Use custom image
    # Remove initContainers section
    # Remove iceberg-jars volume and mount
```

### Benefits of Pre-built Image

1. **Faster startup**: No runtime downloads required
2. **GitOps compliance**: All dependencies declared in code
3. **Reproducible builds**: Same image across environments
4. **Security**: No external network dependencies at runtime
5. **Reliability**: Eliminates potential network failures during JAR downloads

## Dependencies Included

The custom image includes:

- **Iceberg Spark Runtime**: `iceberg-spark-runtime-3.5_2.12-1.5.2.jar`
- **Nessie Spark Extensions**: `nessie-spark-extensions-3.5_2.12-0.77.1.jar`
- **Hadoop AWS**: `hadoop-aws-3.3.4.jar`
- **AWS Java SDK**: `aws-java-sdk-bundle-1.12.367.jar`

## Configuration

The Spark configuration is provided via ConfigMap and includes:

- Iceberg and Nessie catalog configuration
- S3 connectivity to Ceph storage
- Performance optimizations
- Security settings

## Usage

```bash
# Deploy the client
kubectl apply -k .

# Connect to the Spark shell
kubectl exec -it spark-iceberg-client -n data-platform -- /opt/spark/bin/spark-shell

# Example Iceberg operations
spark-sql> USE nessie;
spark-sql> CREATE NAMESPACE IF NOT EXISTS lakehouse;
spark-sql> CREATE TABLE nessie.lakehouse.events (
         >   id BIGINT,
         >   event_time TIMESTAMP,
         >   event_type STRING,
         >   payload STRING
         > ) USING iceberg
         > LOCATION 's3a://iceberg-test/lakehouse/events'
         > PARTITIONED BY (days(event_time));
```

## Security

The client Pod includes:

- Non-root security context
- Read-only root filesystem where possible
- Minimal capabilities
- Resource limits
- Network policies (when enabled)

## Troubleshooting

### Common Issues

1. **S3 Connection Failed**: Check credentials and endpoint configuration
2. **Nessie Unavailable**: Verify Nessie service is running
3. **JAR Download Failures**: Network issues or repository unavailable (resolved with pre-built image)

### Debug Commands

```bash
# Check Pod status
kubectl get pod spark-iceberg-client -n data-platform

# View logs
kubectl logs spark-iceberg-client -n data-platform

# Check Spark configuration
kubectl exec spark-iceberg-client -n data-platform -- cat /opt/spark/conf/spark-defaults.conf

# Test S3 connectivity
kubectl exec spark-iceberg-client -n data-platform -- env | grep AWS
```