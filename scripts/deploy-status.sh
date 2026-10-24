#!/usr/bin/env bash
# Show whether main has reached the cluster: main, the deploy branch, the latest
# Deploy Gate run on main, and the revision Flux has fetched. Read-only apart
# from fetching main and deploy.
set -Eeuo pipefail
source "$(dirname "${0}")/lib/common.sh"

check_cli git gh

git fetch --quiet origin main
main="$(git rev-parse refs/remotes/origin/main)"
printf '%-8s %s  %s\n' main "${main:0:12}" "$(git log -1 --format=%s "${main}")"

deploy=""
if git fetch --quiet origin deploy 2>/dev/null; then
    deploy="$(git rev-parse refs/remotes/origin/deploy)"
    if ! git merge-base --is-ancestor "${deploy}" "${main}"; then
        state="DIVERGED: deploy has commits that are not on main; promotion is stopped"
    else
        behind="$(git rev-list --count "${deploy}..${main}")"
        state="${behind} commit(s) behind main"
    fi
    printf '%-8s %s  %s\n' deploy "${deploy:0:12}" "${state}"
else
    printf '%-8s %s\n' deploy "absent: the first passing gate run on main creates it"
fi

run="$(gh run list --workflow deploy-gate.yaml --branch main --limit 1 \
    --json headSha,status,conclusion,url \
    --jq '(.[0] // empty) | "\(.headSha[0:12])  \(.status) \(.conclusion)  \(.url)"' 2>/dev/null || true)"
printf '%-8s %s\n' gate "${run:-no runs found}"

revision=""
if command -v kubectl >/dev/null 2>&1; then
    revision="$(kubectl --request-timeout=10s -n flux-system get gitrepository flux-system \
        -o jsonpath='{.status.artifact.revision}' 2>/dev/null || true)"
fi
if [[ -z "${revision}" ]]; then
    printf '%-8s %s\n' cluster "unknown (no cluster access)"
    exit 0
fi
sha="${revision##*:}"
at=""
if [[ -n "${deploy}" && "${sha}" == "${deploy}" ]]; then
    at="deploy"
fi
if [[ "${sha}" == "${main}" ]]; then
    at="${at:+${at} and }main"
fi
printf '%-8s %s  %s\n' cluster "${revision}" "${at:+(at ${at})}"
if [[ -z "${at}" ]]; then
    printf '%-8s %s\n' "" "Flux has not fetched the newest commit on the branch it tracks yet"
fi
