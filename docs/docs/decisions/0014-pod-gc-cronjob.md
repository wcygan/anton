---
status: Accepted
date: 2026-04-17
deciders: ['@wcygan']
affects: compute
intent: concrete-need
supersedes: []
superseded-by: null
retrospective: false
edition: condensed-public
slug: /decisions/0014-pod-gc-cronjob
---

# 0014 — Clean failed pods with a Flux-managed CronJob

> Delete Failed pods on a schedule with a narrowly scoped, Flux-managed CronJob.

_Public edition condensed on 2026-10-21; original decision date and meaning retained._

## Context

Kubernetes PodGC deletes terminated pods only after the cluster-wide count passes its threshold. A few stale Failed pods therefore stayed visible on the cluster-health dashboard even when their replacements were healthy, which made the failure panel less trustworthy.

## Decision

Add a Flux-managed CronJob that periodically deletes pods in phase Failed. It runs under a dedicated service account with only the cluster permissions needed to list and delete pods. Keep the controller's existing threshold as a ceiling for large bursts. Stale pods may linger briefly between runs.

## Alternatives considered

- **Manual cleanup:** needs ongoing intervention.
- **Lower the PodGC threshold:** requires a Talos change and still does not guarantee zero stale pods.
- **A cleanup operator or descheduler:** adds unnecessary surface, or solves a different problem.
- **Filter the dashboard:** hides stale API objects instead of removing them.

## Consequences

The job holds cluster-wide pod deletion rights, but its field selector limits deletion to Failed pods. Keep that selector, and verify the schedule and dashboard after deployment. This decision does not authorize widening what the job deletes.
