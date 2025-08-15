# Install Tailscale

We script the installation of
https://tailscale.com/kb/1236/kubernetes-operator +
https://tailscale.com/kb/1437/kubernetes-operator-api-server-proxy

The scripts are in [scripts/tailscale](../scripts/tailscale/):

1. Core Installer:
   [tailscale-operator-install.ts](../scripts/tailscale/tailscale-operator-install.ts)
2. Credentials Setup:
   [setup-tailscale-credentials.ts](../scripts/tailscale/setup-tailscale-credentials.ts)
3. Operator Install:
   [install-tailscale-operator.ts](../scripts/tailscale/install-tailscale-operator.ts)

## Usage

```bash
deno run --allow-all scripts/tailscale/tailscale-operator-install.ts
```

If you need to uninstall the operator, you can run:

```bash
deno run --allow-all scripts/tailscale/uninstall-tailscale-operator.ts
```

## Troubleshooting

For common issues including ingress lockouts and access problems, see the [Tailscale Troubleshooting Guide](./troubleshooting.md).
