# SeaweedFS availability during node maintenance

Preserve exact bytes from existing S3 objects and accept fresh writes while one
owning node is unavailable during planned maintenance. Retain source files,
PVCs, credentials, GitOps ownership and current observability.

The initial audit, isolated proof, new-allocation default and recovered migration
attempt are delivered. Existing-data migration and real node-hold acceptance
remain incomplete. Continue with
[issue 01](issues/01-complete-node-maintenance-availability.md), which contains
the current evidence, proposed increments and stop/rollback conditions.

The durable parent is
[plan 0027](https://github.com/wcygan/anton/blob/d162ef88439305f8c1c98502ad240235a496338e/context/plans/0027-improve-cluster-operational-outcomes.md).
Creating this backlog does not start another maintenance window.
