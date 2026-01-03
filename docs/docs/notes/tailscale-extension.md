# Tailscale Extension for Talos Nodes

Enable Tailscale on Talos nodes so they can access services exposed via Tailscale (e.g., Harbor registry at `https://registry.<tailnet>.ts.net`).

## Why This Is Needed

Kubernetes nodes need to pull container images from Harbor. Harbor is exposed via Tailscale Ingress with valid Let's Encrypt TLS. Without Tailscale on the nodes, containerd cannot reach the registry.

**Alternative considered**: Configure containerd to trust an internal HTTP endpoint. Rejected because it requires different image URLs for push (external) vs pull (internal).

## Configuration

### 1. Talos Schematic with Tailscale Extension

Generate at [factory.talos.dev](https://factory.talos.dev):

```yaml
customization:
  systemExtensions:
    officialExtensions:
      - siderolabs/i915
      - siderolabs/intel-ucode
      - siderolabs/tailscale
```

Current schematic ID: `08086db1d88ea52b2e873f0b0c64562af7ae98f6ed83da5ee478871bbe52abd6`

Verify with:
```bash
curl -s "https://factory.talos.dev/schematics/<ID>"
```

### 2. Encrypted Auth Key

Store the Tailscale auth key in `talos/talenv.sops.yaml`:

```yaml
TAILSCALE_AUTHKEY: tskey-auth-xxxxx
```

Encrypt with:
```bash
sops --encrypt --in-place talos/talenv.sops.yaml
```

**Important**: Use a reusable auth key from the Tailscale admin console, not a one-time key.

### 3. ExtensionServiceConfig Patch

File: `talos/patches/global/tailscale.yaml`

```yaml
apiVersion: v1alpha1
kind: ExtensionServiceConfig
name: tailscale
environment:
  - TS_AUTHKEY=${TAILSCALE_AUTHKEY}
```

Reference in `talos/talconfig.yaml`:
```yaml
patches:
  - "@./patches/global/tailscale.yaml"
```

### 4. Update Node Image URLs

In `talos/talconfig.yaml`, update all nodes to use the new schematic:

```yaml
talosImageURL: factory.talos.dev/installer/08086db1d88ea52b2e873f0b0c64562af7ae98f6ed83da5ee478871bbe52abd6
```

## Applying Changes

### Why Two Steps Are Required

1. **`talosctl upgrade`** installs the new Talos image (with Tailscale extension) but does NOT apply config changes like `ExtensionServiceConfig`

2. **`talosctl apply-config`** applies configuration changes but does NOT upgrade the Talos image (changing `machine.install.image` only affects future fresh installs)

Without both steps, the service waits indefinitely:
```
ext-tailscale   Waiting   Waiting for extension service config
```

### Optimized Approach: Config First, Then Upgrade (One Reboot)

Apply the config first (stages it), then upgrade. The extension finds the config immediately after upgrade:

**Step 1**: Apply config (stages ExtensionServiceConfig, no reboot yet)
```bash
talosctl apply-config -n <node-ip> -f talos/clusterconfig/kubernetes-<hostname>.yaml --mode=staged
```

**Step 2**: Upgrade the node (installs extension, reboots, extension starts with config ready)
```bash
mise exec -- task talos:upgrade-node IP=<node-ip>
```

### Alternative: Upgrade First, Then Apply (Two Reboots)

If you upgrade first, the extension waits for config. Then apply-config triggers another reboot:

```bash
# Step 1: Upgrade (extension waits for config)
mise exec -- task talos:upgrade-node IP=<node-ip>

# Step 2: Apply config (triggers reboot)
talosctl apply-config -n <node-ip> -f talos/clusterconfig/kubernetes-<hostname>.yaml
```

After completion, verify:

```bash
# Check config exists
talosctl get extensionserviceconfigs -n <node-ip>

# Check service is running
talosctl services -n <node-ip> | grep tailscale

# Check logs
talosctl logs ext-tailscale -n <node-ip>
```

## Verification

After successful setup, the node should:

1. Have `ExtensionServiceConfig` for tailscale:
   ```
   NODE           NAMESPACE   TYPE                     ID          VERSION
   192.168.1.98   runtime     ExtensionServiceConfig   tailscale   1
   ```

2. Show `ext-tailscale` as Running:
   ```
   192.168.1.98   ext-tailscale   Running   Started task ext-tailscale (PID xxx)
   ```

3. Have a `tailscale0` interface with a 100.x.x.x IP in the logs

## File Locations

| Component | Path |
|-----------|------|
| Tailscale patch | `talos/patches/global/tailscale.yaml` |
| Encrypted auth key | `talos/talenv.sops.yaml` |
| Node configs | `talos/talconfig.yaml` |
| Generated configs | `talos/clusterconfig/kubernetes-*.yaml` |

## Troubleshooting

### Service stuck "Waiting for extension service config"

The `ExtensionServiceConfig` wasn't applied. Run:
```bash
talosctl apply-config -n <node-ip> -f talos/clusterconfig/kubernetes-<hostname>.yaml
```

### Auth key issues

- Ensure the key is reusable (not one-time)
- Ensure no quotes around the key value in the config
- Generate a fresh key from Tailscale admin console

### Check actual config on node

```bash
talosctl get extensionserviceconfigs -n <node-ip> -o yaml
```
