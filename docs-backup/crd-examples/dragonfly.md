# Dragonfly CRD Examples and Common Pitfalls

## Valid Dragonfly Configuration

Based on the
[official Dragonfly documentation](https://www.dragonflydb.io/docs/managing-dragonfly/operator/dragonfly-configuration),
here are valid configuration examples:

### Basic Configuration

```yaml
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: example-cache
  namespace: database
spec:
  replicas: 1
  resources:
    requests:
      cpu: "100m"
      memory: "256Mi"
    limits:
      cpu: "500m"
      memory: "512Mi"
```

### With Persistent Storage

```yaml
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: cache-with-storage
  namespace: database
spec:
  replicas: 2
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "1"
      memory: "2Gi"
  snapshot:
    cron: "0 */6 * * *" # Every 6 hours
    persistentVolumeClaimSpec:
      accessModes:
        - ReadWriteOnce
      resources:
        requests:
          storage: "10Gi"
      storageClassName: "local-path"
```

### With Authentication

```yaml
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: secure-cache
  namespace: database
spec:
  replicas: 1
  authentication:
    passwordFromSecret:
      name: dragonfly-auth-secret
      key: password
  resources:
    requests:
      cpu: "200m"
      memory: "512Mi"
```

### With Custom Args

```yaml
apiVersion: dragonflydb.io/v1alpha1
kind: Dragonfly
metadata:
  name: custom-cache
  namespace: database
spec:
  replicas: 1
  args:
    - "--cluster_mode=emulated"
    - "--cache_mode=true"
  env:
    - name: DRAGONFLY_MEMORY_STATS
      value: "true"
  resources:
    requests:
      cpu: "100m"
      memory: "256Mi"
```

## Common Pitfalls to Avoid

### ❌ Invalid Fields

These fields are **NOT** valid in the Dragonfly CRD:

```yaml
spec:
  # These will cause validation errors:
  redis: # Not a valid field
    port: 6379

  storage: # Not a valid field - use snapshot.persistentVolumeClaimSpec
    size: "10Gi"

  port: 6379 # Not a valid field - port is always 6379

  memcached: # Use memcachedPort instead
    port: 11211
```

### ✅ Correct Alternatives

```yaml
spec:
  # For memcached protocol support:
  memcachedPort: 11211 # Valid field (since v1.1.2)

  # For storage:
  snapshot:
    persistentVolumeClaimSpec:
      resources:
        requests:
          storage: "10Gi"

  # Port 6379 is always used for Redis protocol (not configurable)
```

## How to Check Valid Fields

1. **Use kubectl explain:**
   ```bash
   kubectl explain dragonfly.spec
   kubectl explain dragonfly.spec --recursive | less
   ```

2. **Check the operator version:**
   ```bash
   kubectl get deployment dragonfly-operator -n database -o jsonpath='{.spec.template.spec.containers[0].image}'
   ```

3. **Refer to the official documentation:**
   - [Dragonfly Configuration](https://www.dragonflydb.io/docs/managing-dragonfly/operator/dragonfly-configuration)
   - [Latest Release Notes](https://github.com/dragonflydb/dragonfly-operator/releases)

## Field Availability by Version

Some fields are only available in newer versions:

- `aclFromSecret` - Since v1.1.1
- `nodeSelector` - Since v1.1.1
- `topologySpreadConstraints` - Since v1.1.1
- `priorityClassName` - Since v1.1.1
- `skipFSGroup` - Since v1.1.2
- `memcachedPort` - Since v1.1.2
- `serviceSpec.name` - Since v1.1.3

Always check your operator version before using these fields.
