# Redeploy mode — kick the image-automation chain

Triggered when `flux get image repository <app-name> -A` returns a row. The app already lives in the cluster; the goal is to short-circuit the default 5m polling cadence so a fresh build deploys NOW.

## Workflow

### Step 0 — Resolve namespace and URL

```sh
flux get image repository <app> -A
# → row gives namespace
NAMESPACE=$(flux get image repository <app> -A -o json | jq -r '.[].namespace')

# Discover hostname from HTTPRoute (skip if --no-verify or no HTTPRoute)
HOST=$(kubectl get httproute -n "$NAMESPACE" "$app" -o jsonpath='{.spec.hostnames[0]}' 2>/dev/null || true)
```

If the HTTPRoute lookup fails or the resource doesn't exist, log "no HTTPRoute found for $app — HTTP verify will be skipped" and continue. Don't abort.

### Step 1 — Capture the current state

```sh
T0=$(date +%s)

# Current resolved tag (used to detect "did anything change")
TAG_BEFORE=$(flux get image policy "$app" -n "$NAMESPACE" -o json | jq -r '.[].latestImage' | sed 's|.*:||')
```

### Step 2 — Force the chain (skipped under --no-force)

In strict order, with brief output between each:

```sh
flux reconcile image repository "$app" -n "$NAMESPACE"
flux reconcile image update     "$app" -n "$NAMESPACE"
```

After image update completes, check whether the policy resolved to a new tag:

```sh
TAG_AFTER=$(flux get image policy "$app" -n "$NAMESPACE" -o json | jq -r '.[].latestImage' | sed 's|.*:||')
```

- If `TAG_BEFORE == TAG_AFTER` → image-automation didn't write a new commit (no new build in the registry). Skip the source/kustomization reconcile; tell the user "no new image; nothing to roll." Exit cleanly with status block (timing: just the reconcile cost).
- If `TAG_BEFORE != TAG_AFTER` → continue with source + kustomization:

```sh
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization "$app" -n "$NAMESPACE"
```

### Step 3 — Watch the rollout (skipped under --no-watch)

```sh
kubectl rollout status deployment/"$app" -n "$NAMESPACE" --timeout=2m
```

If the tag was unchanged in Step 2, this returns immediately; that's fine.

### Step 4 — Verify HTTP 200 (skipped under --no-verify or no HTTPRoute)

```sh
IP=$(dig +short "$HOST" @1.1.1.1 | head -1)
HTTP_CODE=$(curl -sI --max-time 15 --resolve "$HOST:443:$IP" -o /dev/null -w '%{http_code}' "https://$HOST/")
```

`--resolve` against 1.1.1.1 bypasses local DNS cache (the macOS NXDOMAIN-cache issue documented in plan 0012's log).

If `HTTP_CODE != 200` → report and stop. Don't retry.

### Step 5 — Report

```
✅ <app> deployed
   namespace:    <ns>
   image tag:    <new>  (was <old>)   ← or "unchanged — no new build"
   bot commit:   chore(<app>): <tag>  ← or "no commit needed"
   pod:          <pod-name> Running
   url:          https://<host>/  →  200
   total elapsed: <N>s  (T0 → 200)
```

Pod name from `kubectl get pod -n "$NAMESPACE" -l app.kubernetes.io/name=<app> -o jsonpath='{.items[0].metadata.name}'`.

## --no-force mode (status only)

Skip Steps 2 and 3. Walk the same checks but read-only:

```sh
flux get image repository "$app" -n "$NAMESPACE"
flux get image policy     "$app" -n "$NAMESPACE"
flux get image update     "$app" -n "$NAMESPACE"
flux get kustomization    "$app" -n "$NAMESPACE"
kubectl get deploy        "$app" -n "$NAMESPACE"
# HTTP check still runs unless --no-verify
```

Report format swaps to `📋 <app> status` (no timing block).

## Stop conditions

Bail with the status format from `references/troubleshoot.md` if any of:

- ImageRepository `Ready=False`
- ImagePolicy `Ready=False`
- ImageUpdateAutomation `Ready=False`
- GitRepository `Ready=False`
- Kustomization `Ready=False`
- Rollout times out at 2m
- HTTP code is not 200

In every case: report which stage, the message from `flux get` / kubectl events, and recommend `/debug-flux-reconciliation`.

## What this mode never does

- Edit manifests (no tag rewrites, no resource adds)
- `kubectl rollout restart` (would fight GitOps)
- `kubectl set image` (same)
- Loop / retry on failure
- Run cluster-wide reconciles (other apps' Kustomizations etc.)
