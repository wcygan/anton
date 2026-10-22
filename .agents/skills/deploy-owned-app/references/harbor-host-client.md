# Harbor host-native image handoff

Use this only when a verified authentication challenge requires it. A port-forward is a live mutation: obtain approval for the exact service, local port, interval, and cleanup before starting one. Do not infer approval from a request to inspect image metadata.

1. Inspect the unauthenticated `/v2/` response and its `WWW-Authenticate` header from the intended client namespace. The registry endpoint and token realm must agree on reachable host, port, and scheme.
2. If using an approved forward, keep it in the foreground. Use a loopback-only endpoint and host-native client; a Docker engine running in a VM may have different loopback reachability.
3. Build a `linux/amd64` image and export it to a run-owned archive. Verify architecture, archive listing, byte count, and SHA-256 before import, and again after any transfer. Recreate a truncated archive rather than guessing at partial contents.
4. Use a run-owned temporary authentication directory. Read the token from its approved secret manager and feed it to the client's password-stdin interface. Never put credentials in arguments, logs, or committed files.
5. Push exactly the approved image repository and tag using a host-native registry client. For an intentionally HTTP loopback tunnel, use that client's explicit HTTP mode only for the approved local endpoint; do not weaken a remote TLS endpoint.
6. Read the remote digest and image configuration. Require the expected digest and `linux/amd64` before preparing a deployment change. A successful transfer alone is insufficient evidence.
7. Stop the foreground forward, remove only run-owned credential and archive files, and confirm no tunnel remains. Deployment and registry credential changes retain separate authority boundaries.

For `crane`, the relevant operations are `auth login --password-stdin`, `push`, `digest`, and `config`. Check the installed CLI before constructing a command; select endpoint and authentication source from private operator configuration. This reference preserves the procedure without publishing real identities or endpoints.
