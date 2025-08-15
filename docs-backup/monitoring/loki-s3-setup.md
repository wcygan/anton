# Loki S3 Storage Setup

This guide documents the setup of S3 storage for Loki using Rook-Ceph.

## Prerequisites

- Rook-Ceph cluster deployed and healthy
- 1Password Connect configured
- External Secrets Operator installed

## S3 Credentials

Rook-Ceph has automatically created S3 credentials for Loki. The credentials are stored in the `rook-ceph-object-user-storage-loki` secret in the `storage` namespace.

### Retrieving the Credentials

```bash
# Get the access key
kubectl get secret -n storage rook-ceph-object-user-storage-loki \
  -o jsonpath='{.data.AccessKey}' | base64 -d

# Get the secret key
kubectl get secret -n storage rook-ceph-object-user-storage-loki \
  -o jsonpath='{.data.SecretKey}' | base64 -d
```

### Adding to 1Password

1. Log into 1Password
2. Navigate to the Homelab vault
3. Create a new item named `loki-s3-config`
4. Add the following fields:
   - `access_key`: (value from above)
   - `secret_key`: (value from above)

## S3 Bucket Creation

The Loki S3 bucket needs to be created manually. Use the following command:

```bash
# Create a temporary pod with AWS CLI
kubectl run -n storage aws-cli --rm -i --restart=Never \
  --image=amazon/aws-cli:latest \
  --env="AWS_ACCESS_KEY_ID=$(kubectl get secret -n storage rook-ceph-object-user-storage-loki -o jsonpath='{.data.AccessKey}' | base64 -d)" \
  --env="AWS_SECRET_ACCESS_KEY=$(kubectl get secret -n storage rook-ceph-object-user-storage-loki -o jsonpath='{.data.SecretKey}' | base64 -d)" \
  -- s3 mb s3://loki --endpoint-url http://rook-ceph-rgw-storage.storage.svc.cluster.local:80 --region us-east-1
```

## Configuration

The Loki HelmRelease is configured to use:
- Endpoint: `http://rook-ceph-rgw-storage.storage.svc.cluster.local`
- Bucket: `loki`
- Region: `us-east-1` (dummy region, required by S3 protocol)

## Verification

After applying the configuration:

```bash
# Check if ExternalSecret is synced
kubectl get externalsecret loki-s3-credentials -n monitoring

# Check if secret is created
kubectl get secret loki-s3-credentials -n monitoring

# Check Loki pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki

# Check Loki logs
kubectl logs -n monitoring -l app.kubernetes.io/name=loki
```

## Troubleshooting

### Bucket Not Found
If Loki reports "bucket not found", create it manually using the command above.

### Authentication Errors
Verify the credentials in 1Password match those in the Rook-generated secret.

### Connection Timeout
Check that the RGW service is running:
```bash
kubectl get pods -n storage -l app=rook-ceph-rgw
```