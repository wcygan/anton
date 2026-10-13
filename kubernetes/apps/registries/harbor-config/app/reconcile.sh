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

harbor_request() {
  method="$${1}"
  path="$${2}"
  payload="$${3:-}"

  if [ -n "$${payload}" ]; then
    curl \
      --fail \
      --silent \
      --show-error \
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
    --retry 5 \
    --retry-delay 5 \
    --retry-connrefused \
    --user "$${auth}" \
    --request "$${method}" \
    "$${api_url}$${path}"
}

if [ "$${MODE:-reconcile}" = gc-dry-run ]; then
  harbor_request POST /system/gc/schedule '{"schedule":{"type":"Manual"},"parameters":{"dry_run":true,"delete_untagged":false,"workers":1}}' >/dev/null
  echo "submitted garbage collection dry run"
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
if [ "$$(printf '%s' "$${current_gc}" | jq -r '.schedule.cron // ""')" != "$${HARBOR_GC_CRON}" ]; then
  harbor_request PUT /system/gc/schedule "$${desired_gc}" >/dev/null
  echo "updated weekly garbage collection schedule"
fi
