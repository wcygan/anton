---
title: Decision records
---

# Decision records

An architecture decision record (ADR) captures one choice: the situation, the decision, the alternatives considered, and the consequences accepted. Research notes and rollout tasks belong elsewhere.

## Numbering and metadata

Each ADR has a four-digit ID and a descriptive slug, such as `0005-adopt-longhorn-for-block-storage`. Take the next number after the highest existing one, and never reuse a number.

Frontmatter carries `date`, `status`, `affects`, `intent`, `supersedes`, and `superseded-by`. Keep them accurate; tools and the [decision index](../decisions/index.md) read them. The shared `adr` skill owns the template and authoring workflow.

| Status | Meaning |
| --- | --- |
| Accepted | The decision is in force |
| Deferred | Postponed; this does not approve installing anything |
| Rejected | Considered and declined |
| Reverted | Adopted, then removed |
| Superseded-by NNNN | Replaced by the named later decision |

## Changing a decision

Once accepted, an ADR's body stays stable. To change course, write a new ADR and set the old one's status to `Superseded-by NNNN`.

Read the whole supersession chain before treating an old decision as current. Several older ADRs can remain Accepted after a later decision has ended the experiment they started, so check the latest relevant decision.

## Public editions

During the 2026 documentation migration, the original 40 decisions were condensed into public editions. Each keeps its original ID, date, status, meaning, and relationships, and each says it was condensed. The wording changed; the decisions did not.

New ADRs should be public-safe from the first draft. Describe the architecture without private endpoints, identities, credentials, hardware serials, or incident captures. Keep sensitive rationale in private operator records, and make the public decision understandable without it.

## Reconsidering a component

Having installed something before is not a reason to install it again. Declare a concrete need, contained learning, or both. Learning needs a review date, agreement that its data is disposable, and an exit plan. The shared intake procedure applies the full re-adoption rubric.
