# SeaweedFS stale-address comparison

Run the real SeaweedFS 4.40 filer stream path against a deterministic volume-server transition:

```sh
mise exec -- scripts/fixtures/seaweedfs-address-recovery/run.sh
```

The helper clones SeaweedFS revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa` into a temporary directory, overlays the Go test, and removes the checkout on exit. Each case holds a request on the old listener, registers a replacement destination, and withdraws the old server before checking the in-flight read and a follow-up read.

The Pod-IP case continues to target the departed listener and both reads fail. The stable-hostname case keeps the URL unchanged, resolves the next dial to the replacement listener, and verifies the exact bytes returned by `PrepareStreamContentWithThrottler`. The already in-flight read fails in both cases. The acceptance limit is one second from replacement registration through the successful follow-up read in this local deterministic test.

This proves reconnection on a subsequent chunk read after name resolution changes. The already in-flight read fails when its old connection is withdrawn, and the fixture does not establish same-request recovery. Its injected resolver is deterministic and does not verify Kubernetes CoreDNS TTLs, StatefulSet DNS publication, or production connection reuse. Those require the authorized cluster acceptance run.
