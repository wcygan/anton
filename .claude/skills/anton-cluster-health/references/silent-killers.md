# Silent killers

Four Anton-specific failure modes that pass `flux get ks/hr -A` as healthy but still break things. When a user says "everything looks ok but X is broken", start here.

Each section has the same shape: **Symptom → Probe → Fix path**.

---

## 1. SOPS decryption error

**Symptom**: a Kustomization is `Ready=False` with a `decryption error` message. All downstream apps in that Kustomization freeze until the key issue is resolved.

**Probe**:

```sh
flux get ks -A --status-selector ready=false
# For any suspicious row:
flux -n <ns> describe ks <name> | grep -A3 -i 'decrypt'
```

**Verify the Flux-side key matches the repo recipient**:

```sh
kubectl -n flux-system get secret sops-age -o jsonpath='{.data.age\.agekey}' | base64 -d | head -1
# The public key that comes out must match an entry in .sops.yaml recipients
```

**Fix path**: `rotate-credential` (age key) or verify `.sops.yaml` matches the cluster Secret. Full detail: [layer-4-flux](layer-4-flux.md).

---

## 2. ClusterSecretStore `onepassword-connect` NotReady

**Symptom**: No `ExternalSecret` anywhere in the cluster is syncing. New apps that need a 1Password-backed Secret come up without it. ESO controller logs show persistent errors contacting 1Password.

**Probe**:

```sh
kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
# If not True:
kubectl describe clustersecretstore onepassword-connect
kubectl -n external-secrets logs -l app.kubernetes.io/name=external-secrets --tail=50
```

**Check which ExternalSecrets are frozen**:

```sh
kubectl get externalsecret -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status' | grep -v True
```

**Fix path**: `rotate-credential` (1Password service-account token) or check outbound network reachability to the 1Password API. Full detail: [layer-5-platform](layer-5-platform.md).

---

## 3. Envoy Gateway `Programmed=False`

**Symptom**: HTTPRoutes attach cleanly, status shows `Accepted=True`, DNS resolves to the right LB IP — but no traffic flows. `curl` hangs or returns connection reset. envoy is up but has no listener bound.

**Probe**:

```sh
kubectl get gateway -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,ACCEPTED:.status.conditions[?(@.type=="Accepted")].status,PROGRAMMED:.status.conditions[?(@.type=="Programmed")].status'
```

Any `Programmed=False` (or missing) row is a silent outage.

```sh
kubectl describe gateway -n <ns> <name>
# Look for: listener TLS secret missing, port conflict, cert not Ready
kubectl -n envoy-gateway-system get pods
kubectl -n envoy-gateway-system logs -l app.kubernetes.io/name=gateway-helm --tail=50
```

**Fix path**: verify the referenced TLS Secret exists and has `tls.crt`/`tls.key`; verify no other Gateway claims the same listener port. If the controller pod is crash-looping, read its logs first. Full detail: [layer-5-platform](layer-5-platform.md).

---

## 4. Cloudflared tunnel not registered

**Symptom**: `cloudflared` pod is `Running` and `Ready=True`, but external traffic never reaches the cluster. Cloudflare dashboard shows the tunnel as degraded or disconnected. Commit `42822fc3` just fixed this class (QUIC→HTTP/2) — expect regressions when the upstream daemon is bumped.

**Probe**:

```sh
kubectl -n network get pods -l app.kubernetes.io/name=cloudflared
kubectl -n network logs -l app.kubernetes.io/name=cloudflared --tail=50 | \
  grep -Ei 'Registered tunnel connection|ERR|connection refused|QUIC|http2'
```

**Healthy**: recent `Registered tunnel connection` lines, no `ERR`, no `connection refused`.

**Failure patterns**:
- Only `ERR` lines and no registration → token expired → `rotate-credential`
- `QUIC` errors only → transport blocked on egress (UDP/7844); confirm HTTP/2 workaround still in the Helm values
- Pod restarting every few minutes → usually a Helm values regression after a chart bump

**Fix path**: `rotate-credential` for token; check/restore HTTP/2 transport in the cloudflared HelmRelease values. Full detail: [layer-5-platform](layer-5-platform.md).

---

## Why these are "silent"

All four failure modes share a pattern:
1. The *control-plane* resource (Kustomization / HelmRelease / Gateway / Deployment) reports healthy
2. A nested condition or a behavioral signal tells a different story
3. `flux get` and `kubectl get pods` both look green

That's why the main triage flow in `SKILL.md` has a Silent Killers section: if you only run `flux get ks/hr -A`, you will miss all four. Probe them explicitly, every time.
