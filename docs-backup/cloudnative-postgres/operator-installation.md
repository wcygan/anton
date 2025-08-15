# CloudNativePG Operator Installation and Usage

This document outlines the process for installing the CloudNativePG operator in
the cluster using Flux, and how to provision a new PostgreSQL database instance.

## Key Insights from Installation

1. **Namespace Strategy**:
   - The CloudNativePG operator is installed in its own dedicated namespace:
     `cnpg-system`.
   - Database instances (clusters) are provisioned in separate,
     application-specific namespaces (e.g., `database` for the initial test
     instance).

2. **Flux Configuration**:
   - **HelmRepository**: A `HelmRepository` resource (`cloudnative-pg`) is added
     to `kubernetes/flux/meta/repos/` and included in the corresponding
     `kustomization.yaml`. This allows Flux to fetch the CloudNativePG Helm
     chart.
   - **Operator Kustomization**:
     - A Flux `Kustomization` is created for the `cnpg-system` namespace
       (`kubernetes/apps/cnpg-system/kustomization.yaml`).
     - This namespace Kustomization references another Flux `Kustomization` for
       the operator itself
       (`kubernetes/apps/cnpg-system/cnpg-operator/ks.yaml`).
     - The operator's `ks.yaml` points to its application manifests
       (`kubernetes/apps/cnpg-system/cnpg-operator/app/`), which include the
       `HelmRelease`.
   - **HelmRelease for Operator**: The `HelmRelease`
     (`kubernetes/apps/cnpg-system/cnpg-operator/app/helmrelease.yaml`) installs
     the `cloudnative-pg` chart into the `cnpg-system` namespace.
     - CRD management (`crds: CreateReplace`) is enabled in the HelmRelease.
     - The `fullnameOverride` is set to `cnpg-controller-manager` to match the
       deployment name typically used in manifest-based installs and expected by
       health checks.

3. **Secret Management (Test Database Example)**:
   - For the provided test database example (`test-postgres-cluster`),
     application user credentials are managed via a **plain Kubernetes Secret**
     committed directly to Git
     (`kubernetes/apps/database/test-db/app/secret.yaml`).
   - CloudNativePG follows a convention: for a cluster named `my-db-cluster`
     that bootstraps an application user (e.g., `appuser`), it will look for a
     Secret named `my-db-cluster-app` containing `username` and `password` keys.
   - **Important Note for Production**: Storing plain secrets in Git is
     generally discouraged for production environments. Prefer using a secrets
     management solution like 1Password integrated with the 1Password Operator,
     or at least SOPS encryption for secrets stored in Git.

## Adding a New Database Instance

To add a new PostgreSQL database instance using CloudNativePG:

1. **Choose/Create a Namespace**:
   - Decide which namespace the new database will reside in. For example, if
     it's for a specific application `my-app`, you might use the `my-app`
     namespace.
   - If the namespace doesn't exist, create its Kustomization structure under
     `kubernetes/apps/` similar to
     `kubernetes/apps/database/kustomization.yaml`, ensuring it includes the
     `components/common` for namespace creation.

2. **Create Database Kustomization Files**:
   - In the chosen namespace directory (e.g., `kubernetes/apps/my-app/`), create
     a new subdirectory for your database instance, for example, `my-app-db`.
   - **Flux Kustomization (`ks.yaml`)**:
     - Create `kubernetes/apps/my-app/my-app-db/ks.yaml`.
     - This file tells Flux where to find the database manifests and how to
       deploy them.
     - It must `dependOn` the `cnpg-operator` Kustomization to ensure the
       operator is ready before attempting to create a database.
     - Set the `targetNamespace` to where the database should be deployed (e.g.,
       `my-app`).
     - Include a `healthCheck` for the `Cluster` resource.
     - Example (`kubernetes/apps/database/test-db/ks.yaml` can be used as a
       template):
       ```yaml
       # kubernetes/apps/my-app/my-app-db/ks.yaml
       ---
       apiVersion: kustomize.toolkit.fluxcd.io/v1
       kind: Kustomization
       metadata:
         name: &app my-app-db
         namespace: flux-system
       spec:
         commonMetadata:
           labels:
             app.kubernetes.io/name: *app
         dependsOn:
           - name: cnpg-operator
             namespace: flux-system
         interval: 30m
         path: ./kubernetes/apps/my-app/my-app-db/app # Path to app manifests
         prune: true
         sourceRef:
           kind: GitRepository
           name: flux-system
           namespace: flux-system
         targetNamespace: my-app # Target namespace for the database
         timeout: 10m
         wait: true
         healthChecks:
           - apiVersion: postgresql.cnpg.io/v1
             kind: Cluster
             name: my-app-pg-cluster # Name of your Cluster CR
             namespace: my-app # Namespace of your Cluster CR
       ```

   - **Application Kustomization (`app/kustomization.yaml`)**:
     - Create `kubernetes/apps/my-app/my-app-db/app/kustomization.yaml`.
     - This Kustomization lists the actual database manifest files (Cluster CR,
       Secret).
     - Example:
       ```yaml
       # kubernetes/apps/my-app/my-app-db/app/kustomization.yaml
       ---
       apiVersion: kustomize.config.k8s.io/v1beta1
       kind: Kustomization
       resources:
         - ./cluster.yaml
         - ./secret.yaml # Or secret.sops.yaml if using SOPS
       ```

3. **Define the Cluster Resource (`app/cluster.yaml`)**:
   - Create `kubernetes/apps/my-app/my-app-db/app/cluster.yaml`.
   - This is the CloudNativePG Custom Resource that defines your PostgreSQL
     cluster.
   - Specify `instances`, `imageName`, `resources`, `storage`, and `bootstrap`
     configuration.
   - `metadata.name` should match the `healthChecks.name` in `ks.yaml`.
   - `metadata.namespace` should match `targetNamespace` in `ks.yaml`.
   - Example (`kubernetes/apps/database/test-db/app/cluster.yaml` can be
     adapted):
     ```yaml
     # kubernetes/apps/my-app/my-app-db/app/cluster.yaml
     ---
     apiVersion: postgresql.cnpg.io/v1
     kind: Cluster
     metadata:
       name: my-app-pg-cluster
       namespace: my-app
     spec:
       instances: 1
       imageName: ghcr.io/cloudnative-pg/postgresql:16.3 # Or desired version

       resources: # Adjust as needed
         requests:
           cpu: "100m"
           memory: "256Mi"
         limits:
           cpu: "500m"
           memory: "512Mi"

       storage: # Uses default StorageClass (local-path)
         size: "5Gi" # Adjust as needed

       bootstrap:
         initdb:
           database: myapp_db_name # Name of the database to create
           owner: myapp_user # Application user that will own the database
           # CNPG will look for a Secret named 'my-app-pg-cluster-app' for this user's credentials.
     ```

4. **Create User Secret (`app/secret.yaml` or `app/secret.sops.yaml`)**:
   - Create `kubernetes/apps/my-app/my-app-db/app/secret.yaml` (for plain
     secret) or `secret.sops.yaml` (for SOPS-encrypted).
   - This secret will store the credentials for the application user
     (`myapp_user` in the example above).
   - The secret must be named `<clusterName>-app` (e.g.,
     `my-app-pg-cluster-app`) and contain `username` and `password` keys.
   - **Plain Secret Example**:
     ```yaml
     # kubernetes/apps/my-app/my-app-db/app/secret.yaml
     ---
     apiVersion: v1
     kind: Secret
     metadata:
       name: my-app-pg-cluster-app # <clusterName>-app convention
       namespace: my-app
     stringData:
       username: "myapp_user"
       password: "YourPlainPasswordHere!"
     ```
   - **SOPS Encrypted Secret Example** (Recommended for Git):
     ```yaml
     # kubernetes/apps/my-app/my-app-db/app/secret.sops.yaml
     ---
     apiVersion: v1
     kind: Secret
     metadata:
       name: my-app-pg-cluster-app # <clusterName>-app convention
       namespace: my-app
     stringData:
       username: ENC[AES256_GCM,...] # Encrypted username (e.g., "myapp_user")
       password: ENC[AES256_GCM,...] # Encrypted password
     sops:
     # ... SOPS encryption details ...
     ```
     Remember to encrypt the file using `sops --encrypt --in-place <filename>`
     if using SOPS.

5. **Update Namespace Kustomization**:
   - Add a reference to the new database's Flux Kustomization (`ks.yaml`) in the
     parent namespace's `kustomization.yaml`.
   - Example: If your database is in `kubernetes/apps/my-app/my-app-db/ks.yaml`,
     update `kubernetes/apps/my-app/kustomization.yaml`:
     ```yaml
     # kubernetes/apps/my-app/kustomization.yaml
     resources:
       # ... other resources for my-app ...
       - ./my-app-db/ks.yaml # Add this line
     ```

6. **Commit and Push**:
   - Add all new files to Git, commit, and push the changes.
   - Flux will pick up the changes and start provisioning the CloudNativePG
     operator (if not already present) and then the new database instance.

7. **Monitor**:
   - Use `flux get kustomizations -A` and `kubectl get clusters -A` to monitor
     the progress.
   - Check logs of the `cnpg-controller-manager` in the `cnpg-system` namespace
     if issues arise.
   - Once the cluster is ready, you can find connection details (service name,
     port) by describing the `Cluster` CR or checking for created `Service`
     resources in the database's namespace.

This provides a template for deploying CloudNativePG and managing PostgreSQL
instances declaratively with Flux.
