# Troubleshoot — failure modes and recommended next steps

When the skill stops on an error, format the report as:

```
❌ <app> deploy stopped at: <stage>
   reason:       <one-line message from the offending object>
   recommend:    <next skill or command>
   diagnostic:   <one targeted command the user can run>
```

Then stop. Don't retry, don't auto-recover. The skill's job is to surface where it stuck and hand off cleanly.

## Failure → recommendation table

| Stage | Symptom | Likely cause | Recommend | Diagnostic |
|---|---|---|---|---|
| `ImageRepository` Ready=False | `unauthorized` on registry | Private registry without `secretRef`, or expired creds | Check `secretRef` exists + has `dockerconfigjson` Secret; for Harbor, `/rotate-credential` if robot revoked | `flux get image repository <app> -n <ns>` |
| `ImageRepository` Ready=False | `connection refused` / DNS | Cluster can't reach registry | Network triage; for Harbor, check 192.168.1.106 reachable from pods | `kubectl -n flux-system run -it --rm dnsutils --image=infoblox/dnstools --restart=Never -- dig registry.host` |
| `ImagePolicy` Ready=False | `no tag matches` / `no images` | Regex doesn't match published tags | Check actual tags in registry; fix `filterTags.pattern` | `crane ls <registry>/<image>` (or `/v2/.../tags/list`) |
| `ImagePolicy` Ready=False | `latest image cannot be resolved` | ImageRepository hasn't scanned yet | `flux reconcile image repository <app> -n <ns>` | `flux get image repository <app> -n <ns>` |
| `ImageUpdateAutomation` Ready=False | git push rejected | Deploy key revoked, branch protected, or rate-limited | `/rotate-credential` if revoked; check anton repo branch protection rules | `kubectl -n flux-system logs deploy/image-automation-controller --tail=50` |
| `ImageUpdateAutomation` Ready=False | `no such file` / `path not found` | `update.path` points at a directory the policy marker isn't in | Fix `update.path`; ensure `# {"$imagepolicy": ...}` marker is in a YAML under that path | `kubectl describe imageupdateautomation <app> -n <ns>` |
| `Kustomization` Ready=False | `dry-run failed: no matches for kind` | apiVersion typo (e.g. v1beta1 vs v1beta2) or missing CRD | Fix apiVersion in manifest; ensure image controllers + CRDs are installed | `kubectl get crd | grep image.toolkit` |
| `Kustomization` Ready=False | `Server rendered manifests differ` | Drift; someone edited resources by hand | Revert manual edits; let Flux own the state | `flux diff kustomization <app> -n <ns>` |
| Rollout timeout | Pod ImagePullBackOff | Image not pullable (private GHCR, wrong tag, network) | Check GHCR public flip; `kubectl describe pod` for exact error | `kubectl describe pod -n <ns> -l app.kubernetes.io/name=<app>` |
| Rollout timeout | Pod CrashLoopBackOff | App-level error (port mismatch, config missing, panic on startup) | `kubectl logs --previous`; review Dockerfile EXPOSE vs Service targetPort | `kubectl logs -n <ns> -l app.kubernetes.io/name=<app> --tail=100 --previous` |
| Rollout timeout | Pod Pending | No node has resources / scheduling rule conflict | `kubectl describe pod` for the scheduling reason | `kubectl get events -n <ns> --sort-by=.lastTimestamp \| tail -20` |
| HTTP non-200 | 502/504 | Pod up but Service / HTTPRoute / Gateway misrouted | Trace through gateway; check `envoyproxy` logs | `kubectl logs -n network -l gateway.envoyproxy.io/owning-gateway-name=envoy-external --tail=50` |
| HTTP non-200 | 525/526 | TLS handshake / cert issue at Cloudflare edge | Check cert ready in `network` ns; `cert-manager` events | `kubectl get certificate -n network` |
| HTTP non-200 | DNS resolves to wrong IP | external-dns published the record but to the wrong target, or a foreign CNAME exists | Check `kubectl get dnsendpoint -A` for the record; check Cloudflare zone for orphan CNAMEs (per ADR 0023) | `dig +short <host> @1.1.1.1` and compare to `external.<domain>` |
| HTTP `ERR_NAME_NOT_RESOLVED` from operator's browser | Local DNS cache | macOS / Chrome cached NXDOMAIN before record existed | `sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder`; clear `chrome://net-internals/#dns` | (operator-side, not cluster) |
| `flux-operator` 0/1 CrashLoopBackOff | Liveness probe `/readyz` timeout | v0.46.0 probe-timeout bug (plan 0012 log) | Surface the issue; recommend separate plan; downstream may still work in green windows | `kubectl -n flux-system describe pod -l app.kubernetes.io/name=flux-operator` |

## When to escalate

After three rounds of any single failure mode (skill stops, user fixes, retries, fails the same way), recommend opening a new plan with `/planner new "<failure summary>"` rather than continuing to iterate inline. Persistent failures usually indicate a deeper issue than the skill's scope can address.

## When NOT to use this skill

If multiple Flux objects across the cluster are unhealthy (not just the target app), this skill is the wrong tool. Run `/anton-cluster-health` first; fix the cluster-wide issue; then come back to this skill.

If `flux-operator` itself is in CrashLoopBackOff, downstream reconciles may work in narrow green windows but are unreliable. Fix flux-operator first.
