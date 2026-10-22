---
title: DNS ownership and monitoring capacity
record_type: historical-operations
period: 2026
---

# DNS ownership and monitoring capacity

Two failure patterns from older troubleshooting notes are still worth knowing. The original notes used illustrative output rather than dated incident records, so these describe mechanisms, not specific events.

## A healthy app behind stale public DNS

An application can be running, with an accepted route, and still be unreachable because its public DNS record points at a retired tunnel. External DNS respects ownership markers, so it may leave a record it does not own untouched.

**Check first:** the record's owner at the DNS provider and the tunnel it targets, before suspecting the application. A secondary domain also needs explicit DNS intent; an `HTTPRoute` alone does not create or claim the record. Provider changes need their own approval. This failure led to [one shared tunnel](../decisions/0023-shared-cloudflare-tunnel-only.md); see also [service exposure](../guides/secrets-and-exposure.md).

## Prometheus on a full volume

When Prometheus's persistent volume fills, its write-ahead log can fail to open. Prometheus then restarts repeatedly, dashboards go blank, and alerting degrades.

**Check first:** PVC capacity, retention settings, ingestion volume, and storage backend health, then choose an approved repair. Deleting the WAL or TSDB discards evidence and is not a diagnostic step. The original walkthrough targeted a retired Ceph storage class, so its exact commands no longer apply.
