# 2026-04-24 software-side k8s-2 rejoin options

## Bottom line

k8s-2 is **not mitigated for normal scheduling yet**. The cluster-level trigger
surface can be reduced substantially without touching hardware, but the incident
is only mitigated after k8s-2 survives a staged rejoin and burn-in with
netconsole live. Current evidence still has two unexplained silent reboots, both
on k8s-2.

Hardware having worked in the past is useful context, but it does not clear the
node: the recent software state changed materially (Talos/kernel image,
Cilium/Multus/Whereabouts, Longhorn storage fabric, Harbor/SeaweedFS/CNPG
churn, kube-apiserver watch load). Those changes can expose a marginal power,
firmware, NIC, CPU, RAM, or kernel path without any physical hardware change.

## Recommended order

| Priority | Change | Why |
|---|---|---|
| P0 | Keep k8s-2 gated by a hard taint during rejoin, not just `PreferNoSchedule` | The 04-23 cohort landed despite the soft taint. Use an explicit `NoSchedule` taint and only add tolerations to selected test/compute workloads. Kubernetes taints repel pods unless tolerated. |
| P0 | Clear k8s-2's stale kubelet/containerd state before trusting it | The README still records post-reboot sandbox-name / kubelet-volume reconciler saturation. A carefully scoped Talos reset or rejoin can wipe persistent node runtime state, but it is destructive and must be etcd/Longhorn gated. |
| P0 | Finish CNI plumbing hardening | Multus 512Mi is already patched locally. Next candidates: whereabouts memory request/limit, storage-vxlan 128-256Mi, `priorityClassName` on Multus/Whereabouts/storage-vxlan, and CNI restart/memory alerts. |
| P0 | Add kubelet node-reservation headroom | Add `systemReserved`, `kubeReserved`, and `evictionHard` via Talos kubelet `extraConfig`. This prevents schedulable pods from consuming memory needed by kubelet, containerd, control-plane static pods, CNI, and Longhorn. |
| P1 | Add topology spread / anti-affinity to stateful and high-churn apps | Prevent a drain/reboot from piling Harbor, CSI, SeaweedFS, CNPG/Dragonfly, and operators onto k8s-2 at once. SeaweedFS volume anti-affinity already exists; extend this pattern to remaining components where charts/CRDs expose it. |
| P1 | Make drains boring | Do not proceed after a non-zero drain during rejoin tests. Longhorn explicitly blocks drains to protect replicas; investigate events/logs instead of treating a partial drain as good enough. Use one node at a time and no concurrent Flux rollouts. |
| P1 | Instrument kube-apiserver watch pressure per instance | The 04-23 pre-reset mover was corrected to +456MiB apiserver WSS with longrunning/watch growth. Add dashboard/alerts for `apiserver_longrunning_requests`, watch event rate, inflight requests, and APF queue/reject metrics by apiserver instance. |
| P1 | Apply API Priority and Fairness only after finding a noisy client | APF can isolate request flows and applies to watch requests, but blind tuning risks hiding the client that needs fixing. First identify the client/resource pair driving watch rehydration. |
| P1 | Keep observability off k8s-2 during burn-in | The log sink is already hard-excluded from k8s-2. Keep singleton observability components and any reboot detector off k8s-2 until it proves stable. |
| P2 | Test reversible NIC/power-management software knobs only if recurrence continues | Possible knobs: disable EEE on I226 links if Talos exposes ethtool-equivalent control, pin relevant PCI devices to `power/control=on` via `machine.sysfs`, or disable deeper C-state/ASPM paths only with a planned reboot path. These are less evidence-backed than CNI/scheduling/headroom. |
| P2 | Upgrade only for targeted fixes | Talos v1.12.6 and Kubernetes v1.35.3 are current enough for this branch. Do not churn versions as a blind fix; do targeted Talos/Cilium/kernel upgrades only if release notes match NIC, cgroup, apiserver, or datapath symptoms. |

## Concrete repo changes

1. Add a persistent k8s-2 rejoin taint/label.
   - Use Talos `machine.nodeTaints` / `machine.nodeLabels` for persistence, or
     a GitOps-owned node policy if we add one later.
   - Example intent: `anton.io/rejoin=k8s-2:NoSchedule`.
   - Only the staged test workload and eventual compute namespace get a matching
     toleration.

2. Add kubelet reservations in `talos/patches/global/machine-kubelet.yaml`.
   - Candidate starting point for 96GiB MS-01 nodes:
     `systemReserved.memory=2Gi`, `kubeReserved.memory=2Gi`,
     `evictionHard.memory.available=2Gi`, plus modest CPU reservations.
   - Tune after observing allocatable and steady-state daemon usage.

3. Finish CNI hardening.
   - Land the existing Multus 512Mi change.
   - Add Whereabouts resources; current evidence does not prove OOM, but it is
     CNI-critical and cheap to give headroom.
   - Raise storage-vxlan from 32/64Mi to at least 64/128Mi or 128/256Mi.
   - Add `priorityClassName: system-node-critical` or
     `system-cluster-critical` to CNI plumbing after checking rendered manifests.
   - Add `prometheusrule-cni-plumbing.yaml` and dashboard panels for restarts,
     memory near limit, and OOMKilled reasons.

4. Shape rejoin scheduling.
   - Keep k8s-2 cordoned until the above lands.
   - Then uncordon with a hard taint still present.
   - Start with 5-10 low-risk compute pods for 24h.
   - Expand to selected compute for 48h.
   - Remove the taint only after 7 days without reboot/CNI restarts.

5. Reduce drain-induced bursts.
   - Add/verify PDBs for Harbor, CNPG, Dragonfly, SeaweedFS, and observability.
   - Add anti-affinity/spread constraints for Harbor core/portal/registry,
     SeaweedFS master/filer/S3, CNPG instances, Dragonfly pods, and CSI
     sidecars where the owning chart supports it.
   - During rejoin, freeze unrelated Flux changes and do not run Harbor/Longhorn
     drain tests at the same time.

6. Add apiserver watch/runaway visibility.
   - Dashboard/alert by apiserver instance:
     `apiserver_longrunning_requests`,
     `rate(apiserver_watch_events_total[1m])`,
     `apiserver_current_inflight_requests`,
     `apiserver_flowcontrol_*`.
   - If one controller is noisy, use APF FlowSchema/PriorityLevel tuning or move
     that controller off k8s-2 during burn-in.

7. Consider a software reset/rejoin of k8s-2 before full use.
   - This is the cleanest software-only way to remove persistent
     kubelet/containerd zombie state.
   - It is destructive for that machine. For a control-plane node, gate on etcd
     health/snapshot, Longhorn replica health, and explicit wipe scope. Talos
     supports wiping selected STATE/EPHEMERAL partitions, but the exact command
     should be treated as an execution plan, not an ad hoc shell command.

## Rejoin success criteria

- No `node_boot_time_seconds` change on any node.
- No CNI DaemonSet restart increments.
- No OOMKilled events in CNI, Cilium, kube-apiserver, Longhorn, or CSI.
- k8s-2 apiserver WSS does not grow rapidly without a matching explained client.
- Netconsole/vector sink keeps receiving k8s-2 kernel records.
- Longhorn replicas are healthy and no drain/rebuild storm is in progress.

## Sources

Local:

- `context/notes/k8s-2-instability/README.md`
- `context/notes/k8s-2-instability/evidence-2026-04-24-apiserver-and-whereabouts.md`
- `context/notes/k8s-2-instability/evidence-2026-04-24-hardware-firmware-survey.md`
- `context/plans/0006-adopt-harbor-seaweedfs.md`
- `context/plans/0009-k8s-2-k8s-3-silent-reboot-followup.md`
- `kubernetes/apps/network/multus/app/flux-kustomization.yaml`
- `kubernetes/apps/network/whereabouts/app/flux-kustomization.yaml`
- `kubernetes/apps/network/storage-vxlan/app/daemonset.yaml`
- `talos/patches/global/machine-kubelet.yaml`

External:

- Kubernetes reserve compute resources:
  https://kubernetes.io/docs/tasks/administer-cluster/reserve-compute-resources/
- Kubernetes critical addon scheduling:
  https://kubernetes.io/docs/tasks/administer-cluster/guaranteed-scheduling-critical-addon-pods/
- Kubernetes taints/tolerations:
  https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/
- Kubernetes topology spread:
  https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/
- Kubernetes API Priority and Fairness:
  https://kubernetes.io/docs/concepts/cluster-administration/flow-control/
- Talos MachineConfig reference:
  https://docs.siderolabs.com/talos/v1.12/reference/configuration/v1alpha1/config
- Talos reset docs:
  https://www.talos.dev/v1.10/talos-guides/resetting-a-machine/
- Longhorn maintenance/drain docs:
  https://longhorn.io/docs/1.11.1/maintenance/maintenance/
- Multus high-memory issue:
  https://github.com/k8snetworkplumbingwg/multus-cni/issues/1346
- Broadcom Multus OOM/high-memory KB:
  https://knowledge.broadcom.com/external/article/371362/prepare-kubernetes-12410-workload-cluste.html
- Cilium issue #42007:
  https://github.com/cilium/cilium/issues/42007
- Talos v1.12.6 release:
  https://github.com/siderolabs/talos/releases/tag/v1.12.6
- Kubernetes releases:
  https://kubernetes.io/releases
