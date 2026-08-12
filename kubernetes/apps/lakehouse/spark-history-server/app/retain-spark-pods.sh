#!/bin/sh
set -eu

: "$${SUCCESS_RETENTION_SECONDS:?SUCCESS_RETENTION_SECONDS is required}"
: "$${FAILURE_RETENTION_SECONDS:?FAILURE_RETENTION_SECONDS is required}"

now="$${NOW_EPOCH_SECONDS:-$(date +%s)}"

expired_pods() {
  phase="$1"
  retention="$2"
  kubectl get pods \
    --selector='anton.io/retain-failed-pod=true' \
    --output=json \
    | jq --raw-output \
      --arg phase "$phase" \
      --argjson now "$now" \
      --argjson retention "$retention" '
        .items[]
        | select(.status.phase == $phase)
        | ([.status.containerStatuses[]?.state.terminated.finishedAt]
            | map(select(. != null))
            | max // "") as $finished
        | select($finished != "")
        | select(($now - ($finished | fromdateiso8601)) >= $retention)
        | .metadata.name
      '
}

delete_pods() {
  phase="$1"
  retention="$2"
  expired_pods "$phase" "$retention" | while IFS= read -r pod; do
    [ -n "$pod" ] || continue
    kubectl delete pod "$pod" --wait=false
    printf 'level=info message="deleted expired Spark pod" pod=%s phase=%s retention_seconds=%s\n' \
      "$pod" "$phase" "$retention"
  done
}

delete_pods Succeeded "$SUCCESS_RETENTION_SECONDS"
delete_pods Failed "$FAILURE_RETENTION_SECONDS"
