# Known-bad intake patterns

Converged warnings from r/selfhosted, r/homelab, home-operations, cluster-template, awesome-selfhosted, and the general self-hosted community. These are patterns experienced homelabbers regret — not ideological restrictions, lived ones.

**How matches are handled by intent**:

- **Concrete-need intake** — any match is an auto-reject. These are patterns people *tried as production* and regretted.
- **Honest learning intake** — most patterns have a "learning carve-out" below. A homelab learning cluster is explicitly the right place to try things that "don't scale." If the user has declared learning intent with a timebox and exit plan, the match is not a veto.
- **Completionism-as-need** — auto-reject, same as concrete need.

The two patterns **without** a learning carve-out are #4 (duplicates at the Tier-0 layer) and #6 (running next to an existing layer). Duplicating CNI / cert-manager / ESO / envoy-gateway / external-dns / cloudflared is a cluster rebuild, not an intake — handle via the `add-or-replace-node` path or a separate tier-0 decision.

## 1. Self-hosted primary email server

**Pattern**: Running your own outbound SMTP as the primary email for a domain you actually use.

**Why it fails**: Deliverability is a full-time job. DKIM, DMARC, SPF, reverse DNS, IP reputation, blocklist monitoring, spam filter training, and recurring outages when a big provider (Gmail, Outlook, Yahoo) tightens rules. The mox, Mail-in-a-Box, and Mailcow maintainers themselves publicly warn against it for non-specialists.

**Acceptable variants**: Receiving-only MX for a parked domain; internal-only mail between containers; a secondary SMTP relay behind a commercial sender like Resend or Postmark.

**Learning carve-out**: Running a test SMTP server (mox, Postfix, exim4) against a *parked* domain you never send from, purely to understand the SMTP / DKIM / DMARC stack, is legitimate learning intake. Timebox it, don't point any real mail at it, and delete the namespace at the review date.

## 2. HA Postgres on 3 consumer nodes

**Pattern**: CloudNativePG, Patroni, Stolon, or Zalando operator running 3-replica HA on the same 3 nodes that run everything else, as a *production* database you depend on.

**Why it fails as concrete need**: You don't actually have HA — you have a distributed footgun where one bad PVC or one network partition wedges the whole thing, and recovery requires real Postgres + Kubernetes + distributed-systems expertise at 2am. Anton's removal commits include CNPG itself; it was added and removed.

**Acceptable variant for concrete need**: Single-instance CNPG (`replicas: 1`) with scheduled `pg_dump` to object storage and a *tested* restore runbook. Single-instance is honest; HA on 3 consumer nodes is theater *if you're depending on it*.

**Learning carve-out**: HA Postgres on 3 nodes is actually *great* as a learning experiment — it's one of the best ways to see distributed-systems failure modes up close on hardware you own. Declare learning intent, set a 30–60 day timebox, use throwaway data, and simulate failures on purpose (kill a pod, partition the network, fill a disk). "I want to learn why CNPG failover is harder than the docs make it look" is a completely legitimate learning intake. Just don't point anything you care about at it.

## 3. Full observability stack before you have alerts to write

**Pattern**: Install kube-prometheus-stack + Loki + Grafana + Tempo + Alertmanager + Grafana Alloy all at once as a *production monitoring story*, before the cluster has any workloads you actually need to observe.

**Why it fails as concrete need**: 4–8 GB RAM and noticeable CPU on a 3-node cluster, watching a handful of stateless apps that never page. Anton's removal commits include the full LGTM stack (`1753eec8`) — it was added and removed under exactly this framing.

**Acceptable variant for concrete need**: Start with `metrics-server` (already installed) + a single blackbox-exporter probe + one uptime alert to a notification channel you actually read. Add logs when you have a real question only logs can answer. Add traces never, or only when you have a real latency mystery.

**Learning carve-out**: Installing the LGTM stack explicitly to learn Prometheus queries, build Grafana dashboards, write your first real alerting rule, or understand how Loki shards logs is legitimate learning intake. The failure mode of the original anton removal was that it was installed as "production monitoring" without the workloads to justify it — not that you should never run it. Declare learning intent, set a timebox, build a dashboard you actually want to build, delete the namespace at the review date. Every homelabber should run kube-prometheus-stack at least once; just don't pretend you're doing it for reliability.

## 4. App requiring its own operator AND its own CRDs AND its own database

**Pattern**: A single candidate that brings a CRD-defining operator (one upgrade vector), its own bespoke CRDs you'll never touch directly (another upgrade vector), and a backing database it wants you to provision separately (a third intake hidden in the first).

**Why it fails**: Triple maintenance surface. Each vector upgrades on its own schedule, versions drift against each other, and the operator-CRD-DB triangle is the #1 source of stuck Flux HelmReleases in self-hosted K8s.

**Acceptable variant**: If the app is genuinely valuable, evaluate the bundle as three separate intakes. Usually at least one of the three fails under concrete-need framing.

**Learning carve-out**: Fine as a learning intake *if* the user understands they're taking on three learning projects at once and explicitly wants that. "I want to learn this operator and its CRDs and also how CNPG works, all at once" is honest and valid — just note that three-at-once experiments are harder to keep contained and more likely to bleed past the timebox. Consider running the backing DB separately first, getting comfortable with it, then adding the app.

## 5. HA secrets manager on 3 nodes

**Pattern**: HashiCorp Vault in HA mode, or any "enterprise" secrets manager that needs multi-replica + persistent storage + unseal automation, as a *production* secrets store that anton depends on.

**Why it fails as concrete need**: Vault HA on 3 nodes is a known distributed-systems footgun; unseal workflows at 2am are the stuff of homelab nightmares; seal/unseal + auto-unseal + storage backend + audit log rotation add up to a real operational burden. You'd also have to migrate ESO off 1Password to actually use it as the store, which is a separate project.

**Acceptable variant for concrete need**: ESO + 1Password Connect (anton's current setup). Bitwarden Secrets Manager or Infisical for the same pattern. Vault *only* if you already operate it professionally elsewhere and are reusing muscle memory.

**Learning carve-out**: Running Vault (dev mode or HA) in its own namespace, populated with fake secrets you don't care about, purely to learn its auth methods, policies, transit engine, or PKI engine is legitimate learning intake. Do not migrate the real secrets to it. Do not point ESO at it. When the timebox expires, delete the namespace and go back to 1Password.

## 6. Running next to a duplicate of an existing Tier-0 component

**Pattern**: Install a second ingress controller, second CNI, second cert issuer, second secret store, "just to try it" or because the new app's default install assumes ingress-nginx and anton uses envoy-gateway.

**Why it fails**: Two of anything at the infrastructure layer doubles the maintenance surface without delivering double the value. Routing becomes confusing, cert issuance races, and the question "which one owns this resource?" starts appearing in incident postmortems. The home-operations community calls this one explicitly: **one way to do each thing**.

**Acceptable variant**: Reconfigure the new app's chart to use the existing layer (almost always possible for ingress via Gateway API and for secrets via ESO). If the chart hard-requires ingress-nginx specifically, that's a Gate 4 (integration fit) failure — reject.

**No learning carve-out**: Replacing or duplicating a Tier-0 component (Cilium, cert-manager, ESO, envoy-gateway, external-dns, cloudflared) is not an intake even under learning intent — it's a Tier-0 swap. Handle as a deliberate migration in its own decision, with a proper rollback plan, not as a side-by-side experiment. Running two CNIs "to learn" is how clusters get wedged at 3am.

## 7. Kubernetes for a workload that doesn't need it

**Pattern**: Deploy a single-container app to anton because "everything runs on the cluster," when the app has no scale, HA, or integration requirements that justify the Kubernetes overhead.

**Why it fails as concrete need**: You take on 3-file Flux pattern cost, HelmRelease upgrade cost, ingress routing, cert provisioning, ESO wiring, and Renovate PR traffic to run something a `docker-compose.yaml` on one node would handle. The maintenance asymmetry is real.

**Acceptable variant**: If you already have the cluster and the incremental cost is genuinely tiny, fine — but this becomes a lever for completionism intake. Prefer to run it on a separate machine, or even a Raspberry Pi, if the workload doesn't benefit from K8s.

**Learning carve-out**: Running an app on anton specifically to practice the 3-file Flux pattern, ExternalSecret wiring, HTTPRoute setup, or Renovate PR handling *is* the learning. That's one of anton's primary purposes. A simple app as a learning intake vehicle is fine — just make sure you're honest that the learning is about Kubernetes, not about the app itself.

## 8. Speculative multi-tenancy / RBAC / auth infrastructure

**Pattern**: Install OIDC proxy, identity provider (Keycloak/authentik/Zitadel), RBAC admission webhook, or service mesh "because a real cluster needs it" when there is one human user (you).

**Why it fails as concrete need**: Multi-tenancy infrastructure is all cost and no benefit when there's one tenant. authentik + LLDAP + a reverse proxy per app is often several hundred MB of RAM watching zero unauthorized requests.

**Acceptable variant**: Header-auth via Cloudflare Access on public routes (zero cluster cost, handled at the tunnel). Basic auth via an HTTPRoute filter for internal stuff. Real identity infra *only* when multiple humans actually need it — most homelabs never reach that threshold.

**Learning carve-out**: Running authentik, Keycloak, or Zitadel to learn OIDC flows, SAML federation, or modern identity concepts is great. Learning how to wire an OIDC proxy in front of an app is a genuine homelab skill. Timebox it, don't migrate real auth onto it, and delete the namespace when the learning is done.

## 9. Backup tools installed without a tested restore

**Pattern**: Install Velero / Kopia / restic / Longhorn backups, point them at S3/B2, and declare the backup problem solved without ever having restored from one.

**Why it fails**: Untested backups are folklore. You don't know they work. You don't know the runbook. You don't know the restore latency. And you built up a false sense of security that made you comfortable adopting *more* stateful workloads that now also have untested backups.

**Acceptable variant**: Install the tool, run a full backup, restore it into a throwaway namespace, document the exact commands, and only *then* count it as solving the problem. This is Gate 6 made tangible. (Learning intake's equivalent is the throwaway-data acknowledgement.)

**Learning carve-out**: Installing a backup tool purely to learn how it works, without actually depending on it, is fine. Just be honest about it — don't let "I installed Velero to learn" morph into "Velero is protecting my data" without going through the tested-restore exercise first.

## 10. Components added for "completeness" rather than need or learning

**Pattern**: "A real Kubernetes cluster has monitoring / tracing / chaos engineering / policy engine / service mesh / GitOps-for-GitOps / GitOps-with-PR-previews, and mine doesn't, so I should add them" — stated as concrete need, with no real failure mode behind it and no declared learning intent.

**Why it fails**: Completionism-as-need is the single highest-value thing this rubric is designed to block. Anton's LGTM-stack removal commit (`1753eec8`) is the archetype: the stack was installed because "a real cluster needs observability," not because there was a workload that needed observing. The rubric's job is to catch this *specific* rationalization — the one where "I feel like my stack is incomplete" gets dressed up as "I need this."

**Acceptable variant**: None for completionism-as-need. But there are two honest reframings:

1. **Reframe as concrete need** — if you can finish "I cannot ___" with a specific failure mode you actually hit, the candidate isn't completionism anymore, it's concrete need. Evaluate it under the production rubric.
2. **Reframe as learning intake** — if you can finish "I want to learn ___" with a specific thing you want to understand, and give a timebox and exit plan, the candidate isn't completionism anymore, it's learning intake. Evaluate it under the contained-learning variant.

The rubric's entire purpose here is to force one of these two reframings. The third path — "my stack feels naked without it, therefore I need it" — is the one that produced the removal commit. It is the thing this gate rejects.

**How to distinguish completionism from honest learning**: completionism hides behind need-language ("I need X"). Honest learning owns the intent ("I want to try X"). If the user is willing to say "I want to learn this, I know it may not last, here's my timebox" — that's learning, accept it. If they insist it's need-driven but can't produce the present-day failure — that's completionism, reject it. The ask-once protocol in Gate 7 handles the boundary.

## How to use this file

Read it before writing the rubric for any candidate. If a match fires:

- **Under concrete-need intent** → skip straight to the **Reject** outcome in the ADR template and cite the pattern number. Do not soft-score past a known-bad match; the whole reason these are listed is that "yes but this time is different" is how the regret commits got authored.
- **Under honest learning intent** → read the pattern's learning carve-out (if present). If the learning variant is honest (timebox, exit plan, throwaway data), let it pass. Patterns #4 and #6 have no learning carve-out — those are Tier-0 or triple-threat risks that remain rejectable under every intent.
- **Under completionism-as-need** → reject. The point of the rubric is to force the user to reframe (as concrete need if there's a real reason, as learning intake if the reason is curiosity) rather than let completionism-language through.
