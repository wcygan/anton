#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

# macOS ships Bash 3.2, while the shared logger uses Bash 4 associative arrays.
# Keep this operator-facing script usable with the system shell without changing
# the shared helper for every existing script.
if ((BASH_VERSINFO[0] < 4)); then
    function log() {
        local level="${1:-info}"
        shift
        local message="${1:-}"
        shift || true

        printf '%s %-5s %s' \
            "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
            "$(printf '%s' "${level}" | tr '[:lower:]' '[:upper:]')" \
            "${message}"
        if (($# > 0)); then
            printf ' %s' "$@"
        fi
        printf '\n'

        if [[ "${level}" == "error" ]]; then
            exit 1
        fi
    }
fi

umask 077

readonly ROOT_DIR="$(git -C "$(dirname "${0}")" rev-parse --show-toplevel)"
readonly AUDIT_MODE="${1:-cluster}"
readonly AUDIT_TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
readonly AUDIT_ROOT="${ROOT_DIR}/.private/security-audits"
readonly OUTPUT_DIR="${AUDIT_ROOT}/${AUDIT_TIMESTAMP}"

function usage() {
    cat <<'EOF'
Usage: security-audit.sh [cluster|images]

  cluster  Scan cluster configuration and RBAC with Trivy, then the NSA
           framework with Kubescape. This is the default.
  images   Explicitly scan workload images with Trivy.
EOF
}

function assert_agentless_state() {
    local phase="${1}"
    local trivy_namespace
    local scanner_jobs

    if ! trivy_namespace="$(kubectl get namespace trivy-temp --ignore-not-found --output=name)"; then
        log warn "Unable to verify the Trivy temporary namespace" "phase=${phase}"
        return 1
    fi

    if [[ -n "${trivy_namespace}" ]]; then
        log warn "Unexpected Trivy temporary namespace exists" "phase=${phase}" "resource=${trivy_namespace}"
        return 1
    fi

    if ! scanner_jobs="$({ kubectl get jobs --all-namespaces --output=json | jq -r '
        .items[]
        | select(
            (.metadata.namespace == "trivy-temp")
            or (.metadata.name | test("(^|[-])trivy([-]|$)|node-collector"; "i"))
            or any(
                .spec.template.spec.containers[]?;
                (.image // "") | test("aquasecurity/(trivy|node-collector)"; "i")
            )
        )
        | "\(.metadata.namespace)/\(.metadata.name)"
    '; } 2>/dev/null)"; then
        log warn "Unable to verify that scanner Jobs are absent" "phase=${phase}"
        return 1
    fi

    if [[ -n "${scanner_jobs}" ]]; then
        log warn "Unexpected Trivy scanner Jobs exist" "phase=${phase}" "jobs=${scanner_jobs//$'\n'/,}"
        return 1
    fi

    log info "Agentless scan invariant holds" "phase=${phase}"
}

function verify_agentless_state_on_exit() {
    local status=$?
    trap - EXIT

    if ! assert_agentless_state after; then
        status=1
    fi

    exit "${status}"
}

function write_metadata() {
    {
        printf 'started_at=%s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
        printf 'mode=%s\n' "${AUDIT_MODE}"
        printf 'kube_context=%s\n' "$(kubectl config current-context)"
        printf 'trivy_version=%s\n' "$(trivy --version | sed -n '1s/^Version: //p')"
        if [[ "${AUDIT_MODE}" == "cluster" ]]; then
            printf 'kubescape_version=%s\n' "$(kubescape version | sed -n 's/^Your current version is: //p')"
        fi
    } >"${OUTPUT_DIR}/metadata.txt"
}

function run_cluster_audit() {
    log info "Running Trivy configuration and RBAC scan" "output=${OUTPUT_DIR}/trivy-config-rbac.json"
    trivy kubernetes \
        --kubeconfig "${KUBECONFIG}" \
        --disable-node-collector \
        --disable-telemetry \
        --skip-images \
        --scanners misconfig,rbac \
        --format json \
        --output "${OUTPUT_DIR}/trivy-config-rbac.json"

    log info "Running Kubescape NSA framework scan" "output=${OUTPUT_DIR}/kubescape-nsa.json"
    kubescape scan framework nsa \
        --kubeconfig "${KUBECONFIG}" \
        --keep-local \
        --format json \
        --output "${OUTPUT_DIR}/kubescape-nsa.json"
}

function run_image_audit() {
    log info "Running explicit Trivy workload image scan" "output=${OUTPUT_DIR}/trivy-images.json"
    trivy kubernetes \
        --kubeconfig "${KUBECONFIG}" \
        --disable-node-collector \
        --disable-telemetry \
        --scanners vuln \
        --format json \
        --output "${OUTPUT_DIR}/trivy-images.json"
}

case "${AUDIT_MODE}" in
    cluster)
        check_cli jq kubectl kubescape trivy
        ;;
    images)
        check_cli jq kubectl trivy
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

check_env KUBECONFIG

if [[ ! -f "${KUBECONFIG}" ]]; then
    log error "Kubeconfig does not exist" "file=${KUBECONFIG}"
fi

if ! assert_agentless_state before; then
    log error "Refusing to scan while agentless invariants are violated"
fi

trap verify_agentless_state_on_exit EXIT

mkdir -p "${OUTPUT_DIR}"
chmod 700 "${OUTPUT_DIR}"
write_metadata

case "${AUDIT_MODE}" in
    cluster)
        run_cluster_audit
        ;;
    images)
        run_image_audit
        ;;
esac

log info "Security audit completed" "mode=${AUDIT_MODE}" "output=${OUTPUT_DIR}"
