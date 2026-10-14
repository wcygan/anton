---
sidebar_position: 0
---

# Routine operations

Use this guide for health checks, deployment, and diagnosis. Run commands from
the Anton repository root. Replace angle-bracket placeholders before running
examples.

## Start every session

```sh
mise exec -- task --list
mise exec -- kubectl config current-context
```

Mise selects the pinned tools, `./kubeconfig`, and
`./talos/clusterconfig/talosconfig`. The expected Kubernetes context is
`tailscale-operator.<tailnet-name>.ts.net`; `admin@anton` is the fallback.
Stop if the context is unexpected. If access or target resolution fails, use
[Talos health and target setup](talos-health.md) before proceeding.

Before editing, check `git status --short`, `git branch --show-current`, and
`git rev-parse --short HEAD`; preserve unrelated work. Before a cluster read,
identify the affected namespace/resource and time window.

## Check health

Read in order and stop at the first failing layer:

```sh
# Nodes, Talos services, and etcd through the complete remote target set
mise exec -- task talos:health

# Networking and DNS controller readiness
mise exec -- kubectl -n kube-system get daemonset cilium
mise exec -- kubectl -n kube-system get deployment coredns

# Flux source, application rendering, and Helm reconciliation
mise exec -- flux get sources git -A
mise exec -- flux get sources oci -A
mise exec -- flux get sources helm -A
mise exec -- flux get ks -A
mise exec -- flux get hr -A

# The service you actually need
mise exec -- kubectl -n <workload-namespace> get pods,services,httproutes
```

Healthy nodes and Ready controllers establish those layers only. Check the
affected workload's required dependencies, restart counts, and actual endpoint
before calling the service healthy. Check both public and private access when
both matter. Do not create a debug pod or port-forward as part of this initial
read-only check.

## Deploy a change

1. Find the owning app under `kubernetes/apps/<namespace>/<app>/`. Read its
   `ks.yaml` and `app/kustomization.yaml`, then the HelmRelease or raw manifests.
   Edit those sources directly; there is no template-render step.
2. Run `mise exec -- task contracts:validate`. Keep SOPS files encrypted and
   use the matching app/exposure/storage guidance for the change.
3. Review the diff. Commit, push, and merge only within the authorized Git
   workflow. A local branch does not deploy: Flux must receive the change on
   its configured source ref. Inspect that ref with:

   ```sh
   mise exec -- kubectl -n flux-system get gitrepository flux-system \
     -o jsonpath='{.spec.ref}{"\n"}{.status.artifact.revision}{"\n"}'
   ```

4. Let the webhook or polling trigger Flux, then verify the intended revision,
   reconciliation, workload rollout, and endpoint:

   ```sh
   mise exec -- flux get sources git -A
   mise exec -- flux get kustomization <app> -n <flux-namespace>
   mise exec -- flux get helmrelease <release> -n <release-namespace>
   mise exec -- kubectl -n <workload-namespace> rollout status \
     deployment/<deployment> --timeout=2m
   ```

   Use the actual workload kind/name; omit the HelmRelease check for raw apps.
   Check stable readiness, recent events/restarts, and the actual public URL or
   private service before declaring success.

Flux resource namespaces can differ from workload namespaces. For example,
`echo/ks.yaml` defines Kustomization `flux-system/echo` targeting `default`.
Resolve each identity from its manifest instead of inferring it from the folder.

For an owned app, check whether image automation is configured:

```sh
mise exec -- flux get image repository -A
mise exec -- flux get image policy -A
mise exec -- flux get image update -A
```

Only apps with the corresponding resources use the build → registry → image
policy → bot commit → Flux path. This checkout has no per-app image-automation
resources in the public manifests; do not assume older `sample-site-a` examples
are deployed. Third-party image/chart updates use the reviewed manifest workflow.

`mise exec -- task reconcile` forces root reconciliation and needs explicit
operator approval. It neither builds an image nor deploys an unmerged local diff.
Avoid live image edits and rollout restarts that bypass the owning Git source.

## Diagnose a failure

Record the symptom, expected behavior, exact target, revision/generation, and
incident window. Follow:

```text
Git intent → Flux artifact → render/apply → workload → dependencies → endpoint
```

Use the health checks above to find the first failing layer. For a failing
Flux object, retain its reason/message and inspect that exact object:

```sh
mise exec -- kubectl -n <flux-namespace> describe kustomization <app>
mise exec -- kubectl -n <release-namespace> describe helmrelease <release>
```

For a workload failure, choose one pod from its namespace and keep reads bounded:

```sh
mise exec -- kubectl -n <workload-namespace> get pods -o wide
mise exec -- kubectl -n <workload-namespace> describe pod <pod>
mise exec -- kubectl -n <workload-namespace> logs <pod> -c <container> \
  --since=30m --tail=100
mise exec -- kubectl -n <workload-namespace> get events \
  --field-selector involvedObject.kind=Pod,involvedObject.name=<pod> \
  --sort-by=.metadata.creationTimestamp
```

Use `logs --previous` for the previous container instance after a restart.
Match timestamps to the incident window and redact credentials before retaining
logs. If Flux is healthy but the endpoint fails, check the route, service
endpoints, DNS, and verified backend dependencies before changing anything.

Continue with the matching runbook:

- [Talos access and health](talos-health.md)
- [Helm remediation deadlocks](flux-helm-remediation.md)
- [Multus attachment failures](multus-attach-failure.md)
- [Kubernetes logs and Loki](kubernetes-logs-loki.md)

Repair the owning Git source or failed external dependency. Reconciles,
restarts, debug pods, port-forwards, and other live mutations require separate
approval with an exact target and expected effect.
