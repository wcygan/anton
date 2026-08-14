# 07 — Produce the first orphan-file report

**What to build:** Produce a deletion-free report of old orphan candidates under the exact Flight Recorder table locations.

**Blocked by:** 06 — Schedule the recorder and retire the hourly fixture.

**Status:** ready-for-agent

- [ ] The report scans only exact Flight Recorder table locations.
- [ ] The report never scans the warehouse root, raw-object prefix, or unrelated table locations.
- [ ] Candidate files must be at least seven days old.
- [ ] Prefix mismatches stop the report with an error.
- [ ] Current snapshots, retained snapshots, branches, and tags remain protected.
- [ ] The report retains candidate counts, byte totals, scope, observation time, and the Spark Attempt identity.
- [ ] The first run deletes no object.
- [ ] The operator can review the exact scope before authorizing automatic cleanup.
- [ ] Focused tests and repository contracts pass.
