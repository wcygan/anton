# Harbor Developer Guide

Quick reference for pushing and pulling container images against anton's
Harbor registry.

## TL;DR endpoints

| Use | Endpoint | Auth |
|---|---|---|
| `docker push` (on-LAN laptop) | `192.168.1.106` | admin or robot account |
| `docker push` (remote laptop) | `registry.<tailnet-name>.ts.net` | admin or robot account, via Tailscale |
| `docker pull` from cluster Pod | `192.168.1.106/library/<image>` | **none** — `library` is anonymous-pull |
| Web UI | `https://registry.<tailnet-name>.ts.net` | admin or your account |

**Platform note.** Cluster nodes run `linux/amd64`. On an Apple Silicon Mac,
always build with `--platform linux/amd64` or Pods will fail to start.

## Getting credentials

```sh
# Admin password (for the Harbor web UI and for pushing)
kubectl -n registries get secret harbor-admin-secret \
  -o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}' | base64 -d
```

You'll typically create a scoped **robot account** in the Harbor UI for
scripted/CI pushes rather than reusing the admin credentials directly.

## Docker insecure-registry setup (LAN)

Harbor's LAN endpoint is HTTP. Docker requires explicit opt-in.

**Docker Desktop** → *Settings* → *Docker Engine* → add:

```json
{
  "insecure-registries": ["192.168.1.106"]
}
```

Apply & restart the engine.

**Remote/Tailscale path** is HTTPS via the operator's issued cert; no
insecure-registry flag is needed there, but `docker login` targets the
Tailscale hostname.

## Push an image

```sh
# On-LAN, HTTP:
docker login 192.168.1.106
docker tag myapp:v1 192.168.1.106/library/myapp:v1
docker push 192.168.1.106/library/myapp:v1

# Over Tailscale, HTTPS:
docker login registry.<tailnet-name>.ts.net
docker tag myapp:v1 registry.<tailnet-name>.ts.net/library/myapp:v1
docker push registry.<tailnet-name>.ts.net/library/myapp:v1
```

Both resolve to the same Harbor and the same SeaweedFS `harbor` bucket.
`library` is the default public project; ask for a new project in the
Harbor UI if you want auth-gated pulls or per-team separation.

## Pull from Kubernetes (no pull secret needed)

`library` is configured for anonymous pull, so cluster Pods can reference
Harbor images directly:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: myapp
  namespace: default
spec:
  containers:
    - name: myapp
      image: 192.168.1.106/library/myapp:v1
```

No `imagePullSecrets`, no ServiceAccount patching, no per-namespace
`docker-registry` Secret. The Talos machine-registries patch plus the
Spegel peer cache handles discovery; anonymous-pull handles auth.

For **private projects**, create a robot account in the Harbor UI with
`Pull` scope on that project, stash its token in 1Password, and pull it
into the target namespace via an ExternalSecret of kind
`kubernetes.io/dockerconfigjson`.

## Build + push in one shot (ARM Mac)

```sh
docker build --platform linux/amd64 -t 192.168.1.106/library/myapp:v1 .
docker push 192.168.1.106/library/myapp:v1
```

Verify the manifest architecture:

```sh
docker manifest inspect 192.168.1.106/library/myapp:v1 \
  | jq '.manifests // [{architecture}] | .[].platform // .[].architecture'
```

## Off-LAN push — use Tailscale, not port-forward

If you're off-LAN, sign into Tailscale and push to the Tailscale hostname
directly:

```sh
docker login registry.<tailnet-name>.ts.net
docker push registry.<tailnet-name>.ts.net/library/myapp:v1
```

No `kubectl port-forward` shenanigans needed — the Tailscale operator
handles TLS termination with a browser-trusted cert.

## Troubleshooting

### `unauthorized` on push/pull

Robot tokens expire or admin passwords drift. `docker login` again.

### `Image pull failed` from a Pod

Two likely causes:

1. **Talos machine-registries patch not applied on that node.** Verify:
   ```sh
   talosctl --endpoints <tailscale-ip> --nodes <tailscale-ip> \
     get machineconfig -o yaml | yq '.spec.machine.registries.mirrors'
   ```
   Should show `192.168.1.106 → http://192.168.1.106`.
2. **Non-`library` project without auth.** Create a robot account for the
   project and project-scoped `imagePullSecret`.

### Architecture mismatch

Check `docker inspect myapp:v1 | jq '.[0].Architecture'`. If it says `arm64`,
rebuild with `--platform linux/amd64`.

### Can reach `curl http://192.168.1.106` but push fails with TLS

You didn't add `192.168.1.106` to Docker's `insecure-registries`.

## Further reading

- [Harbor registry architecture](./harbor-registry.md) — endpoints, storage
  backend, admin credentials, troubleshooting the cluster side.
- ADR 0015 — the decision record for running Harbor on SeaweedFS S3 with
  anonymous pull on `library`.
