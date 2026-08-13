# Application Credential Exposure

Use this branch when an application credential reaches output, retained
evidence, a command argument, an unprotected file, or another unauthorized sink.

## Immediate state

1. Stop new use of the exposed credential.
2. Stop acceptance work that depends on it.
3. Record the credential owner, version, consumers, and exposure boundary.
4. Keep the credential value out of the record.
5. Mark prior acceptance evidence as belonging to the old credential epoch.

Exposure response does not authorize rotation. Present the exact external,
repository, Flux, and workload actions before requesting approval.

## Rotation contract

State these items before any mutation:

- Credential owner and nonsecret identifier.
- Affected ExternalSecrets, Secrets, and workloads.
- Replacement creation path.
- Old and new overlap period.
- Cache or restart behavior.
- Verification timeout and stop condition.
- Revocation point.
- Rollback operation.
- New credential epoch name.

Keep one credential rotation active at a time.

## Replacement sequence

1. Create the replacement through the authoritative secret owner.
2. Use protected input or an interactive secret editor.
3. Verify only version metadata and field names.
4. Update repository mappings only when the consumer shape changes.
5. Verify ExternalSecret delivery without reading Secret data.
6. Verify every consumer reaches stable readiness.
7. Start a new acceptance evidence epoch.
8. Re-run every acceptance check that used the exposed credential.
9. Revoke the old credential after end-to-end verification.
10. Remove run-owned files, variables, sessions, and port-forwards.

For cached credentials, restart only the exact consumer after approval. Record
the predicted transition and rollback before the restart.

## Evidence epoch

Retain the owner, version, epoch, completion time, consumer revision, and first
accepted operation. Adapt the receipt fields to the consumer contract.

For an Airflow shadow gate, retain this exact nonsecret receipt shape:

```json
{
  "schema_version": 1,
  "status": "accepted",
  "candidate_revision": "<git-revision>",
  "credential_version": 2,
  "credential_owner": "<nonsecret-owner>",
  "credential_epoch": "<nonsecret-epoch>",
  "rotation_completed_at": "<ISO-8601-time>",
  "rotation_completed_before_run_id": "<first-accepted-run-id>",
  "source": {
    "observed_at": "<ISO-8601-time>",
    "command": "<metadata-only-command>",
    "result": {
      "version": 2,
      "updated_at": "<ISO-8601-time>"
    }
  }
}
```

Every accepted run must name the same epoch. A credential change starts a new
evidence directory and resets any consecutive-run count.

The source must retain metadata-only output from the credential owner. The
owner update time must precede the first accepted run.

The receipt must contain no token, password, access key, cookie, private key,
authorization header, or encoded secret.

## Verification

Verify these layers in order:

1. Secret owner shows the new version.
2. ExternalSecret reports `Ready=True`.
3. The target Secret has the expected keys and owner metadata.
4. Each consumer reports stable readiness without authentication errors.
5. The user-visible operation succeeds.
6. New acceptance evidence identifies the new epoch.
7. The old credential is revoked.
8. Temporary authentication material is absent.

Inspect Secret metadata only. Use bounded logs and redact unexpected values.

## Rollback

Keep the old credential valid until replacement verification passes. If the
new credential fails, restore the previous owner mapping and consumer state.

Revoke the replacement only after the prior credential path is healthy. Record
the failed epoch as rejected and retain its nonsecret diagnostics.

## Completion report

```text
Status: rotated | rolled back | blocked
Owner: <external or repository owner>
Consumers: <ExternalSecrets and workloads>
Epoch: <nonsecret identifier>
Verification: <metadata, readiness, user-visible result>
Revocation: <old credential status>
Cleanup: <temporary material and sessions>
Residual risk: <cached or unverified consumer>
```
