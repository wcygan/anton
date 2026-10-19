# SeaweedFS maintenance availability proof

Run the local comparison with:

```sh
scripts/fixtures/seaweedfs-maintenance-availability/run.sh
```

The runner verifies SeaweedFS image digest
`sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602`
and source revision `875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa`. It creates
separate `000` and `001` stacks with a master, filer, S3 gateway, and three
volume servers. All services use a Compose network marked `internal`; the
fixture publishes no host ports, uses no host networking or cluster mounts,
and uses only a synthetic 1 MiB payload and a throwaway S3 identity. The
SeaweedFS, Python, and grpcurl images are pinned by digest. A cleanup trap
removes and verifies the absence of the fixture's containers, volumes, and
network, including after errors.

Every request goes through the signed S3 API with a 10-second client deadline.
The runner reads Filer object metadata to recover each test key's exact FID and
VID, then asks the master for its actual volume-server owners. Each outage
uses a different never-read key. The warm and cold controls must each have one
chunk, share a VID, and have different FIDs. For `001`, before each owner stop the runner
restarts Filer, waits up to 15 seconds for Filer's gRPC `LookupVolume` response
for the exact VID to show both owners, restarts S3, and verifies a warm GET's
bytes. It performs no cache refresh after stopping the owner. After restart,
it verifies Filer sees both owners again before the next hold.

The `000` comparison checks that a previously read warm key can succeed from
cache while the never-read key fails, and records a fresh PUT/GET's actual
copy count. It then rehearses migration of one existing object: stop S3 and
Filer, switch only the master process to default `001` while retaining its
data volume, mark the exact source VID read-only under the master lock, restart
the source, and verify its persisted `.vif` and master read-only state. The
runner configures that VID for `001`, copies it to a verified-empty server,
and requires equal `.dat`, `.idx`, and `.vif` hashes while both `.vif` files
remain read-only. Only after equality does it mark both replicas writable.
It then verifies both `.vif` markers are writable and waits up to 30 seconds
for `/dir/status` to include the VID in the `001` writable layout. The output
includes the exact layout response, `volume.list` diagnostics, and source and
target `.dat` sizes against the 8 MiB fixture limit before reopening Filer and
S3.

Observed on 2026-10-19 with the pinned image and the final internal-network
runner before adding the `/dir/status` assignment assertion:

- The `000` cold key had one owner on VID 1. With that owner stopped, the
  warm GET returned the expected digest in 0.038s and the never-read GET
  timed out at 10.055s. A fresh PUT and GET succeeded in 0.253s and 0.042s;
  metadata showed one copy on a surviving server.
- In the migration rehearsal, source and target `.dat`, `.idx`, and `.vif`
  hashes matched. The source `.dat` was 4,194,632 bytes, below the 8 MiB
  volume limit. Both copies were marked writable after hash equality. A direct
  `/dir/status` read showed VID 1 in the `001` writable list and both volume
  servers in topology. The FID and VID stayed unchanged.
- For the migrated VID, both independent never-read GETs succeeded with the
  expected digest while each owner was stopped (0.038s and 0.052s). Fresh
  PUT/GET operations also returned exact bytes and metadata showed two owners
  on surviving servers.
- In the independent `001` stack, two separately placed cold keys both
  returned exact bytes during their respective owner holds (0.044s and
  0.046s). Fresh writes had two owners excluding the stopped server, and all
  fresh GETs returned the expected digest.

This is a local single-volume-server test with Filer and S3 explicitly
refreshed before each planned hold. It does not establish unplanned node-failure
HA, simultaneous loss of every process on a drained Kubernetes node, CSI
reattachment behavior, network convergence, or maintenance duration. The copy
rehearsal is quiesced; it does not test migration with active writers. The
measured latencies apply only to this local Docker runtime and 1 MiB payload.

An earlier sequential migration experiment failed its second cold GET when
processes reused a one-location lookup after a server returned. That run did
not capture each cache layer's state. The final preparation observes each
Filer response and refreshes S3 before each independent hold. S3's own map
contents/completeness remain unassessed; the actual owner-absent cold GET is
the outcome evidence. This fixture does not establish that every later
maintenance window can skip those preparation gates.
