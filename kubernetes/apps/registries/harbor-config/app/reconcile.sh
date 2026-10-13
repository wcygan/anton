#!/bin/sh

set -eu

: "$${HARBOR_API_URL:?HARBOR_API_URL is required}"
: "$${HARBOR_USERNAME:?HARBOR_USERNAME is required}"
: "$${HARBOR_PASSWORD:?HARBOR_PASSWORD is required}"
: "$${HARBOR_RETENTION_CRON:?HARBOR_RETENTION_CRON is required}"
: "$${HARBOR_PROTECTED_TAGS:?HARBOR_PROTECTED_TAGS is required}"
: "$${HARBOR_IMAGE_HOST:?HARBOR_IMAGE_HOST is required}"
: "$${HARBOR_GC_CRON:?HARBOR_GC_CRON is required}"

api_url="$${HARBOR_API_URL%/}"
auth="$${HARBOR_USERNAME}:$${HARBOR_PASSWORD}"
mode="$${MODE:-reconcile}"
case "$${mode}" in
  reconcile|gc-dry-run|inspect|verify-images) ;;
  *) echo "unsupported mode" >&2; exit 1 ;;
esac

harbor_request() {
  method="$${1}"
  path="$${2}"
  payload="$${3:-}"
  if { [ "$${mode}" = inspect ] || [ "$${mode}" = verify-images ]; } && [ "$${method}" != GET ]; then
    echo "inspection forbids API writes" >&2
    exit 1
  fi

  if [ -n "$${payload}" ]; then
    curl \
      --fail \
      --silent \
      --show-error \
      --connect-timeout 5 --max-time 30 \
      --retry 5 \
      --retry-delay 5 \
      --retry-connrefused \
      --user "$${auth}" \
      --request "$${method}" \
      --header "Content-Type: application/json" \
      --data "$${payload}" \
      "$${api_url}$${path}"
    return
  fi

  curl \
    --fail \
    --silent \
    --show-error \
    --connect-timeout 5 --max-time 30 \
    --retry 5 \
    --retry-delay 5 \
    --retry-connrefused \
    --user "$${auth}" \
    --request "$${method}" \
    "$${api_url}$${path}"
}

if [ "$${mode}" = gc-dry-run ]; then
  harbor_request POST /system/gc/schedule '{"schedule":{"type":"Manual"},"parameters":{"dry_run":true,"delete_untagged":false,"workers":1}}' >/dev/null
  echo "submitted garbage collection dry run"
  exit 0
fi

if [ "$${mode}" = verify-images ]; then
  # Use registry token auth inside the pod; never print tokens or passwords.
  workloads="$$(kubectl get pods,deployments,statefulsets,daemonsets,jobs,cronjobs -A -o json)"
  images="$$(printf '%s' "$${workloads}" | jq -r --arg host "$${HARBOR_IMAGE_HOST}" '[.. | objects | .image? // empty | select(type=="string") | select(startswith($$host+"/"))] | unique[]')"
  count=0
  blobs=0
  for image in $${images}; do
    image=$${image#*/}
    case "$${image}" in
      *@*) reference=$${image##*@}; repository=$${image%@*}; repository=$${repository%:*} ;;
      *:*) reference=$${image##*:}; repository=$${image%:*} ;;
      *) reference=latest; repository=$${image} ;;
    esac
    project=$${repository%%/*}
    repo=$${repository#*/}
    encoded="$$(printf '%s' "$${repo}" | jq -sRr '@uri | @uri')"
    digest="$$(harbor_request GET "/projects/$${project}/repositories/$${encoded}/artifacts/$${reference}" | jq -er '.digest')"
    token="$$(curl --fail --silent --show-error --max-time 30 --user "$${auth}" \
      --get --data-urlencode 'service=harbor-registry' --data-urlencode "scope=repository:$${repository}:pull" \
      "$${HARBOR_TOKEN_URL:-$${api_url%/api/v2.0}/service/token}" | jq -er '.token')"
    queue="$${digest}"
    seen=' '
    manifests=0
    while [ -n "$${queue}" ]; do
      current=$${queue%% *}
      if [ "$${queue}" = "$${current}" ]; then queue=''; else queue=$${queue#* }; fi
      case "$${seen}" in *" $${current} "*) continue ;; esac
      printf '%s' "$${current}" | grep -Eq '^sha256:[0-9a-f]{64}$' || { echo 'invalid manifest digest' >&2; exit 1; }
      seen="$${seen}$${current} "
      manifests=$((manifests + 1))
      [ "$${manifests}" -le 64 ] || { echo 'manifest graph exceeds verification bound' >&2; exit 1; }
      manifest="$$(curl --fail --silent --show-error --max-time 30 --max-filesize 1048576 \
        --header "Authorization: Bearer $${token}" \
        --header 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' \
        "$${HARBOR_REGISTRY_URL:-http://harbor}/v2/$${repository}/manifests/$${current}")"
      children="$$(printf '%s' "$${manifest}" | jq -er 'if .schemaVersion==2 then [.manifests[]?.digest]|join(" ") else error("invalid manifest") end')"
      [ -z "$${children}" ] || queue="$${queue:+$${queue} }$${children}"
      digests="$$(printf '%s' "$${manifest}" | jq -r '[(.config.digest // empty),.layers[]?.digest]|unique[]')"
      for blob in $${digests}; do
        printf '%s' "$${blob}" | grep -Eq '^sha256:[0-9a-f]{64}$' || { echo 'invalid blob digest' >&2; exit 1; }
        code="$$(curl --fail --silent --show-error --head --output /dev/null --max-time 30 --write-out '%{http_code}' \
          --header "Authorization: Bearer $${token}" "$${HARBOR_REGISTRY_URL:-http://harbor}/v2/$${repository}/blobs/$${blob}")"
        [ "$${code}" = 200 ] || { echo 'blob availability not confirmed' >&2; exit 1; }
        blobs=$((blobs + 1))
      done
    done
    count=$((count + 1))
  done
  jq -n --argjson count "$${count}" --argjson blobs "$${blobs}" '{verified_artifacts:$$count,readable_blobs:$$blobs}'
  exit 0
fi

if [ "$${mode}" = inspect ]; then
  # Allowlisted response fields only: never include credentials/configuration.
  health="$$(harbor_request GET /health | jq '{components:[.components[]|{name,status}]}')"
  # Harbor 2.15 returns GCHistory here: options are JSON in job_parameters.
  gc="$$(harbor_request GET /system/gc/schedule | jq '(.parameters // (.job_parameters | fromjson)) as $$p | {schedule:{type:.schedule.type,cron:.schedule.cron},parameters:($$p|{dry_run:(.dry_run // false),delete_untagged:(.delete_untagged // false),workers})}')"
  history="$$(harbor_request GET '/system/gc?page=1&page_size=20' | jq '[.[] | {id,job_status,creation_time,update_time,job_kind,schedule:(.schedule|{type,cron}),parameters:((.job_parameters | if type == "string" then fromjson else . end) | {dry_run:(.dry_run // false),delete_untagged:(.delete_untagged // false),workers})}]')"
  report='[]'
  page=1
  while :; do
    projects="$$(harbor_request GET "/projects?page=$${page}&page_size=100")"
    printf '%s' "$${projects}" | jq -e 'type=="array"' >/dev/null
    ids="$$(printf '%s' "$${projects}" | jq -r '.[].project_id')"
    for id in $${ids}; do
      retention="$$(harbor_request GET "/projects/$${id}/metadatas/" | jq -er '.retention_id')"
      policy="$$(harbor_request GET "/retentions/$${retention}")"
      executions="$$(harbor_request GET "/retentions/$${retention}/executions?page=1&page_size=20" | jq '[.[] | {id,policy_id,start_time,end_time,status,trigger,dry_run:(.dry_run // false)}]')"
      report="$$(printf '%s' "$${report}" | jq --argjson id "$${id}" --argjson policy "$${policy}" --argjson executions "$${executions}" '. + [{project_id:$$id,policy:($$policy|{algorithm,rules,trigger,scope}),executions:$$executions}]')"
    done
    [ "$$(printf '%s' "$${projects}" | jq 'length')" -lt 100 ] && break
    page=$((page + 1))
  done
  jq -n --argjson gc "$${gc}" --argjson history "$${history}" --argjson projects "$${report}" --argjson health "$${health}" '{gc:$$gc,gc_executions:$$history,projects:$$projects,health:$$health}'
  exit 0
fi

policy_for_project() {
  project_id="$${1}"

  jq -n \
    --argjson project_id "$${project_id}" \
    --arg cron "$${HARBOR_RETENTION_CRON}" \
    --arg protected_tags "$${HARBOR_PROTECTED_TAGS}" \
    '
      def all_repositories:
        {repository: [{kind: "doublestar", decoration: "repoMatches", pattern: "**"}]};
      def tagged_artifacts:
        ({untagged: false} | tojson);
      def selector($$pattern):
        {kind: "doublestar", decoration: "matches", pattern: $$pattern, extras: tagged_artifacts};

      {
        algorithm: "or",
        rules: [
          {
            disabled: false,
            action: "retain",
            scope_selectors: all_repositories,
            tag_selectors: [selector("**")],
            params: {latestPushedK: 2},
            template: "latestPushedK"
          },
          {
            disabled: false,
            action: "retain",
            scope_selectors: all_repositories,
            tag_selectors: [selector($$protected_tags)],
            params: {},
            template: "always"
          }
        ],
        trigger: {
          kind: "Schedule",
          references: {},
          settings: {cron: $$cron}
        },
        scope: {level: "project", ref: $$project_id}
      }
    '
}

normalise_policy() {
  jq -S '
    del(.id)
    | del(.trigger.settings.next_scheduled_time)
    | .rules |= map(del(.id, .priority))
  '
}

reconcile_project() {
  project_id="$${1}"
  desired="$$(policy_for_project "$${project_id}")"
  retention_id="$$(harbor_request GET "/projects/$${project_id}/metadatas/" | jq -r '.retention_id // empty')"

  if [ -z "$${retention_id}" ]; then
    harbor_request POST /retentions "$${desired}" >/dev/null
    echo "created retention policy for project $${project_id}"
    return
  fi

  current="$$(harbor_request GET "/retentions/$${retention_id}")"
  if [ "$$(printf '%s' "$${current}" | normalise_policy)" = "$$(printf '%s' "$${desired}" | normalise_policy)" ]; then
    echo "retention policy for project $${project_id} is current"
    return
  fi

  harbor_request PUT "/retentions/$${retention_id}" "$${desired}" >/dev/null
  echo "updated retention policy $${retention_id} for project $${project_id}"
}

# Fail closed if the complete workload inventory cannot be read. Include
# scaled-to-zero controllers and scheduled jobs, not obsolete ReplicaSets.
workloads="$$(kubectl get pods,deployments,statefulsets,daemonsets,jobs,cronjobs -A -o json)"
images="$$(printf '%s' "$${workloads}" | jq -r --arg host "$${HARBOR_IMAGE_HOST}" \
  '[.. | objects | .image? // empty | select(type == "string") | select(startswith($$host + "/"))] | unique[]')"
protected=""
for image in $${images}; do
  image=$${image#*/}
  case "$${image}" in
    *@*) reference=$${image##*@}; repository=$${image%@*}; repository=$${repository%:*} ;;
    *:*) reference=$${image##*:}; repository=$${image%:*} ;;
    *) reference=latest; repository=$${image} ;;
  esac
  project=$${repository%%/*}
  repository=$${repository#*/}
  encoded="$$(printf '%s' "$${repository}" | jq -sRr '@uri | @uri')"
  artifact="$$(harbor_request GET "/projects/$${project}/repositories/$${encoded}/artifacts/$${reference}")"
  digest="$$(printf '%s' "$${artifact}" | jq -er '.digest')"
  tag="in-use-$${digest#sha256:}"
  protected="$${protected} $${tag}"
  if ! printf '%s' "$${artifact}" | jq -e --arg tag "$${tag}" 'any(.tags[]?; .name == $$tag)' >/dev/null; then
    harbor_request POST "/projects/$${project}/repositories/$${encoded}/artifacts/$${digest}/tags" \
      "$$(jq -n --arg name "$${tag}" '{name:$$name}')" >/dev/null
  fi
done

page=1
while :; do
  projects="$$(harbor_request GET "/projects?page=$${page}&page_size=100")"
  project_count="$$(printf '%s' "$${projects}" | jq 'length')"

  [ "$${project_count}" -eq 0 ] && break

  printf '%s' "$${projects}" | jq -r '.[].project_id' | while IFS= read -r project_id; do
    reconcile_project "$${project_id}"
  done

  [ "$${project_count}" -lt 100 ] && break
  page=$((page + 1))
done

# Remove only this reconciler's obsolete protection tags. Keep artifact
# deletion in Harbor retention; a failed inventory above prevents this stage.
page=1
while :; do
  repositories="$$(harbor_request GET "/repositories?page=$${page}&page_size=100")"
  count="$$(printf '%s' "$${repositories}" | jq 'length')"
  [ "$${count}" -eq 0 ] && break
  printf '%s' "$${repositories}" | jq -r '.[].name' | while IFS= read -r full; do
    project=$${full%%/*}
    repository=$${full#*/}
    encoded="$$(printf '%s' "$${repository}" | jq -sRr '@uri | @uri')"
    artifact_page=1
    while :; do
      artifacts="$$(harbor_request GET "/projects/$${project}/repositories/$${encoded}/artifacts?page=$${artifact_page}&page_size=100&with_tag=true")"
      printf '%s' "$${artifacts}" | jq -r '.[] | .digest as $$digest | .tags[]? | select(.name | startswith("in-use-")) | [$$digest,.name] | @tsv' | \
      while read -r digest tag; do
        case " $${protected} " in
          *" $${tag} "*) ;;
          *) harbor_request DELETE "/projects/$${project}/repositories/$${encoded}/artifacts/$${digest}/tags/$${tag}" >/dev/null ;;
        esac
      done
      [ "$$(printf '%s' "$${artifacts}" | jq 'length')" -lt 100 ] && break
      artifact_page=$((artifact_page + 1))
    done
  done
  [ "$${count}" -lt 100 ] && break
  page=$((page + 1))
done

# Retention drops references daily; GC frees unreferenced blobs weekly.
# Keep untagged artifacts: a digest-only deploy outside this inventory must
# not be removed merely because it lacks a tag.
desired_gc="$$(jq -n --arg cron "$${HARBOR_GC_CRON}" \
  '{schedule:{type:"Custom",cron:$$cron},parameters:{delete_untagged:false,dry_run:false,workers:1}}')"
current_gc="$$(harbor_request GET /system/gc/schedule)"
normalise_gc() {
  # Harbor serializes false dry_run with omitempty; its absent default is false.
  jq -S '(.parameters // (.job_parameters | fromjson)) as $$p | {schedule:{type:.schedule.type,cron:.schedule.cron},parameters:($$p|{dry_run:(.dry_run // false),delete_untagged:(.delete_untagged // false),workers})}'
}
current_gc_normalised="$$(printf '%s' "$${current_gc}" | normalise_gc)"
desired_gc_normalised="$$(printf '%s' "$${desired_gc}" | normalise_gc)"
if [ "$${current_gc_normalised}" != "$${desired_gc_normalised}" ]; then
  harbor_request PUT /system/gc/schedule "$${desired_gc}" >/dev/null
  echo "updated weekly garbage collection schedule"
fi
