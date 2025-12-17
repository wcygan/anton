---
description: Plan and design a new application deployment for the Kubernetes cluster
---

Help the user plan and bootstrap a new application for deployment to their Talos Kubernetes cluster with GitOps via Flux.

**Discovery phase - Ask these questions:**

1. **What application do you want to host?**
   - Existing Helm chart (e.g., from Bitnami, official charts)
   - Custom container image
   - Something you need to research first

2. **How should it be exposed?**
   - **Public (internet-facing)**: Via Cloudflare tunnel → `envoy-external` gateway
   - **Internal only**: Via `envoy-internal` gateway (accessible within network/Tailscale)
   - **Not exposed**: Cluster-internal service only

3. **What domain/subdomain?**
   - Primary domain: `${SECRET_DOMAIN}` (wcygan.net)
   - Secondary domain: `${SECRET_DOMAIN_TWO}` (kneadybynaturebakery.com)
   - Suggest appropriate subdomain based on app name

4. **Does it need persistent storage?**
   - If yes, recommend Ceph block storage (`ceph-block` StorageClass)
   - Estimate storage size based on app requirements

5. **Does it need secrets?**
   - API keys, passwords, tokens
   - Will use SOPS encryption

**Research phase (if needed):**

If the user wants to host an app but isn't sure how:
- Use WebSearch to find the official Helm chart or recommended deployment method
- Check if there's an OCI registry for the chart (preferred for Flux)
- Identify required configuration values
- Note any dependencies (databases, caches, etc.)

**Design output - Provide:**

1. **Architecture summary:**
   ```
   [App] → [Service] → [HTTPRoute] → [Gateway] → [Cloudflare/Internal]
                ↓
           [PVC if needed]
   ```

2. **Required files (3-file pattern):**
   ```
   kubernetes/apps/{namespace}/{app-name}/
   ├── ks.yaml                 # Flux Kustomization
   └── app/
       ├── kustomization.yaml  # Resource list
       ├── helmrelease.yaml    # Helm deployment
       ├── ocirepository.yaml  # Chart source
       ├── httproute.yaml      # (if exposed)
       └── secret.sops.yaml    # (if secrets needed)
   ```

3. **Key configuration decisions:**
   - Namespace (new or existing)
   - Resource limits (based on app requirements)
   - Replica count and HA considerations
   - Health check endpoints

4. **Checklist before implementation:**
   - [ ] Helm chart exists and version identified
   - [ ] OCI registry URL confirmed
   - [ ] Domain/subdomain decided
   - [ ] Storage requirements known
   - [ ] Secrets identified and ready
   - [ ] Dependencies available (databases, etc.)

**Implementation approach:**

Once design is approved, offer to:
1. Create the directory structure
2. Generate all required YAML files following project patterns
3. Reference existing apps as templates (e.g., `echo`, `grafana`)
4. Run `task configure` to validate
5. Commit with semantic message: `feat({namespace}): add {app-name} deployment`

**Reference patterns from:**
- `kubernetes/apps/default/echo/` - Simple app with HTTPRoute
- `kubernetes/apps/observability/grafana/` - App with PVC and secrets
- `kubernetes/apps/network/cloudflare-tunnel/` - External exposure setup
- `kubernetes/apps/CLAUDE.md` - Detailed 3-file pattern documentation

**Important reminders:**
- Always use `postBuild.substituteFrom` in ks.yaml for variable substitution
- External apps need Cloudflare tunnel route configuration
- Secondary domain apps need explicit DNSEndpoint resources
- Include resource limits to prevent runaway consumption
