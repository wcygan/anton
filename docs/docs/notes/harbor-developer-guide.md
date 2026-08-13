# Harbor Developer Guide

Use this guide to push and pull container images through Anton's Harbor
registry. Keep credentials outside command arguments, logs, and retained output.

## Endpoint and client matrix

| Use | Endpoint | Client location | Transport |
|---|---|---|---|
| LAN push or pull | `192.168.1.106` | Laptop or cluster node | HTTP |
| Local tunnel push | `127.0.0.1:18081` | Host-native client | HTTP |
| Cluster image pull | `192.168.1.106/library/<image>` | Kubernetes node | HTTP |
| Web UI | `https://registry.<tailnet-name>.ts.net` | Browser | HTTPS |

Cluster nodes run `linux/amd64`. Build and publish that platform explicitly.

The Docker engine can use a different network namespace from the command-line
process. Docker Desktop and similar runtimes can place the engine in a virtual
machine. That engine's `127.0.0.1` might not reach a Mac host port-forward.

## Credential boundary

Use a scoped Harbor robot account for image pushes. Keep its token in the
approved secret manager. Use protected standard input for authentication.

Do not retrieve the Harbor admin password from a Kubernetes Secret for routine
pushes. Do not place any password or token in a command argument.

Obtain explicit approval before each image push. A local port-forward needs
separate approval.

Create one isolated authentication directory before either push flow:

```sh
harbor_auth_dir="$(mktemp -d /tmp/anton-harbor-auth.XXXXXX)"
chmod 700 "$harbor_auth_dir"
```

Use this directory for every authenticated client command. Run the cleanup
gate after a success or failure.

## Repository paths

OCI image references use this shape:

```text
<registry>/library/<image>:<tag>
```

Harbor management API references use this separate shape:

```text
/api/v2.0/projects/library/repositories/<url-encoded-repository>
```

The `library` project permits anonymous pulls. Pushes still require authentication.

## LAN push

Harbor's LAN endpoint uses HTTP. Configure the Docker engine to treat
`192.168.1.106` as an insecure registry before this flow.

```sh
DOCKER_CONFIG="$harbor_auth_dir" mise exec -- docker login \
  192.168.1.106 --username <robot-account>
DOCKER_CONFIG="$harbor_auth_dir" mise exec -- docker buildx build \
  --platform linux/amd64 \
  --tag 192.168.1.106/library/myapp:v1 \
  --push .
```

The login command prompts for the token. Keep terminal logging disabled.

## Local port-forward push

Use this flow when LAN access is unavailable. Obtain approval before starting
the port-forward.

Start the tunnel in a dedicated terminal. Keep it in the foreground:

```sh
mise exec -- kubectl -n registries port-forward svc/harbor 18081:80
```

From another terminal, inspect the unauthenticated challenge:

```sh
mise exec -- curl -sS -D - -o /dev/null http://127.0.0.1:18081/v2/ \
  | rg -i '^www-authenticate:'
```

The upload endpoint and token realm must be reachable from the same client
network namespace. Stop when the challenge points to an unreachable address.

### Build and verify the archive

Use Docker only for the local build and archive creation:

```sh
mise exec -- docker buildx build \
  --platform linux/amd64 \
  --load \
  --tag myapp:v1 .
mise exec -- docker image inspect myapp:v1 \
  --format '{{.Os}}/{{.Architecture}}'
mise exec -- docker save --output /tmp/myapp-v1-linux-amd64.tar myapp:v1
mise exec -- wc -c /tmp/myapp-v1-linux-amd64.tar
mise exec -- shasum -a 256 /tmp/myapp-v1-linux-amd64.tar
mise exec -- tar -tf /tmp/myapp-v1-linux-amd64.tar >/dev/null
```

Require `linux/amd64` and a successful archive listing. Stop after an
unexpected EOF, changed byte count, or failed archive listing.

The prior large-image incident did not retain enough evidence for a narrower
truncation repair. Recreate the archive before another push.

If an archive crosses a process or host boundary, verify its byte count and
checksum at both ends before import. Do not trust the transfer exit alone.

### Authenticate and push from the host

Pass the robot token from the approved secret manager through standard input:

```sh
mise exec -- op read 'op://anton/<harbor-robot-item>/<token-field>' \
  | DOCKER_CONFIG="$harbor_auth_dir" mise exec -- crane auth login \
      --insecure 127.0.0.1:18081 \
      --username <robot-account> \
      --password-stdin
```

Push one archive to one repository tag:

```sh
DOCKER_CONFIG="$harbor_auth_dir" mise exec -- crane push \
  --insecure \
  /tmp/myapp-v1-linux-amd64.tar \
  127.0.0.1:18081/library/myapp:v1
```

Do not substitute `docker push localhost:18081` on macOS without proving the
Docker engine shares the host loopback path.

### Verify the remote image

```sh
DOCKER_CONFIG="$harbor_auth_dir" mise exec -- crane digest \
  --insecure 127.0.0.1:18081/library/myapp:v1
DOCKER_CONFIG="$harbor_auth_dir" mise exec -- crane config \
  --insecure 127.0.0.1:18081/library/myapp:v1 \
  | mise exec -- jq -r '"\(.os)/\(.architecture)"'
```

Record the digest and require `linux/amd64` before editing any manifest.

### Clean up

Stop the foreground port-forward with `Ctrl-C`. Remove the run-owned
authentication directory and archive:

```sh
case "$harbor_auth_dir" in
  /tmp/anton-harbor-auth.*|/private/tmp/anton-harbor-auth.*)
    ;;
  *)
    exit 1
    ;;
esac
rm -f -- "$harbor_auth_dir/config.json"
rmdir -- "$harbor_auth_dir"
rm -f -- /tmp/myapp-v1-linux-amd64.tar
```

If `rmdir` fails, inspect the directory. Obtain approval before recursive deletion.

Verify that no temporary listener remains. Keep only the remote digest and
nonsecret archive checksum in retained evidence.

## Kubernetes pulls

The public `library` project does not require an image pull Secret:

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

Private projects require a scoped robot account and an ExternalSecret-managed
`kubernetes.io/dockerconfigjson` Secret.

## Troubleshooting

### Direct tailnet push fails

Harbor currently returns an HTTP token realm for the tailnet hostname. The
Tailscale ingress serves HTTPS. Use the approved host-native tunnel flow.

### The local tunnel works with curl, but Docker fails

Confirm where the Docker engine runs. Host curl success does not prove that a
virtual-machine engine can reach host loopback.

### Push fails before upload

Check the registry scheme, token realm, client namespace, and repository path.
An HTTP tunnel must use an insecure-capable client.

### Push stops during a large layer

Retain the client exit status and archive byte count. Recheck the archive
checksum and listing. Recreate the archive when either value changes.

### A Pod reports an architecture error

Inspect the remote image configuration. Publish `linux/amd64`, then update the
committed digest through review.

## Further reading

- [Harbor registry architecture](./harbor-registry.md)
- ADR 0015 for Harbor storage and anonymous-pull decisions.
