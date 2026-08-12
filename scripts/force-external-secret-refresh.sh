#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

namespace="${1:-}"
external_secret="${2:-}"

check_cli date kubectl mise python3

if [[ ! "${namespace}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    log error "Namespace must use a Kubernetes DNS label" "namespace=${namespace}"
fi
if [[ ! "${external_secret}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
    log error "ExternalSecret must use a Kubernetes DNS label" "name=${external_secret}"
fi

command_text="mise exec -- kubectl -n ${namespace} annotate externalsecret ${external_secret} force-sync=manual --overwrite"
python3 scripts/cluster-targets.py preflight --command "${command_text}"
mise exec -- kubectl -n "${namespace}" get externalsecret "${external_secret}" -o name >/dev/null

refresh_id="$(date -u +%s)"
mise exec -- kubectl -n "${namespace}" annotate externalsecret "${external_secret}" \
    "force-sync=${refresh_id}" --overwrite
log info "Requested ExternalSecret refresh" "namespace=${namespace}" "name=${external_secret}"
