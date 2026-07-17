#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

readonly TTFB_LIMIT_SECONDS="5"
readonly ENDPOINTS=(
  "https://echo.wcygan.net/"
  "https://cs2plant.nu-sync.net/"
  "https://nu-sync.net/"
  "https://kneadybynaturebakery.com/"
)

check_endpoint() {
    local endpoint="$1"
    local host
    host="${endpoint#https://}"
    host="${host%%/*}"

    dig +time=5 +tries=1 +short "$host" | awk 'NF { found = 1 } END { exit !found }'

    local response status dns tls ttfb tls_verify
    response="$(curl --fail --silent --show-error --location --connect-timeout 10 --max-time 20 --retry 1 --retry-delay 1 --retry-max-time 30 --output /dev/null --write-out '%{http_code} %{time_namelookup} %{time_appconnect} %{time_starttransfer} %{ssl_verify_result}' "$endpoint")"
    read -r status dns tls ttfb tls_verify <<<"$response"
    [[ "$status" =~ ^[23][0-9][0-9]$ ]]
    [[ "$tls_verify" = "0" ]]
    awk -v ttfb="$ttfb" -v limit="$TTFB_LIMIT_SECONDS" 'BEGIN { exit !(ttfb <= limit) }'

    log info "Public endpoint healthy" "endpoint=$endpoint" "dns_seconds=$dns" "tls_seconds=$tls" "tls_verify=$tls_verify" "status=$status" "ttfb_seconds=$ttfb"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf '| %s | yes (%s) | yes (%s; verify=%s) | %s | %s |\n' "$endpoint" "$dns" "$tls" "$tls_verify" "$status" "$ttfb" >>"$GITHUB_STEP_SUMMARY"
    fi
}

main() {
    check_cli awk curl dig
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf '## Public endpoint uptime\n\nBounded curl: 10s connect, 20s total. TTFB gate: ≤ %ss.\n\n| Endpoint | DNS | TLS | HTTP | TTFB (s) |\n| --- | --- | --- | --- | --- |\n' "$TTFB_LIMIT_SECONDS" >>"$GITHUB_STEP_SUMMARY"
    fi

    local endpoint
    for endpoint in "${ENDPOINTS[@]}"; do
        check_endpoint "$endpoint"
    done
}

main "$@"
