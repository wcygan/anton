---
title: Anton
slug: /
sidebar_position: 1
---

import ClusterOverview from '@site/src/components/ClusterOverview';

# Anton

Anton is a three-node Kubernetes homelab running Talos Linux. It hosts public applications, private operator services, and time-boxed learning experiments. Flux applies what is committed to Git; these pages explain what the platform provides and how to operate it safely.

<ClusterOverview />

Public requests reach applications through Cloudflare Tunnel. The cluster opens the tunnel outbound to Cloudflare, and responses return over that same connection. Inside the cluster, `cloudflared` hands each request to Envoy Gateway, which routes it to an application.

## Start here

| I want to… | Read |
| --- | --- |
| See what the platform provides | [Capabilities](overview/capabilities.md) |
| Understand how the pieces fit | [Architecture](overview/architecture.md) |
| Check health or find a failure | [Routine operations](guides/operations.md) |
| Connect from outside the LAN | [Remote access](guides/remote-access.md) |
| Store data or debug a volume | [Storage](guides/storage.md) |
| Know why something was chosen | [Decisions](decisions/index.md) |
| Learn from a past incident | [Records](records/index.md) |

## How to read these pages

Each collection answers a different question, and none of them is a live health check:

- **Guides** describe current procedures. They name the checks to run; they do not report results.
- **Decisions** explain why a choice was made. Follow supersession links before treating an old decision as current.
- **Records** summarize what was established during a dated window, including what stayed uncertain.

A committed manifest shows intent, and an old record shows history. Confirm present behavior against the live cluster.

This site is public. Credentials, private hostnames, detailed inventories, raw evidence, and working plans stay outside it. Shared agent procedures live in the repository's `.agents/skills/`. [Documentation and maintenance](reference/documentation.md) explains what belongs where.
