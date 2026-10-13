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
  reconcile|retention|retention-dry-run|gc-dry-run|inspect|verify-images|verify-filers) ;;
  *) echo "unsupported mode" >&2; exit 1 ;;
esac

harbor_request() {
  method="$${1}"
  path="$${2}"
  payload="$${3:-}"
  if { [ "$${mode}" = inspect ] || [ "$${mode}" = verify-images ] || [ "$${mode}" = verify-filers ]; } && [ "$${method}" != GET ]; then
    echo "inspection forbids API writes" >&2
    exit 1
  fi

  if [ -n "$${payload}" ]; then
    curl \
      --fail \
      --silent \
      --show-error \
      --connect-timeout 5 --max-time 30 \
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
    --user "$${auth}" \
    --request "$${method}" \
    "$${api_url}$${path}"
}

if [ "$${mode}" = gc-dry-run ]; then
  harbor_request POST /system/gc/schedule '{"schedule":{"type":"Manual"},"parameters":{"dry_run":true,"delete_untagged":false,"workers":1}}' >/dev/null
  echo "submitted garbage collection dry run"
  exit 0
fi

reconcile_home="$${HARBOR_RECONCILE_HOME:-$$(dirname "$0")}"
. "$${reconcile_home}/helpers.sh"
if [ "$${mode}" = verify-images ]; then
  verified_inventory="$$(resolve_inventory)"
  verify_inventory "$${verified_inventory}"
  exit 0
fi
if [ "$${mode}" = verify-filers ]; then
  verify_filers
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
          },
          {
            disabled: false,
            action: "retain",
            scope_selectors: all_repositories,
            tag_selectors: [{kind:"doublestar",decoration:"matches",pattern:"",extras:({untagged:true}|tojson)}],
            params: {},
            template: "always"
          }
        ],
        # Deletion is submitted only by the guarded Kubernetes job.
        trigger: {kind:"",references:{},settings:{}},
        scope: {level: "project", ref: $$project_id}
      }
    '
}

normalise_policy() {
  jq -S '
    del(.id)
    | del(.trigger.settings.next_scheduled_time)
    | .trigger.references = (.trigger.references // {})
    | .trigger.settings = (.trigger.settings // {})
    | .rules |= map(del(.id, .priority) | .disabled=(.disabled // false))
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

# Require durable filers and a complete, readable active/desired/rollback set.
# Harbor's scheduler stays Manual, so a failed inventory cannot trigger deletion.
filers="$$(verify_filers)"
protected_inventory="$$(resolve_inventory)"
image_verification="$$(verify_inventory "$${protected_inventory}")"
if [ "$${mode}" = retention ]; then write_evidence '{"state":"running"}'; fi
protected=""
for row in $$(printf '%s' "$${protected_inventory}" | jq -r '.[]|@base64'); do
  record="$$(printf '%s' "$${row}" | base64 -d)"
  full="$$(printf '%s' "$${record}" | jq -r '.repository')"
  digest="$$(printf '%s' "$${record}" | jq -r '.digest')"
  project=$${full%%/*}; repository=$${full#*/}
  encoded="$$(printf '%s' "$${repository}" | jq -sRr '@uri|@uri')"
  artifact="$$(harbor_request GET "/projects/$${project}/repositories/$${encoded}/artifacts/$${digest}")"
  tag="in-use-$${digest#sha256:}"
  protected="$${protected} $${tag}"
  if ! printf '%s' "$${artifact}" | jq -e --arg tag "$${tag}" 'any(.tags[]?;.name==$$tag)' >/dev/null; then
    harbor_request POST "/projects/$${project}/repositories/$${encoded}/artifacts/$${digest}/tags" "$$(jq -n --arg name "$${tag}" '{name:$$name}')" >/dev/null
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

# Abort before removing old protection if the workload set changed mid-run.
latest_inventory="$$(resolve_inventory)"
[ "$${latest_inventory}" = "$${protected_inventory}" ] || { echo 'protection inventory changed; stop' >&2;exit 1; }

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
desired_gc="$$(jq -n --arg cron "$${HARBOR_GC_CRON}" --arg enabled "$${HARBOR_GC_ENABLED:-true}" \
  '{schedule:(if $$enabled=="true" then {type:"Custom",cron:$$cron} elif $$enabled=="false" then {type:"None"} else error("invalid GC enable flag") end),parameters:{delete_untagged:false,dry_run:false,workers:1}}')"
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

if [ "$${mode}" = retention ] || [ "$${mode}" = retention-dry-run ]; then
  dry_run=false
  [ "$${mode}" != retention-dry-run ] || dry_run=true
  executions='[]'
  projects="$$(harbor_request GET '/projects?page=1&page_size=100')"
  [ "$$(printf '%s' "$${projects}" | jq 'length')" -lt 100 ] || { echo 'project count exceeds execution bound' >&2;exit 1; }
  for project_id in $$(printf '%s' "$${projects}" | jq -r '.[].project_id'); do
    latest_inventory="$$(resolve_inventory)"
    [ "$${latest_inventory}" = "$${protected_inventory}" ] || { echo 'protection inventory changed; stop' >&2;exit 1; }
    verify_filers >/dev/null
    policy_id="$$(harbor_request GET "/projects/$${project_id}/metadatas/" | jq -er '.retention_id')"
    execution="$$(execute_retention "$${policy_id}" "$${dry_run}")"
    executions="$$(printf '%s' "$${executions}" | jq --argjson execution "$${execution}" '.+[$$execution]')"
  done
  latest_inventory="$$(resolve_inventory)"
  [ "$${latest_inventory}" = "$${protected_inventory}" ] || { echo 'post-retention inventory changed; stop' >&2;exit 1; }
  verify_inventory "$${protected_inventory}" >/dev/null
  filers="$$(verify_filers)"
  evidence="$$(jq -cn --arg hash "$$(inventory_hash "$${protected_inventory}")" --argjson now "$$(date -u +%s)" --argjson filers "$${filers}" --argjson executions "$${executions}" --argjson dry_run "$${dry_run}"     '{schema:1,state:"Success",completed_at:$$now,inventory_sha256:$$hash,filers:$$filers,executions:$$executions,dry_run:$$dry_run}')"
  if [ "$${dry_run}" = false ]; then write_evidence "$${evidence}"; fi
  printf '%s\n' "$${evidence}"
fi
