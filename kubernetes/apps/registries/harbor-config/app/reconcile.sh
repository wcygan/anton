#!/bin/sh

set -eu

: "$${HARBOR_API_URL:?HARBOR_API_URL is required}"
: "$${HARBOR_USERNAME:?HARBOR_USERNAME is required}"
: "$${HARBOR_PASSWORD:?HARBOR_PASSWORD is required}"
: "$${HARBOR_RETENTION_CRON:?HARBOR_RETENTION_CRON is required}"
: "$${HARBOR_PROTECTED_TAGS:?HARBOR_PROTECTED_TAGS is required}"

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
            params: {latestPushedK: 3},
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
