#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

# The generated talosconfig contains the nodes' LAN addresses. Those are not
# reachable from an off-LAN operator shell, so this wrapper deliberately uses
# the persistent Tailscale addresses instead. Override the mapping when a
# Tailscale address changes:
#   TALOS_TAILSCALE_NODES='k8s-1=100.x.x.x,k8s-2=100.x.x.x,k8s-3=100.x.x.x'
readonly DEFAULT_TAILSCALE_NODES='k8s-1=100.75.61.79,k8s-2=100.87.89.3,k8s-3=100.100.217.100'
readonly TAILSCALE_NODE_SPEC="${TALOS_TAILSCALE_NODES:-${DEFAULT_TAILSCALE_NODES}}"

check_env TALOSCONFIG KUBECONFIG
check_cli mise kubectl

declare -a node_specs=()
declare -a reachable_nodes=()
declare -a failed_nodes=()

IFS=',' read -r -a node_specs <<<"${TAILSCALE_NODE_SPEC}"

if [[ "${#node_specs[@]}" -ne 3 ]]; then
    log error "Expected exactly three Tailscale node mappings" "value=${TAILSCALE_NODE_SPEC}"
fi

function talos() {
    mise exec -- talosctl --talosconfig "${TALOSCONFIG}" "$@"
}

function node_name() {
    printf '%s' "${1%%=*}"
}

function node_ip() {
    printf '%s' "${1#*=}"
}

function validate_node_specs() {
    local spec
    local name
    local ip
    local k8s1_count=0
    local k8s2_count=0
    local k8s3_count=0

    for spec in "${node_specs[@]}"; do
        name="$(node_name "${spec}")"
        ip="$(node_ip "${spec}")"
        if [[ -z "${name}" || -z "${ip}" || "${name}" == "${ip}" ]]; then
            log error "Invalid Tailscale node mapping" "mapping=${spec}"
        fi

        case "${name}" in
            k8s-1) k8s1_count=$((k8s1_count + 1)) ;;
            k8s-2) k8s2_count=$((k8s2_count + 1)) ;;
            k8s-3) k8s3_count=$((k8s3_count + 1)) ;;
            *) log error "Unexpected Talos node label" "node=${name}" ;;
        esac
    done

    if [[ "${k8s1_count}" -ne 1 || "${k8s2_count}" -ne 1 || "${k8s3_count}" -ne 1 ]]; then
        log error "Tailscale mapping must contain k8s-1, k8s-2, and k8s-3 exactly once" "value=${TAILSCALE_NODE_SPEC}"
    fi
}

function check_tailscale_endpoint() {
    local spec="$1"
    local name
    local ip
    local version_output

    name="$(node_name "${spec}")"
    ip="$(node_ip "${spec}")"

    if [[ -z "${name}" || -z "${ip}" || "${name}" == "${ip}" ]]; then
        log warn "Invalid Tailscale node mapping" "mapping=${spec}"
        failed_nodes+=("${spec}")
        return 0
    fi

    if version_output="$(talos version --endpoints "${ip}" --nodes "${ip}" 2>&1)"; then
        reachable_nodes+=("${spec}")
        log info "Talos endpoint reachable over Tailscale" "node=${name}" "endpoint=${ip}"
        printf '%s\n' "${version_output}" | awk '/^Server:/{getline; print}' | sed 's/^[[:space:]]*/  /'
    else
        failed_nodes+=("${spec}")
        log warn "Talos endpoint failed over Tailscale" "node=${name}" "endpoint=${ip}"
        printf '%s\n' "${version_output}" >&2
    fi
}

validate_node_specs

for spec in "${node_specs[@]}"; do
    check_tailscale_endpoint "${spec}"
done

if [[ "${#reachable_nodes[@]}" -eq 0 ]]; then
    log error "No Talos nodes are reachable over Tailscale"
fi

health_ok=1
for spec in "${reachable_nodes[@]}"; do
    ip="$(node_ip "${spec}")"
    log info "Running server-side Talos health check" "endpoint=${ip}"
    if talos health --endpoints "${ip}" --nodes "${ip}" --wait-timeout "${TALOS_HEALTH_TIMEOUT:-20s}"; then
        health_ok=0
        break
    fi
    log warn "Talos health endpoint did not complete" "endpoint=${ip}"
done

if [[ "${health_ok}" -ne 0 ]]; then
    log error "Talos health check failed through every reachable Tailscale endpoint"
fi

log info "Checking Kubernetes node readiness through the Tailscale operator proxy"
kubectl get nodes -o wide

if [[ "${#failed_nodes[@]}" -gt 0 ]]; then
    log error "One or more Talos Tailscale endpoints failed" "nodes=${failed_nodes[*]}"
fi

log info "Talos and Kubernetes health checks completed"
