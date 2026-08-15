# 08 — Enable bounded weekly orphan cleanup

**What to build:** After operator approval, remove only accepted old orphan candidates through one weekly, Lease-protected maintenance path.

**Blocked by:** 07 — Produce the first orphan-file report.

**Status:** ready-for-agent

- [ ] The accepted dry-run scope and explicit operator approval are recorded before deletion is enabled.
- [ ] Weekly cleanup uses the authoritative writer Lease and exact Flight Recorder table locations.
- [ ] Only files older than seven days and absent from every protected reference are eligible.
- [ ] Any scope, prefix, reference, or accounting mismatch stops deletion.
- [ ] The run retains candidate counts, deleted counts, byte totals, and the Spark Attempt identity.
- [ ] Read-only Trino checks confirm that retained rows and snapshots remain queryable.
- [ ] Raw objects, unrelated Iceberg tables, and the warehouse root remain outside cleanup authority.
- [ ] Disabling the weekly schedule stops future deletion without changing retained data.
- [ ] Focused tests and repository contracts pass.
