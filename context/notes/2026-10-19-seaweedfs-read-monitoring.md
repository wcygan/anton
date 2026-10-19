# SeaweedFS S3 read monitoring — 2026-10-19

The operator-approved change clears old S3 process caches and detects read
failures that readiness and HTTP status counters can miss. SeaweedFS remains
4.40; no volume files, PVCs, or WAL data were repaired or deleted.

## Configuration and ownership

- Existing PR #513 (`c040a67c`) already restored stable per-volume peer DNS and
  explicit `ipBind: 0.0.0.0`. That configuration was preserved.
- `8197fe06` enables S3 metrics, adds the read-only probe Secret through ESO,
  and gives the ordinary bucket provisioner ownership of the fixture bucket.
  Both old S3 gateways were replaced, clearing their cached literal IPs.
- `7e1d0c09` adds the sidecar, PodMonitor, native rules, Loki log rule, and
  explicit ntfy warning routes. `d9ed6ef6` strengthens alert fixture exclusions.
- `1bf42c06` corrects a probe startup false positive found during live rollout.

Each gateway signs GETs through its own localhost listener every minute. A
15-second process timer bounds the complete request, including a trickling
response. A successful check requires HTTP 200, exactly 65,536 bytes, and the
expected SHA-256. The fixture is `s3-read-probe/fixture-v1` (65,536 zero bytes);
filer metadata confirmed a real volume chunk, volume ID 49. A single fixture
does not cover every historical object or cached volume mapping.

The existing spark-events reader identity receives only one additional action,
`Read:s3-read-probe`. Its existing permissions are preserved. The sidecar's
separate Secret contains read-only credentials; the admin S3 config is not
mounted there. No credential values were retrieved to the workstation.

The operator owns the S3 metrics Service and ServiceMonitor. Flux owns the
probe PodMonitor, code ConfigMap, rules, and routing. The code ConfigMap hash is
referenced through a Kustomize name transformer for the Seaweed CR, so code
changes roll gateways. Probe readiness checks its metrics server independently
of storage. Failed reads therefore do not remove both gateways from service.

## Rollout finding and correction

The first implementation spawned a fresh interpreter for each request. On
`k8s-2`, imports under the 100m CPU limit took 26.60 seconds, while the complete
diagnostic finished in 27.92 seconds with a verified S3 read. The subprocess's
15-second timer expired before it sent a GET. An isolated fake-server control
on the same node reproduced the false alarm, separating probe runtime from
SeaweedFS behavior.

The corrected implementation imports once and uses a process timer around the
request. A startup probe allows 60 seconds for the metrics listener. Repeated
signed reads then succeeded on both gateways, including `k8s-2`. This preserves
the network deadline instead of hiding the failure with a larger timeout.

## Alerts and regression evidence

| Alert | Evidence |
| --- | --- |
| `SeaweedFSS3ReadFailures` | Real Loki ruler evaluation of three synthetic failure lines through the collector; normal reads, cancellations, foreign logs, old logs, and subthreshold counts are excluded in local tests. |
| `SeaweedFSS3Read5xx` | Native Prometheus tests exercise thresholds and exclude successful GETs and write failures; a labeled synthetic Alertmanager alert exercises warning delivery. |
| `SeaweedFSS3ReadProbeFailed` | Actual probe code against an isolated HTTP 200 server with a truncated body; recovery restores the correct complete body. |
| `SeaweedFSS3MonitoringUnavailable` | Native tests cover missing scrapes, missing or stalled probe output, absent desired replica counts, and duplicate targets; a labeled synthetic alert exercises warning delivery. |

All warning names are explicitly routed to ntfy; unmatched warnings remain
dropped. Critical alerts retain the existing route. HTTP 5xx alone is
insufficient because a stream can fail after successful headers are sent.

Validation: 477 contract tests passed (the optional amtool test was skipped in
that run and passed separately); 10 focused probe/manifest tests passed;
9 HTTP behavior tests also passed on the pinned linux/amd64 Python image with
a 100m CPU limit; 17 native Prometheus scenarios passed. Disposable Loki and
OTel tests exercised the actual mounted rules and collector policy. Docusaurus
typecheck and production build passed.

## Live acceptance

At 22:23 UTC, all four alert names had both firing and resolved receipts in
ntfy (eight distinct message IDs), with no increase in failed webhooks:

| Alert | Firing receipt (UTC) | Resolved receipt (UTC) |
| --- | --- | --- |
| `SeaweedFSS3Read5xx` | 22:13:09 | 22:18:09 |
| `SeaweedFSS3MonitoringUnavailable` | 22:13:09 | 22:18:09 |
| `SeaweedFSS3ReadFailures` | 22:14:17 | 22:19:17 |
| `SeaweedFSS3ReadProbeFailed` | 22:17:08 | 22:22:08 |

The collector-to-Loki test retained exactly three synthetic failure lines.
The isolated probe recorded repeated `status_or_length` failures, then returned
to verified reads after its fake server's complete body was restored. Actual
production object data was not corrupted for these tests.

A separate temporary job using Harbor's existing bucket-scoped identity
verified a nonzero smoke payload by write/read/compare/delete and confirmed its
absence afterward. It also verified the immutable Loki image manifest and
streamed a fresh 47,137,575-byte Harbor backing blob, matching SHA-256
`a7a5340d91257624b40159030b165b8f5cd3818c388cd329e507db5bc4cc2018`.
A historical Loki read at 20:01 UTC returned 18 canary records. This is targeted
read validation, not proof of completeness for every historical log or image.

The bootstrap, smoke, log, negative-control, and observer jobs and their pods
were removed. Both temporary PodMonitors were removed, including their scrape
targets. Local forwarding was stopped. The persistent fixture bucket and object
are intentional production monitoring resources and remain provisioner-owned.

Final checks found all 10 Seaweed pods ready, all 18 Longhorn volumes healthy,
zero read-only volume gauges, two successful current gateway probes, and four
healthy S3 scrape targets (native metrics plus probe metrics). Loki, all three
collectors, and all three log canaries were ready. There were no active storage
or log-loss alerts; only the known fan alert and Watchdog remained.

`seaweedfs-config`, Loki, ntfy, and kube-prometheus-stack were all Flux Ready at
runtime revision `1bf42c06`. The applied probe code matched the committed code
byte-for-byte. Local detailed evidence lives under ignored
`.private/s3-read-probes/`; the runbook contains rerunnable local commands.

During verification, separate node maintenance cordoned `k8s-3` and relocated
workloads, including an S3 gateway and monitoring components. Longhorn replicas
temporarily stopped or rebuilt. The webhook outage during that maintenance
left kube-prometheus-stack and ntfy Kustomizations reporting a failed dry run,
with storage and Loki blocked on their dependency. Once the webhook was ready,
ordered reconciliation retried the already-correct desired state. No chart
upgrade or webhook configuration change was needed. The storage replicas and
Flux dependencies recovered before final acceptance.

Test Behavior, Not Implementation selected full-body verification and actual
HTTP failure fixtures. Prove It Works required real gateway reads and exposed
the CPU-limited startup false positive before acceptance.
