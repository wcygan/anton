---
name: `wait: false` is the anton default; set `wait: true` only with justification
description: Flux Kustomization `spec.wait` is false across almost every anton app; deviate only when downstream apps genuinely depend on HR readiness, and add a comment explaining why
type: feedback
---

Every anton `ks.yaml` I've inspected sets `wait: false` or omits it (inheriting false). The `add-flux-app` template explicitly comments "`wait: false` (use `true` only for critical services)." Even Longhorn — a Tier-0 storage dependency — uses `wait: false`.

**Why:** `wait: true` blocks the Kustomization until every HelmRelease inside reports Ready, which can mask real failures behind long reconcile hangs and cascades stuck-state across dependent Kustomizations. Anton's `cluster-apps` Kustomization also runs with `wait: false`, so flipping individual child apps to `wait: true` is a local-only guarantee.

**How to apply:** default new `ks.yaml` files to `wait: false`. Set `wait: true` only when the brief explicitly asks AND downstream apps (ServiceMonitors, dashboard ConfigMaps, Probes, webhooks) would fail or reconcile incorrectly before the HelmRelease is Ready. When doing so, leave an inline comment naming the downstream consumer that justifies the block, so the next reader can evaluate whether the constraint still holds. Kube-prometheus-stack (plan 0002) is the first case where this was justified in-brief: other monitoring resources depend on prometheus-operator CRDs being Established.
