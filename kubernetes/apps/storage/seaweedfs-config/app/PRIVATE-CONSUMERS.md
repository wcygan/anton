# Private S3 consumers

The shared ExternalSecret and bucket provisioner remain the only owners of S3
identity configuration and bucket lifecycle. Private deployment repositories must
not reconcile a second copy of either resource.

Before delivering this extension, create `seaweedfs-auxiliary` in 1Password vault
`anton` with concealed field `identities` containing `[]`. An absent field or
invalid bundle fails ESO reconciliation and preserves the previously delivered
Secret. Private consumer inventory and credentials belong in that field, never
in public manifests. Each entry has exactly these fields:

```json
[{"name":"private-fixture","bucket":"private-fixture","accessKey":"example","secretKey":"example"}]
```

The template retains existing identities and grants each additional identity only
Read, Write and List for its named ordinary bucket. It rejects malformed fields,
empty credentials, invalid names, duplicate identity names and access keys,
including collisions with existing identities. JSON encoding preserves credential
characters. Validation failures produce generic template errors without values.
The existing template's legacy credentials remain unchanged.

The same bundle emits `AUXILIARY_ORDINARY_BUCKETS` into the shared Secret. The
existing CronJob already reads that Secret with envFrom; the provisioner combines
this intent with ordinary platform buckets, retaining kind-collision refusal
before any creation. Removal of intent never deletes buckets or their data.

`mustFromJson` rejects malformed JSON. The template intentionally uses an invalid
constant JSON value to report rejected records because current ESO removes the
Sprig `fail` helper. Tests render the actual Go template using Helm's Sprig
implementation and synthetic values; they do not replace controller verification.
See https://external-secrets.io/latest/guides/templating/.

Before an approved live change, validate contracts, observe ESO delivery, and
compare identities without printing credentials. Qualify file reload against the
actual runtime before sending SIGHUP, one gateway at a time. Otherwise follow the
shared-service maintenance procedure. Verify existing consumers and new scoped
read/write/delete behavior. Do not assume Secret delivery implies process reload.
