#!/bin/sh
reconcile_home="$${HARBOR_RECONCILE_HOME:-$$(dirname "$$0")}"

resolve_inventory() {
  # Keep full Kubernetes JSON out of shell variables/argv (ARG_MAX and RSS).
  scratch="$${HARBOR_SCRATCH_DIR:-/tmp}"
  for kind in pods deployments statefulsets daemonsets replicasets controllerrevisions jobs cronjobs; do
    kubectl get "$$kind" -A --chunk-size=50 -o json > "$$scratch/harbor-kind.json" || return 1
    jq -c '
      if (.items|type)!="array" then error("incomplete workload inventory") else . end |
      {items:[.items[] |
        if .kind=="ControllerRevision" and (.data|type)!="object" then error("unreadable controller revision") else . end |
        {kind, data:(if .kind=="ControllerRevision" then {} else null end),
         images:[..|objects|{image:(.image // null),imageID:(.imageID // null)}|select(.image!=null or .imageID!=null)],
         status:(if .kind=="Pod" then (.status|{containerStatuses,initContainerStatuses,ephemeralContainerStatuses}) else {} end)}]}
    ' "$$scratch/harbor-kind.json" > "$$scratch/harbor-projected-$$kind.json" || return 1
  done
  jq -s '{items:map(.items)|add}' "$$scratch/harbor-projected-pods.json" "$$scratch/harbor-projected-deployments.json" "$$scratch/harbor-projected-statefulsets.json" "$$scratch/harbor-projected-daemonsets.json" "$$scratch/harbor-projected-replicasets.json" "$$scratch/harbor-projected-controllerrevisions.json" "$$scratch/harbor-projected-jobs.json" "$$scratch/harbor-projected-cronjobs.json" > "$$scratch/harbor-workloads.json" || return 1
  kubectl -n registries get ingresses -o json > "$$scratch/harbor-ingresses.json" || return 1
  references="$$( { printf '{"workloads":'; cat "$$scratch/harbor-workloads.json"; printf ',"ingresses":'; cat "$$scratch/harbor-ingresses.json"; printf '}'; } | jq --arg host "$$HARBOR_IMAGE_HOST" -f "$$reconcile_home/protected-images.jq")" || return 1
  records='[]'
  for row in $$(printf '%s' "$$references" | jq -r '.[]|@base64'); do
    record="$$(printf '%s' "$$row" | base64 -d)"
    repository="$$(printf '%s' "$$record" | jq -r '.repository')"
    reference="$$(printf '%s' "$$record" | jq -r '.reference')"
    project=$${repository%%/*}; repo=$${repository#*/}
    encoded="$$(printf '%s' "$$repo" | jq -sRr '@uri|@uri')"
    artifact="$$(harbor_request GET "/projects/$$project/repositories/$$encoded/artifacts/$$reference")"
    digest="$$(printf '%s' "$$artifact" | jq -er '.digest|select(test("^sha256:[0-9a-f]{64}$$"))')"
    records="$$(printf '%s' "$$records" | jq --arg repository "$$repository" --arg digest "$$digest" '. + [{repository:$$repository,digest:$$digest}]')"
  done
  printf '%s' "$$records" | jq -Sc 'unique_by([.repository,.digest])|sort_by(.repository,.digest)'
}

inventory_hash() { printf '%s' "$$1" | sha256sum | cut -d' ' -f1; }

verify_filers() {
  pods="$$(kubectl -n storage get pods seaweedfs-filer-0 seaweedfs-filer-1 -o json)"
  claims="$$(kubectl -n storage get pvc seaweedfs-filer-seaweedfs-filer-0 seaweedfs-filer-seaweedfs-filer-1 -o json)"
  volumes="$$(kubectl -n storage get volumes.longhorn.io -o json)"
  jq -n --argjson pods "$$pods" --argjson claims "$$claims" --argjson volumes "$$volumes" '{pods:$$pods,claims:$$claims,volumes:$$volumes}' | jq -f "$$reconcile_home/filer-persistence.jq"
}

verify_inventory() {
  verified="$$1";count=0;blobs=0
  for row in $$(printf '%s' "$$verified" | jq -r '.[]|@base64'); do
    record="$$(printf '%s' "$$row" | base64 -d)"
    repository="$$(printf '%s' "$$record" | jq -r '.repository')"
    digest="$$(printf '%s' "$$record" | jq -r '.digest')"
    token_response="$$(curl --fail --silent --show-error --connect-timeout 5 --max-time 30 --user "$$auth" --get --data-urlencode 'service=harbor-registry' --data-urlencode "scope=repository:$$repository:pull" "$${HARBOR_TOKEN_URL:-$${api_url%/api/v2.0}/service/token}")"
    token="$$(printf '%s' "$$token_response" | jq -er '.token|select(type=="string" and length>0)')"
    queue="$$digest";seen=' ';manifests=0
    while [ -n "$$queue" ]; do
      current=$${queue%% *}
      if [ "$$queue" = "$$current" ]; then queue=''; else queue=$${queue#* }; fi
      case "$$seen" in *" $$current "*) continue ;; esac
      printf '%s' "$$current" | grep -Eq '^sha256:[0-9a-f]{64}$$' || { echo 'invalid manifest digest' >&2;exit 1; }
      seen="$$seen$$current ";manifests=$$((manifests+1))
      [ "$$manifests" -le 64 ] || { echo 'manifest graph exceeds bound' >&2;exit 1; }
      manifest="$$(curl --fail --silent --show-error --connect-timeout 5 --max-time 30 --max-filesize 1048576 --header "Authorization: Bearer $$token" --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' "$${HARBOR_REGISTRY_URL:-http://harbor}/v2/$$repository/manifests/$$current")" || { echo 'registry manifest verification failed' >&2;exit 1; }
      children="$$(printf '%s' "$$manifest" | jq -er 'if .schemaVersion==2 then [.manifests[]?.digest]|join(" ") else error("invalid manifest") end')"
      [ -z "$$children" ] || queue="$${queue:+$$queue }$$children"
      digests="$$(printf '%s' "$$manifest" | jq -r '[(.config.digest // empty),.layers[]?.digest]|unique[]')"
      for blob in $$digests; do
        printf '%s' "$$blob" | grep -Eq '^sha256:[0-9a-f]{64}$$' || { echo 'invalid blob digest' >&2;exit 1; }
        code="$$(curl --fail --silent --show-error --head --output /dev/null --connect-timeout 5 --max-time 30 --write-out '%{http_code}' --header "Authorization: Bearer $$token" "$${HARBOR_REGISTRY_URL:-http://harbor}/v2/$$repository/blobs/$$blob")" || { echo 'registry blob verification failed' >&2;exit 1; }
        [ "$$code" = 200 ] || { echo 'blob availability not confirmed' >&2;exit 1; }
        blobs=$$((blobs+1))
      done
    done
    count=$$((count+1))
  done
  jq -n --argjson count "$$count" --argjson blobs "$$blobs" --arg hash "$$(inventory_hash "$$verified")" '{verified_artifacts:$$count,readable_blobs:$$blobs,inventory_sha256:$$hash}'
}

write_evidence() {
  kubectl -n registries patch configmap harbor-retention-status --type=merge -p "$$(jq -n --arg content "$$1" '{data:{evidence:$$content}}')" >/dev/null
}

execute_retention() {
  policy_id="$$1";dry_run="$$2"
  prior="$$(harbor_request GET "/retentions/$$policy_id/executions?page=1&page_size=100")"
  printf '%s' "$$prior" | jq -e 'type=="array" and all(.[]; .status=="Success" or .status=="Error" or .status=="Stopped")' >/dev/null || { echo 'retention already active or outcome unknown' >&2;exit 1; }
  previous="$$(printf '%s' "$$prior" | jq '[.[].id]|max // 0')"
  harbor_request POST "/retentions/$$policy_id/executions" "$$(jq -n --argjson dry_run "$$dry_run" '{dry_run:$$dry_run}')" >/dev/null
  attempts=0
  while [ "$$attempts" -lt 60 ]; do
    executions="$$(harbor_request GET "/retentions/$$policy_id/executions?page=1&page_size=100")"
    execution="$$(printf '%s' "$$executions" | jq -c --argjson previous "$$previous" '[.[]|select(.id>$$previous)]|if length>1 then error("ambiguous retention execution") else .[0] // {} end')"
    state="$$(printf '%s' "$$execution" | jq -r '.status // "Pending"')"
    case "$$state" in
      Success)
        printf '%s' "$$execution" | jq -e --argjson dry_run "$$dry_run" '(.dry_run // false)==$$dry_run' >/dev/null
        printf '%s' "$$execution" | jq -c '{id,policy_id,start_time,end_time,status,dry_run:(.dry_run // false)}';return ;;
      Pending|Running|Scheduled|InProgress) ;;
      *) echo 'retention execution failed; stop' >&2;exit 1 ;;
    esac
    attempts=$$((attempts+1));sleep 5
  done
  echo 'retention completion not confirmed; stop without retry' >&2;exit 1
}
