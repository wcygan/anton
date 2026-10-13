#!/bin/sh
# Inspection by default. Apply mode is only for the approved post-GC pilot/job.
set -eu
mode="$${MODE:-inspect-reclamation}"
case "$${mode}" in inspect-reclamation|apply-reclamation) ;; *) echo 'unsupported reclamation mode' >&2; exit 1 ;; esac
: "$${RECLAMATION_HOME:=/opt}"
case "$${VOLUME_ID:-}" in *[!0-9]*) echo 'invalid volume ID' >&2; exit 1 ;; esac

collect() {
  # JSON goes to bounded job-local /tmp, never to a persistent dataset.
  MODE=inspect sh "$${RECLAMATION_HOME}/reconcile.sh" > /tmp/harbor.json
  MODE=verify-images sh "$${RECLAMATION_HOME}/reconcile.sh" > /tmp/image-availability.json
  printf '[]' > /tmp/node-items.json
  for node in k8s-1 k8s-2 k8s-3; do
    kubectl get node "$${node}" -o json > /tmp/node.json
    jq --slurpfile node /tmp/node.json '. + [$$node[0]]' /tmp/node-items.json > /tmp/next.json
    mv /tmp/next.json /tmp/node-items.json
  done
  jq '{items:.}' /tmp/node-items.json > /tmp/nodes.json
  kubectl -n storage get volumes.longhorn.io -o json > /tmp/longhorn.json
  printf '[]' > /tmp/seaweed.json
  for pod in seaweedfs-volume-0 seaweedfs-volume-1 seaweedfs-volume-2; do
    kubectl -n storage get pod "$${pod}" -o json > /tmp/pod.json
    claim="$$(jq -er '[.spec.volumes[]|select(.persistentVolumeClaim!=null)] | if length==1 then .[0].persistentVolumeClaim.claimName else error("ambiguous PVC") end' /tmp/pod.json)"
    volume="$$(kubectl -n storage get pvc "$${claim}" -o jsonpath='{.spec.volumeName}')"
    [ -n "$${volume}" ] || { echo 'unbound SeaweedFS PVC' >&2; exit 1; }
    kubectl get --request-timeout=20s --raw "/api/v1/namespaces/storage/pods/$${pod}:8444/proxy/status" > /tmp/status.json
    jq --arg pod "$${pod}" --arg volume "$${volume}" --slurpfile status /tmp/status.json \
      '. + [{pod:$$pod,longhorn_volume:$$volume,status:$$status[0]}]' /tmp/seaweed.json > /tmp/next.json
    mv /tmp/next.json /tmp/seaweed.json
  done
  jq -n --slurpfile harbor /tmp/harbor.json --slurpfile nodes /tmp/nodes.json \
    --slurpfile longhorn /tmp/longhorn.json --slurpfile seaweed /tmp/seaweed.json \
    '{harbor:$$harbor[0],nodes:$$nodes[0],longhorn_volumes:$$longhorn[0],seaweed:$$seaweed[0]}' > /tmp/input.json
  jq --argjson now "$$(date -u +%s)" -f "$${RECLAMATION_HOME}/reclamation-gates.jq" /tmp/input.json > /tmp/eligible.json
}

collect
cat /tmp/eligible.json # Persist the checked GC ID and candidate byte counts in Job logs.
if [ -n "$${VOLUME_ID:-}" ]; then
  jq -e --argjson id "$${VOLUME_ID}" 'any(.seaweed[].status.Volumes[]; .Id==$$id and .Collection=="harbor")' /tmp/input.json >/dev/null || {
    echo 'unknown Harbor volume ID' >&2; exit 1;
  }
fi
if [ "$${mode}" = inspect-reclamation ]; then
  cat /tmp/eligible.json
  exit 0
fi

ids="$$(jq -r '.candidates[].volume_id' /tmp/eligible.json)"
for id in $${ids}; do
  [ -z "$${VOLUME_ID:-}" ] || [ "$${id}" = "$${VOLUME_ID}" ] || continue
  # Re-read all gates before every causal mutation. No automatic retries.
  collect
  candidate="$$(jq -c --argjson id "$${id}" '.candidates[]|select(.volume_id==$$id)' /tmp/eligible.json)"
  [ -n "$${candidate}" ] || continue
  pod="$$(printf '%s' "$${candidate}" | jq -r '.pod')"
  before="$$(jq -c --argjson id "$${id}" '.seaweed[].status.Volumes[]|select(.Id==$$id and .Collection=="harbor")' /tmp/input.json)"
  printf 'lock; volume.vacuum -collection=harbor -volumeId=%s -garbageThreshold=0.10; unlock\n' "$${id}" | \
    kubectl -n storage exec -i seaweedfs-master-0 -c master -- \
      weed shell -master=seaweedfs-master-0.seaweedfs-master-peer.storage:9333,seaweedfs-master-1.seaweedfs-master-peer.storage:9333,seaweedfs-master-2.seaweedfs-master-peer.storage:9333 > /tmp/vacuum.log 2>&1
  # weed shell can log command errors yet return zero; do not mistake that for success.
  if grep -Ei 'error|failed|not found|cannot|timeout' /tmp/vacuum.log >/dev/null; then
    echo 'uncertain compaction outcome; stop without retry' >&2; exit 1
  fi
  kubectl get --request-timeout=20s --raw "/api/v1/namespaces/storage/pods/$${pod}:8444/proxy/status" > /tmp/after.json
  after="$$(jq -ec --argjson id "$${id}" '[.Volumes[]|select(.Id==$$id and .Collection=="harbor")]|if length==1 then .[0] else error("volume missing") end' /tmp/after.json)"
  jq -en --argjson before "$${before}" --argjson after "$${after}" \
    '$$after.CompactRevision > $$before.CompactRevision and $$after.Size < $$before.Size and $$after.ReadOnly==false' >/dev/null || {
      echo 'compaction did not demonstrate completion; stop without retry' >&2; exit 1;
    }
  jq -n --argjson id "$${id}" --argjson before "$${before}" --argjson after "$${after}" \
    '{volume_id:$$id,compaction_revision:$$after.CompactRevision,seaweed_size_reduction_bytes:($$before.Size-$$after.Size)}'
  collect # Post-action health gates must pass before the next volume.
done
