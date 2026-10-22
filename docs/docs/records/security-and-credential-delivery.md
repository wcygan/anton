---
title: Security and credential delivery incidents
record_type: historical-incident
period: 2026-07 to 2026-09
---

# Security and credential delivery incidents

## Secret-provider quota exhausted

In August 2026, frequent polling across many secret fields used up the external provider's shared daily request allowance, and retries made it run out faster. Kubernetes Secrets that already existed kept their last values, but new or changed values could not be delivered.

The fix reduced routine reads and made delivery behave more safely under failure. Counters local to one token did not show historical usage. No secret values belong in incident records.

**Diagnose delivery failures across four layers:** provider quota, ESO reconciliation, the materialized Secret's metadata, and the consuming workload. Prefer keeping last-known-good values working. Report the age and delivery condition without reading Secret data.

## Security review findings

Reviews found gaps in policy validation, binding identity, YAML document discovery, path containment, effective-target checks, and public endpoint handling. Fixes were recorded with regression tests.

Source triage and image coverage are not a blanket security clearance or a runtime audit. Raw scanner output and detailed inventories stay private. Check live state before claiming a past fix still holds.
