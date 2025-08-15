# Secret Management Golden Rules

## Rule #1: Never Commit Unencrypted Secrets

**A single unencrypted secret in Git history is compromised forever.**

### NEVER Do This:
```bash
# CATASTROPHIC - Secret exposed in Git history forever
echo "password123" > secret.yaml
git add secret.yaml
git commit -m "add secret"
# Even if you delete it later, it's in history!
```

### Always Do This:
```bash
# Option 1: Use SOPS
sops -e secret.yaml > secret.sops.yaml
git add secret.sops.yaml

# Option 2: Use External Secrets
cat > external-secret.yaml <<EOF
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: app-secret
spec:
  secretStoreRef:
    name: onepassword-connect
EOF
git add external-secret.yaml
```

## Rule #2: Protect the SOPS Age Key

**The age.key is the master key to all secrets.**

### Security Measures:
```bash
# 1. Never commit age.key
echo "age.key" >> .gitignore

# 2. Secure permissions
chmod 600 age.key

# 3. Backup securely (encrypted)
age -r age1... -o age.key.backup age.key

# 4. Store in password manager
# Add to 1Password/Bitwarden with 2FA
```

### If Age Key is Compromised:
```bash
# 1. Generate new key immediately
age-keygen -o age.key.new

# 2. Re-encrypt all secrets
for file in $(find . -name "*.sops.yaml"); do
  sops -d $file | sops -e --age $(cat age.key.new | grep "public key" | cut -d: -f2) /dev/stdin > $file.new
  mv $file.new $file
done

# 3. Update cluster secret
kubectl delete secret sops-age -n flux-system
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.key=age.key.new
```

## Rule #3: Use Separate Secrets for Each App

**Don't create "mega secrets" with all credentials.**

### Wrong Way:
```yaml
# DON'T - Single secret with everything
apiVersion: v1
kind: Secret
metadata:
  name: all-passwords
data:
  postgres-password: ...
  redis-password: ...
  api-key: ...
  jwt-secret: ...
```

### Right Way:
```yaml
# DO - Separate secrets per app/purpose
---
apiVersion: v1
kind: Secret
metadata:
  name: postgres-credentials
  namespace: database
data:
  password: ...
---
apiVersion: v1
kind: Secret
metadata:
  name: redis-credentials
  namespace: cache
data:
  password: ...
```

## Rule #4: Rotate Secrets Regularly

**Static secrets are time bombs.**

### Rotation Process:
```bash
# 1. Generate new secret
openssl rand -base64 32 > new-password.txt

# 2. Update in 1Password/secret store
# Use 1Password CLI or web interface

# 3. Update ExternalSecret to sync
kubectl annotate externalsecret my-secret \
  force-sync=$(date +%s) --overwrite

# 4. Restart pods to pick up new secret
kubectl rollout restart deployment my-app
```

## Rule #5: Never Log Secrets

**Secrets in logs are secrets exposed.**

### Application Code:
```go
// WRONG
log.Printf("Connecting with password: %s", password)

// RIGHT
log.Printf("Connecting to database...")
```

### Kubernetes Manifests:
```yaml
# WRONG - Secret visible in describe/events
env:
  - name: PASSWORD
    value: "supersecret123"

# RIGHT - Reference secret
env:
  - name: PASSWORD
    valueFrom:
      secretKeyRef:
        name: app-secrets
        key: password
```

## Rule #6: Limit Secret Access

**Use RBAC to restrict secret access.**

### Implement Least Privilege:
```yaml
# ServiceAccount for app
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app
  namespace: my-namespace
---
# Role with minimal permissions
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-app-secrets
  namespace: my-namespace
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["my-app-secret"]  # Only specific secret
    verbs: ["get"]
```

## Rule #7: Monitor Secret Usage

**Track who accesses secrets and when.**

### Enable Audit Logging:
```yaml
# Audit policy for secrets
- level: RequestResponse
  omitStages:
    - RequestReceived
  resources:
    - group: ""
      resources: ["secrets"]
  namespaces: ["default", "production"]
```

### Check Secret Access:
```bash
# Recent secret access events
kubectl get events --all-namespaces \
  --field-selector reason=SecretAccessed \
  --sort-by='.lastTimestamp'
```

## Rule #8: Handle 1Password/External Secrets Carefully

**External secret operators need special attention.**

### 1Password Integration:
```bash
# 1. Never expose Connect server publicly
# 2. Use separate credentials per cluster
# 3. Rotate Connect tokens regularly

# Check 1Password Connect health
kubectl logs -n external-secrets deployment/onepassword-connect

# Verify secret sync
kubectl get externalsecrets -A
kubectl describe externalsecret <name>
```

### Common Issues:
```yaml
# Issue: ClusterSecretStore not ready
# Fix: Check Connect token
kubectl get secret onepassword-connect-token -n external-secrets -o yaml

# Issue: Secret not syncing
# Fix: Check 1Password item exists and permissions
kubectl logs -n external-secrets deployment/external-secrets
```

## Rule #9: Backup Secrets Appropriately

**Secrets need special backup procedures.**

### Backup Strategy:
```bash
# 1. Export to encrypted file
kubectl get secrets -A -o yaml | \
  sops -e --age $(cat age.key.pub) /dev/stdin > secrets-backup.sops.yaml

# 2. Store in separate location from code
# - Different Git repo
# - Encrypted cloud storage
# - Physical secure storage

# 3. Test restore process
sops -d secrets-backup.sops.yaml | kubectl apply -f -
```

## Rule #10: Clean Up Unused Secrets

**Old secrets are security debt.**

### Regular Cleanup:
```bash
# Find unused secrets
for secret in $(kubectl get secrets -A -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)"'); do
  namespace=$(echo $secret | cut -d/ -f1)
  name=$(echo $secret | cut -d/ -f2)
  
  # Check if referenced in pods
  kubectl get pods -n $namespace -o json | grep -q $name || echo "Potentially unused: $secret"
done

# Delete after verification
kubectl delete secret unused-secret
```

## Emergency Procedures

### Secret Leak Response:
```bash
# 1. Immediate rotation
# Generate new credentials for affected service

# 2. Update secret in cluster
kubectl create secret generic temp-secret \
  --from-literal=password=$(openssl rand -base64 32) \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Force pod restart
kubectl rollout restart deployment affected-app

# 4. Audit logs for unauthorized access
kubectl logs -n external-secrets deployment/external-secrets | grep -i error

# 5. Update all dependent services
```

### SOPS Decryption Failures:
```bash
# 1. Verify age key is present
kubectl get secret sops-age -n flux-system

# 2. Check key format
kubectl get secret sops-age -n flux-system -o jsonpath='{.data.age\.key}' | base64 -d

# 3. Test decryption locally
export SOPS_AGE_KEY_FILE=./age.key
sops -d test.sops.yaml

# 4. Re-create secret if needed
kubectl delete secret sops-age -n flux-system
kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.key
```

## Remember

> **Secrets are like passwords - assume they're compromised the moment they're exposed. Rotation is not optional, it's mandatory.**