# Auxiliary deployment connector

This generic connector lets Flux reconcile an additional authenticated Git source.
It starts suspended. Its workload root also starts suspended.

The source URL is supplied by `SECRET_AUXILIARY_GIT_URL` in the existing SOPS-encrypted
`kubernetes/components/sops/cluster-secrets.sops.yaml`; that key is intentionally not
set by this scaffold. The substitution defaults to an unreachable `.invalid` URL
so local strict validation can pass before credentials are prepared. Do not place the URL, application inventory, or credentials
in public documentation, issues, or commits.

ESO reads `auxiliary-git/username` and `auxiliary-git/password` from vault `anton`.
The fine-grained GitHub token must have Contents read/write for only the additional
repository. It must not have access to this public repository.

Enable `ks.yaml` only after repository and credential setup. Verify source readiness,
then separately enable `app/private-root.yaml`. Child Kustomization defaults mirror
`kubernetes/flux/cluster/ks.yaml`; keep them aligned when platform defaults change.

Public ownership ends at the connector. Private workload manifests, image setters,
app inventory, and operator runbooks belong to the private source. The URL becomes
plaintext in the applied GitRepository; public Git retains only a variable and ciphertext.

Validate with `mise exec -- task contracts:validate` and local Kustomize builds.
Do not push or enable either gate without operator authorization.
