# Harbor Image Handoff

Use this reference for one approved lakehouse image handoff. The human command
path lives in `docs/docs/notes/harbor-developer-guide.md`.

## Authority boundaries

An image handoff can cross four separate boundaries:

1. Build one local image.
2. Start one local-only Kubernetes port-forward.
3. Authenticate and push one repository tag.
4. Edit one committed digest.

Obtain separate approval for the port-forward and push. Repository authority
does not grant either live action.

## Preflight record

Record these values before a push:

- Dockerfile and source revision.
- Local image tag and `linux/amd64` platform.
- Client network namespace.
- Registry endpoint and HTTP or HTTPS transport.
- Token challenge realm.
- Harbor project and repository.
- Isolated authentication directory and cleanup owner.
- Archive path, byte count, and checksum.
- Port-forward process and cleanup owner.

The OCI repository path is `library/<image>`. Harbor management API paths use
`/api/v2.0/projects/library/repositories/...`. Keep these path types separate.

## Client locality

| Client location | Host loopback result |
|---|---|
| Native Mac or Linux process | Reaches a localhost-only port-forward. |
| Docker engine on the Linux host | Reaches host loopback. |
| Docker Desktop or another virtual machine | Loopback can identify the virtual machine. |
| Cluster node or Pod | Uses the committed LAN registry endpoint. |

The upload endpoint and token challenge realm must be reachable from the same
client network namespace. Stop when either address resolves elsewhere.

Use the host-native `crane` path for a localhost-only tunnel on macOS. The
Docker engine path requires separate proof that its loopback reaches the host.

## Verified local Harbor route

Use `svc/harbor-core 18083:80` for a local tunnel. Use
`harbor.localtest.me:18083` in curl and Crane commands. Resolve that alias to
`127.0.0.1` for curl. Set `NO_PROXY` and `no_proxy` to the alias and loopback
addresses for Crane.

This preserves the Harbor token realm. A `127.0.0.1` image reference can
receive a token realm that the client cannot use through the local tunnel.

Use one pre-provisioned, scoped robot account for normal pushes. If an
approved automation run creates a temporary robot, use a unique timestamped
name, limit it to `library` repository push and pull, set a short expiry, and
delete its exact Harbor robot ID during cleanup. Do not retain the token.

## Archive and platform gate

Build for `linux/amd64`. Before transfer, record the archive byte count and
SHA-256 checksum. Require a successful archive listing.

Stop after an unexpected EOF, changed byte count, or failed archive listing.
Recreate the archive before another push. The prior incident did not retain
enough evidence for a more specific truncation repair.

If an archive crosses a process or host boundary, verify its byte count and
checksum at both ends before import. A successful transfer exit is insufficient.

After the push, verify the remote digest and remote image configuration. The
configuration must report `linux/amd64` before a manifest edit.

## Cleanup gate

- Stop the port-forward.
- Remove known files from the validated authentication directory.
- Require approval before any recursive directory deletion.
- Remove any run-owned archive after its digest is retained.
- Verify that no temporary listener or credential file remains.
- Review only the intended manifest digest change.

Report the source revision, repository tag, remote digest, platform, archive
checksum, tunnel cleanup, and any unverified transfer behavior.
