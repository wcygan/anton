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

## Credential readiness gate

Complete the local image gate first. Verify the selected 1Password account
before archive creation:

```sh
mise exec -- op whoami --account <account>
```

Stop before archive creation when this check fails. A user readiness message
does not replace the CLI result.

Create and validate the archive. Then authorize secret manager access before
the port-forward starts.

Write the required credential only to a run-owned, mode `600` authentication
file. Do not print the credential or retain it after cleanup.

On an authorization timeout, remove the exact run-owned files and stop. Require
user readiness before one replacement authorization request. Do not loop prompts.

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

## Dependent image order

Use this order when one image embeds another image digest:

1. Publish the dependency image.
2. Record its verified remote digest.
3. Update the consumer source with that digest.
4. Rebuild the consumer image.
5. Inspect the consumer image and verify the embedded digest.
6. Publish the consumer image.
7. Update the deployment digests.

Never build the consumer before the dependency remote digest exists. Stop when
the embedded digest and dependency digest differ.

## Cleanup gate

- Stop the port-forward.
- Remove known files from the validated authentication directory.
- Require approval before any recursive directory deletion.
- Remove any run-owned archive after its digest is retained.
- Verify that no temporary listener or credential file remains.
- Review only the intended manifest digest change.

Report both image digests and their embedded-digest comparison when images have
a dependency. Also report the source revision, tags, platform, archive checksum,
tunnel cleanup, and any unverified transfer behavior.
