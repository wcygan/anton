---
description: Safely remove an application from the cluster following GitOps patterns
---

Help the user safely remove an application from the Kubernetes cluster. This is the reverse of the 3-file pattern used to deploy apps.

**Pre-removal checklist:**

1. **Identify the app location:**
   ```
   kubernetes/apps/{namespace}/{app-name}/
   ├── ks.yaml
   └── app/
       ├── kustomization.yaml
       ├── helmrelease.yaml
       ├── ocirepository.yaml
       └── (other resources)
   ```

2. **Check for dependencies:**
   - Is anything else using this app's services?
   - Are there PVCs with important data?
   - Are there secrets that other apps reference?

   ```bash
   kubectl get svc -n {namespace} {app} -o yaml
   kubectl get pvc -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get secrets -n {namespace} -l app.kubernetes.io/name={app}
   ```

3. **Check for ingress/routes:**
   ```bash
   kubectl get httproute -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get certificate -n {namespace} | grep {app}
   ```

**Data preservation decision:**

Ask the user:
- **Keep PVCs?** Data will persist even after app removal
- **Delete PVCs?** Data will be permanently lost
- **Backup first?** Create snapshot before deletion

**Removal steps:**

1. **Remove from namespace kustomization:**
   Edit `kubernetes/apps/{namespace}/kustomization.yaml`:
   ```yaml
   resources:
     - ./namespace.yaml
     # - ./{app-name}/ks.yaml  # Remove or comment this line
   ```

2. **Delete the app directory:**
   ```bash
   rm -rf kubernetes/apps/{namespace}/{app-name}/
   ```

3. **Handle PVCs (if deleting data):**
   - Flux won't delete PVCs by default (data protection)
   - Manual deletion required:
   ```bash
   kubectl delete pvc -n {namespace} -l app.kubernetes.io/name={app}
   ```

4. **Clean up related resources:**
   - Certificates (if app-specific)
   - DNSEndpoints (for secondary domains)
   - NetworkPolicies (if app-specific)

5. **Commit and push:**
   ```bash
   git add -A
   git commit -m "feat({namespace}): remove {app-name}"
   git push
   ```

6. **Verify removal:**
   ```bash
   kubectl get all -n {namespace} -l app.kubernetes.io/name={app}
   kubectl get hr -n {namespace} {app}  # Should be gone
   kubectl get ks -n {namespace} {app}  # Should be gone
   ```

**Special cases:**

- **Namespace-only app:** If this was the only app in namespace, consider removing the namespace too
- **Shared secrets:** Don't delete secrets used by other apps
- **CRDs:** Some apps install CRDs - check if other apps need them
- **Finalizers stuck:** If resources won't delete, check for stuck finalizers

**Output format:**

1. **Confirm app location** and files to remove
2. **List dependencies** found (if any)
3. **Show removal commands** in order
4. **Highlight data implications** (PVCs, secrets)
5. **Provide commit message** following semantic format

**Safety reminder:**
- This is a destructive operation
- Verify you're removing the correct app
- Consider backing up PVC data first
- Flux will reconcile and remove resources from cluster
