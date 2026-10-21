#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${0}")/../../lib/common.sh"

check_cli git go

readonly seaweedfs_revision="875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa"
readonly fixture_dir="$(cd "$(dirname "${0}")" && pwd)"
readonly scratch_dir="$(mktemp -d "${TMPDIR:-/tmp}/anton-seaweedfs-recovery.XXXXXX")"
trap 'rm -rf "${scratch_dir}"' EXIT

log info "Cloning pinned SeaweedFS source" "revision=${seaweedfs_revision}"
git clone --quiet --filter=blob:none --no-checkout https://github.com/seaweedfs/seaweedfs.git "${scratch_dir}/seaweedfs"
git -C "${scratch_dir}/seaweedfs" checkout --quiet "${seaweedfs_revision}"

actual_revision="$(git -C "${scratch_dir}/seaweedfs" rev-parse HEAD)"
if [[ "${actual_revision}" != "${seaweedfs_revision}" ]]; then
    log error "SeaweedFS checkout does not match pinned revision" "expected=${seaweedfs_revision}" "actual=${actual_revision}"
fi

cp "${fixture_dir}/stale_address_repro_test.go" "${scratch_dir}/seaweedfs/weed/filer/stale_address_repro_test.go"
log info "Running deterministic stale-address comparison" "revision=${actual_revision}"
(cd "${scratch_dir}/seaweedfs" && go test -v ./weed/filer -run 'Test(PodIPAddressDoesNotRecoverAfterReplacement|StableVolumeHostnameReconnectsToReplacementAddress)$' -count=1 -timeout=10s)
