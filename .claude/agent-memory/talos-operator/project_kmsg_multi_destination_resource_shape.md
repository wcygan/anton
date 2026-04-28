---
name: KmsgLogConfig multi-destination collapses to single resource ID
description: Multiple KmsgLogConfig docs in machine config render as one runtime resource (id=kmsg-log) with N destinations, not N separate resources
type: project
---

When `talos/patches/global/machine-kmsg.yaml` defines multiple `KmsgLogConfig` documents (e.g. `vector-sink` TCP + `vector-sink-udp` UDP), the Talos runtime collapses them into a SINGLE COSI resource:

```
$ talosctl ... get kmsglogconfigs
NODE    NAMESPACE   TYPE            ID         VERSION
k8s-2   runtime     KmsgLogConfig   kmsg-log   2
```

The `spec.destinations` array contains both URLs. The `name:` field on each machine-config doc is NOT preserved as a resource ID — it is metadata the controller squashes.

**Why:** This is how the `KmsgLogConfigController` in Talos 1.12.6 reconciles. The "name" in machine config is informational; the runtime keeps a single `kmsg-log` resource that aggregates destinations.

**How to apply:** When verifying a multi-destination kmsg config rollout, do NOT expect `get kmsglogconfigs` to return one row per destination. Instead inspect `-o yaml` and check `spec.destinations` length and contents. Version increments by 1 per machine-config apply that touches the resource. Confirmed on all 3 nodes 2026-04-28 with `vector-sink` (tcp://192.168.1.105:6001) + `vector-sink-udp` (udp://192.168.1.105:6002) — single ID `kmsg-log` version 2.
