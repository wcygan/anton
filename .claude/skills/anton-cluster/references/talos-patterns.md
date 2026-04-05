# Talos Patterns

Conventions for the `talos/` tree, talhelper, patches, node inventory, and the bootstrap-to-Flux handoff.

## 1. `/talos` Directory Layout

```
talos/
├── talconfig.yaml         # Rendered by Makejinja from templates/ — NOT hand-edited
├── talenv.yaml            # Hand-edited: talosVersion + kubernetesVersion pins
├── talenv.sops.yaml       # Hand-edited, encrypted: TS_AUTHKEY, Harbor robot creds, etc.
├── talsecret.sops.yaml    # Generated once at bootstrap; cluster/etcd/k8s certs; encrypted
├── clusterconfig/         # Generated per-node machine configs; gitignored
│   ├── .gitignore         # Excludes kubernetes-k8s-*.yaml and talosconfig
│   ├── kubernetes-<host>.yaml  # (gitignored) per-node rendered machine config
│   └── talosconfig        # (gitignored) talosctl client config
└── patches/
    ├── README.md
    ├── global/            # Applied to ALL nodes
    ├── controller/        # Applied to control plane nodes only
    ├── worker/            # Applied to worker nodes only (if any)
    └── <hostname>/        # Per-node patches (optional)
```

Generated vs hand-edited:
- **Hand-edited**: `talenv.yaml`, `talenv.sops.yaml`, patches, `templates/` sources (never `talconfig.yaml` directly)
- **Generated**: `talconfig.yaml` (from templates), `clusterconfig/*.yaml` (by talhelper), `talsecret.sops.yaml` (once, at bootstrap)
- **Gitignored**: `talos/clusterconfig/kubernetes-*.yaml`, `talos/clusterconfig/talosconfig`, and top-level `age.key`, `kubeconfig`

## 2. talconfig.yaml and the Template Pipeline

`talos/talconfig.yaml` is rendered from `templates/config/talos/talconfig.yaml.j2` using Makejinja. Inputs:

- `cluster.yaml` — CIDRs, load balancer IPs, repository, Cloudflare config
- `nodes.yaml` — per-node definitions
- `templates/scripts/plugin.py` — custom Jinja filters (`nthhost`, `basename`, `talos_patches`, `age_key`)

Rendered shape (top-level keys):

```yaml
clusterName: kubernetes
talosVersion: "${talosVersion}"          # From talenv.yaml
kubernetesVersion: "${kubernetesVersion}"
endpoint: https://<cluster_api_addr>:6443
additionalApiServerCertSans: [...]
clusterPodNets: ["10.42.0.0/16"]         # From cluster.yaml
clusterSvcNets: ["10.43.0.0/16"]
cniConfig:
  name: none                              # Cilium manages CNI
nodes: [...]                              # Rendered from nodes.yaml
patches: [...]                            # References to patches/global/*.yaml
controlPlane:
  patches: [...]                          # References to patches/controller/*.yaml
worker:
  patches: [...]                          # (only if workers exist)
```

Node entry shape:

```yaml
- hostname: "k8s-1"
  ipAddress: "<node-ip>"
  installDiskSelector:
    serial: "<disk-serial>"               # OR installDisk: "/dev/sda"
  machineSpec:
    secureboot: false
  talosImageURL: factory.talos.dev/installer/<schematic-id>
  controlPlane: true
  networkInterfaces:
    - deviceSelector:
        hardwareAddr: "<mac>"
      dhcp: false
      addresses: ["<node-ip>/24"]
      routes:
        - network: "0.0.0.0/0"
          gateway: "<gateway-ip>"
      mtu: 1500
      vip:
        ip: "<cluster_api_addr>"          # Control plane VIP only
```

**Never edit `talconfig.yaml` directly.** Change `nodes.yaml` / `cluster.yaml` / a template, then run `task configure`.

## 3. Patches

Patches are partial Talos machine configs, applied on top of the generated base. They live in `talos/patches/<scope>/<name>.yaml` and are referenced from `talconfig.yaml` using the `@./patches/...` syntax that talhelper resolves relative to the talconfig file.

### Scopes

| Dir | Applied to |
|---|---|
| `global/` | All nodes (control plane + workers) |
| `controller/` | Control plane nodes only |
| `worker/` | Worker nodes only |
| `<hostname>/` | That node only (optional, the template loops on `talos_patches('<hostname>')`) |

### Observed global patches

| File | Purpose |
|---|---|
| `machine-files.yaml` | Write containerd config tweaks (unpack discard, device ownership) |
| `machine-kubelet.yaml` | Kubelet `extraConfig` + `nodeIP.validSubnets` |
| `machine-network.yaml` | Registry mirrors (Harbor), registry auth, DNS servers, static host entries |
| `machine-sysctls.yaml` | inotify limits, QUIC buffers, ARP thresholds, user namespaces |
| `machine-time.yaml` | NTP servers |
| `tailscale.yaml` | Tailscale extension — `TS_AUTHKEY` from `talenv.sops.yaml`, `TS_STATE_DIR=mem:` |

### controller scope

`controller/cluster.yaml` — allow scheduling on control planes, API server aggregation routing, pod GC threshold, disable built-in CoreDNS + kube-proxy (Cilium replaces them), etcd metrics/advertised subnets, scheduler/controller-manager bind addresses.

### Patch file format

Just the subset to merge:

```yaml
machine:
  kubelet:
    extraConfig:
      serializeImagePulls: false
    nodeIP:
      validSubnets: ["<node_cidr>"]
```

## 4. Secrets in Talos

Two encrypted files, both SOPS + Age.

- **`talsecret.sops.yaml`** — generated once at bootstrap via `talhelper gensecret`. Contains cluster ID, etcd certs, k8s API/aggregator/service-account certs, trust device token, bootstrap token. Never hand-edited.
- **`talenv.sops.yaml`** — hand-edited (SOPS supports in-place edit). Holds env vars consumed by patches: Tailscale auth key, Harbor robot credentials, etc.

SOPS rules in `.sops.yaml`:
- `talos/*.sops.ya?ml` — encrypts the entire file (because Talos configs aren't data/stringData shaped)
- `(bootstrap|kubernetes)/*.sops.ya?ml` — encrypts only `data`/`stringData` fields

Both rulesets share the same Age public recipient (defined in `.sops.yaml`). The private key is `age.key` at the repo root, gitignored. Backup is in the 1Password `anton` vault.

Flow: `task configure` runs an `encrypt-secrets` step that calls `sops --encrypt --in-place` on any `*.sops.*` file that `sops filestatus` reports as unencrypted (idempotent).

## 5. Generate + Apply Flow (talhelper)

talhelper is the tool; tasks wrap it with preflight checks.

| Task | Under the hood | When to run |
|---|---|---|
| `task talos:generate-config` | `cd talos && talhelper genconfig` | After changing `talconfig.yaml`, patches, or `talenv.yaml` |
| `task talos:apply-node IP=<ip> MODE=auto` | `talhelper gencommand apply --node <ip> --extra-flags '--mode=auto' \| bash` | After regenerating configs |
| `task talos:upgrade-node IP=<ip>` | `talhelper gencommand upgrade --node <ip> --extra-flags "--image=...${talosImageURL}... --timeout=10m" \| bash` | After bumping `talosVersion` in `talenv.yaml` |
| `task talos:upgrade-k8s` | `talhelper gencommand upgrade-k8s --extra-flags "--to '${kubernetesVersion}'" \| bash` | After bumping `kubernetesVersion` in `talenv.yaml` |
| `task talos:reset` | `talosctl reset` | **DESTRUCTIVE** — explicit confirmation only |

Apply modes:
- `auto` — automatic reboot if required
- `staged` — write config, apply at next reboot
- `no-reboot` — reject changes that would need a reboot

### Bootstrap sequence (`task bootstrap:talos`)

1. `talhelper gensecret | sops --encrypt > talsecret.sops.yaml` (only if it doesn't exist)
2. `talhelper genconfig` — render machine configs
3. `talhelper gencommand apply --insecure | bash` — apply over insecure API (no certs yet)
4. `talhelper gencommand bootstrap | bash` — bootstrap etcd on the first control plane
5. `talhelper gencommand kubeconfig --extra-flags="$ROOT_DIR --force" | bash` — fetch kubeconfig

After this, `task bootstrap:apps` takes over (Cilium → CoreDNS → Spegel → cert-manager → Flux).

### Regeneration triggers

| Change | Command |
|---|---|
| `nodes.yaml` or `cluster.yaml` | `task configure` → `task talos:generate-config` → `task talos:apply-node` per node |
| Any file under `talos/patches/` | `task talos:generate-config` → `task talos:apply-node` per affected node |
| `talenv.yaml` (version bumps) | `task configure` (re-renders talconfig) → `task talos:upgrade-node` or `task talos:upgrade-k8s` |

## 6. talenv.yaml

```yaml
# renovate: datasource=docker depName=ghcr.io/siderolabs/installer
talosVersion: v1.12.0

# renovate: datasource=docker depName=ghcr.io/siderolabs/kubelet
kubernetesVersion: v1.35.0
```

Hand-edited (with Renovate auto-bump comments). Two pins drive all upgrades. Template references them as `${talosVersion}` and `${kubernetesVersion}`. Always bump the pin **before** running the corresponding upgrade task.

## 7. nodes.yaml

```yaml
nodes:
  - name: k8s-1
    address: <node-ip>
    controller: true                     # true = control plane, false = worker
    disk: /dev/sda                       # absolute path OR serial string
    mac_addr: <mac>
    schematic_id: <64-char-hex>          # From factory.talos.dev
    mtu: 1500                            # Optional, default 1500
    secureboot: false                    # Optional
    encrypt_disk: false                  # Optional, TPM-based
```

CUE schema validation (`templates/.../nodes.schema.cue`) enforces:
- Unique names, addresses, MAC addresses
- Name is lowercase alphanumeric + hyphens, cannot be `global`/`controller`/`worker`
- IPv4 addresses
- 64-char hex schematic IDs
- MTU 1450–9000

Disk is either a path (`/dev/sda`) or a serial string. Prefer serial on multi-disk machines — the template branches on the leading `/` to pick `installDisk` vs `installDiskSelector.serial`.

Schematics are per-node (different nodes can bake in different extensions), though in practice most nodes share one ID.

## 8. Bootstrap ↔ Flux Handoff

`bootstrap/` bridges bare Talos to a Flux-managed cluster. Key mechanic: bootstrap HelmReleases read values from the *same* files Flux will later use, so nothing diverges.

`bootstrap/helmfile.d/templates/values.yaml.gotmpl` contains roughly:

```gotemplate
{{ (fromYaml (readFile (printf "../../../kubernetes/apps/%s/%s/app/helmrelease.yaml"
  .Release.Namespace .Release.Name))).spec.values | toYaml }}
```

That's why `kubernetes/apps/**/helmrelease.yaml` is the single source of truth — both bootstrap and Flux consume it.

Sequence:

```
task init         → age.key, github-deploy.key, sample cluster.yaml/nodes.yaml
task configure    → render templates + encrypt SOPS files
task bootstrap:talos → talhelper genconfig + apply + bootstrap + kubeconfig
task bootstrap:apps  → helmfile: cilium → coredns → spegel → cert-manager → flux-operator → flux-instance
(Flux takes over)    → reconciles kubernetes/ from Git
```

Handoff happens when `flux-instance` deploys and starts reconciling `kubernetes/flux/cluster/ks.yaml`.

## 9. Notable / Non-Obvious Conventions

- **talconfig.yaml is templated** — unusual for Talos; most users hand-edit. Here it flows from `nodes.yaml` + `cluster.yaml` through Makejinja for consistency.
- **Patch references use `@./patches/`** — talhelper resolves `@` relative to the talconfig directory.
- **Per-node patches are rare** — global + controller cover almost everything.
- **Tailscale state is in memory** (`TS_STATE_DIR=mem:`) — nodes re-register on reboot with a `-1` suffix; manual cleanup in the Tailscale admin console is an accepted tradeoff since reboots are infrequent.
- **Harbor registry routed via containerd** — containerd runs on the host, can't resolve cluster service DNS, so `machine-network.yaml` has a static host entry mapping Harbor's service name to its ClusterIP. If Harbor's service IP changes, this must be updated.
- **`generate-config` is deliberately separate from `apply`** — lets you inspect rendered machine configs before applying to a live node.
- **Schematic IDs are public** — they identify a factory-built Talos image with baked-in extensions; safe to commit.

## 10. Quick Answer Table

| Question | Answer | Location |
|---|---|---|
| Versions? | `talenv.yaml` | `talos/talenv.yaml` |
| Node inventory? | `nodes.yaml` | repo root |
| Network ranges? | `cluster.yaml` | repo root |
| Cluster certs/secrets? | `talsecret.sops.yaml` (generated) | `talos/` |
| Auth keys (Tailscale, Harbor)? | `talenv.sops.yaml` | `talos/` |
| Kubelet tweaks? | `machine-kubelet.yaml` | `talos/patches/global/` |
| Registry config? | `machine-network.yaml` | `talos/patches/global/` |
| CNI? | Cilium HelmRelease (not in `talos/`) | `kubernetes/apps/kube-system/cilium/` |
| How is talconfig generated? | Makejinja template | `templates/config/talos/talconfig.yaml.j2` |
| Apply to node? | talhelper + talosctl | `task talos:apply-node IP=<ip>` |
| Upgrade Talos? | | `task talos:upgrade-node IP=<ip>` |
| Upgrade Kubernetes? | | `task talos:upgrade-k8s` |
| Bootstrap? | helmfile + phase script | `task bootstrap:apps` / `scripts/bootstrap-apps.sh` |
| Encrypt secrets? | SOPS + Age | `task configure` (encrypt-secrets step) |
