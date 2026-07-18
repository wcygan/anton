# Host-agent image procedure

Harbor is LAN-only (`192.168.1.106`), so build, digest lookup, and Trivy scan
run in short-lived in-cluster Jobs; do not attempt them from the host. The
builder is `gcr.io/kaniko-project/executor@sha256:c3109d5926a997b100c4343944e06c6b30a6804b2f9abe0994d3de6ef92b028e`.
The scanner is `aquasec/trivy@sha256:6967db29ce5294d054121e94b3cb1262de858af63b4547bb1bade66a4306f2e4`.

For each Dockerfile, create a ConfigMap named `host-agent-build-context` with
`--from-file=Dockerfile=containers/<name>/Dockerfile`, then create a
`registries` Job with `automountServiceAccountToken: false`, no host mounts,
and an `emptyDir` mounted at `/docker`. Its `registry-auth` init container
must use only `secretKeyRef` `harbor-admin-secret/HARBOR_ADMIN_PASSWORD` to
write `/docker/config.json` for username `admin`. The non-privileged Kaniko
container runs as UID 0 (required to unpack base-image ownership metadata),
with `allowPrivilegeEscalation: false`, and mounts the ConfigMap file at
`/workspace/Dockerfile`. It runs:

```sh
/kaniko/executor --context=dir:///workspace --dockerfile=/workspace/Dockerfile \
  --destination=192.168.1.106/library/<name>:<version> --insecure --reproducible
```

Capture the pushed digest from Kaniko's non-secret `Pushed ...@sha256:` log,
then use `:<tag>@sha256:<digest>` in the DaemonSet. Run the pinned Trivy image
against that immutable reference and record normalized HIGH/CRITICAL counts.
Use `busybox:1.37.0@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028`
for the auth init container. Scan with `trivy image --quiet --insecure
--scanners vuln --format json 192.168.1.106/library/<name>:<version>@sha256:<digest>`.
Delete temporary resources with `kubectl -n registries delete job/<name>
--wait=true` and `kubectl -n registries delete configmap/host-agent-build-context
--wait=true`; the `emptyDir` docker config disappears with the Pod.

Current 0.1.1 releases:

- `storage-vxlan:0.1.1@sha256:4963bcf50365220415a02eece7a32c42466b7ead21e36e47028bf02cc7cbcd81`
- `nvme-power-collector:0.1.1@sha256:a190eb1d473ce16a01100e3c9427b353b9ee864554a4ef6de1571ab4d0a35841`
