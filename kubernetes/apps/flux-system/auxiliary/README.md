# Auxiliary deployment connector

This enabled connector lets the existing Flux installation reconcile an additional
authenticated Git source. `ks.yaml` applies the credential, source and workload root;
`app/private-root.yaml` reconciles the additional source's `clusters/anton` path.

The source URL is supplied by `SECRET_AUXILIARY_GIT_URL` in the existing SOPS-encrypted
`kubernetes/components/sops/cluster-secrets.sops.yaml`. The key is configured as
ciphertext. An absent key defaults to an unreachable `.invalid` URL, which prevents
an unconfigured source from fetching. Keep the URL, application inventory and
credentials out of public documentation, issues and commits.

ESO reads `auxiliary-git/username` and `auxiliary-git/password` from vault `anton`.
The fine-grained GitHub token must have Contents read/write for only the additional
repository. It must not have access to this public repository.

The public cluster root and this connector's workload root receive the same child
defaults from `kubernetes/components/flux-child-defaults`. Edit that component once
to change SOPS, deletion or Helm behavior for both roots. Each public Kustomize entry
point includes it locally; the additional source needs no copy or remote import.

For a fresh setup, prepare the repository and credentials with both Kustomizations
suspended. Enable the connector, verify credential delivery and source readiness,
then enable the workload root. Those activation stages are already complete here.
Suspending either root does not suspend its existing children or image automation;
freeze the exact workload Kustomizations and automation when both must stop.

Public ownership ends at the connector. Private workload manifests, image setters,
app inventory, and operator runbooks belong to the private source. The URL becomes
plaintext in the applied GitRepository; public Git retains only a variable and ciphertext.

Validate with `mise exec -- task contracts:validate` and local Kustomize builds of
`kubernetes/flux/cluster` and this `app` directory. Operator procedures and recovery
evidence belong in the additional source. Publication and deployment require
operator authorization.
