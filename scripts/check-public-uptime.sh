#!/usr/bin/env bash
set -Eeuo pipefail

source "$(dirname "${0}")/lib/common.sh"

readonly TTFB_LIMIT_SECONDS="5"
readonly USER_AGENT="anton-public-uptime/1.0"
readonly MONITOR_HEADER="X-Anton-Uptime-Monitor: github-actions"
# echo.wcygan.net is deliberately excluded: its Cloudflare zone returns 403 to
# GitHub-hosted runners before requests reach the shared echo origin.
readonly ENDPOINTS=(
  "https://echo.nu-sync.net/"
  "https://cs2plant.nu-sync.net/"
  "https://nu-sync.net/"
  "https://kneadybynaturebakery.com/"
)

check_endpoint() {
    local endpoint="$1"
    local host outcome=0
    host="${endpoint#https://}"
    host="${host%%/*}"

    if ! dig +time=5 +tries=1 +short "$host" | awk 'NF { found = 1 } END { exit !found }'; then
        log warn "Public endpoint DNS lookup failed" "endpoint=$endpoint"
        if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
            printf '| %s | no | - | - | - |\n' "$endpoint" >>"$GITHUB_STEP_SUMMARY"
        fi
        return 1
    fi

    local response status dns tls ttfb tls_verify
    if ! response="$(curl --silent --show-error --location --user-agent "$USER_AGENT" --header "$MONITOR_HEADER" --connect-timeout 10 --max-time 20 --retry 1 --retry-delay 1 --retry-max-time 30 --output /dev/null --write-out '%{http_code} %{time_namelookup} %{time_appconnect} %{time_starttransfer} %{ssl_verify_result}' "$endpoint")"; then
        log warn "Public endpoint request failed" "endpoint=$endpoint"
        if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
            printf '| %s | yes | no | request failed | - |\n' "$endpoint" >>"$GITHUB_STEP_SUMMARY"
        fi
        return 1
    fi
    read -r status dns tls ttfb tls_verify <<<"$response"

    log info "Public endpoint response" "endpoint=$endpoint" "dns_seconds=$dns" "tls_seconds=$tls" "tls_verify=$tls_verify" "status=$status" "ttfb_seconds=$ttfb"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf '| %s | yes (%s) | yes (%s; verify=%s) | %s | %s |\n' "$endpoint" "$dns" "$tls" "$tls_verify" "$status" "$ttfb" >>"$GITHUB_STEP_SUMMARY"
    fi

    if [[ ! "$status" =~ ^[23][0-9][0-9]$ ]]; then
        log warn "Public endpoint returned unhealthy HTTP status" "endpoint=$endpoint" "status=$status"
        outcome=1
    fi
    if [[ "$tls_verify" != "0" ]]; then
        log warn "Public endpoint TLS verification failed" "endpoint=$endpoint" "tls_verify=$tls_verify"
        outcome=1
    fi
    if ! awk -v ttfb="$ttfb" -v limit="$TTFB_LIMIT_SECONDS" 'BEGIN { exit !(ttfb <= limit) }'; then
        log warn "Public endpoint exceeded TTFB threshold" "endpoint=$endpoint" "ttfb_seconds=$ttfb" "limit_seconds=$TTFB_LIMIT_SECONDS"
        outcome=1
    fi

    return "$outcome"
}

main() {
    check_cli awk curl dig
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        printf '## Public endpoint uptime\n\nPublic surfaces: `echo.nu-sync.net`, `cs2plant.nu-sync.net`, `nu-sync.net`, and `kneadybynaturebakery.com`. `echo.wcygan.net` is excluded because its Cloudflare zone rejects GitHub-hosted traffic before origin. User-Agent: `%s`. Disclosure header: `%s`. Bounded curl: 10s connect, 20s total. TTFB gate: ≤ %ss.\n\n| Endpoint | DNS | TLS | HTTP | TTFB (s) |\n| --- | --- | --- | --- | --- |\n' "$USER_AGENT" "$MONITOR_HEADER" "$TTFB_LIMIT_SECONDS" >>"$GITHUB_STEP_SUMMARY"
    fi

    local endpoint failed=0
    for endpoint in "${ENDPOINTS[@]}"; do
        if ! check_endpoint "$endpoint"; then
            failed=1
        fi
    done

    if ((failed)); then
        log error "One or more public endpoint checks failed"
    fi
}

main "$@"
