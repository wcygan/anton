#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${0}")/../../lib/common.sh"

check_cli docker sha256sum python3 rg
docker compose version >/dev/null

version="4.40"
if (( $# != 0 )); then
    if (( $# != 2 )) || [[ "$1" != "--version" ]]; then
        log error "Usage: run.sh [--version 4.40|4.48]"
    fi
    version="$2"
fi
case "${version}" in
    4.40)
        revision="875cd1f67ea25e8965a4f5ba1e6aaf501ba6b6fa"
        image="chrislusf/seaweedfs@sha256:52194fba4fecd0083c842158b3a902ba6e04a63619b2b0efcd08007bdb6a4602"
        ;;
    4.48)
        revision="530be3e37337488ecc34d58441e0bc476e121c93"
        image="chrislusf/seaweedfs@sha256:4e61d15fd35994cb1e43e1e553dff106794841fd9a99ade2fc8c8bfce4d7872d"
        ;;
    *)
        log error "Unsupported SeaweedFS version" "version=${version}" "allowed=4.40,4.48"
        ;;
esac
readonly version revision image
export SEAWEEDFS_IMAGE="${image}"
readonly python_image="docker.io/library/python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72"
readonly grpcurl_image="docker.io/fullstorydev/grpcurl@sha256:085e183ca334eb4e81ca81ee12cbb2b2737505d1d77f5e33dabc5d066593d998"
readonly scratch_dir="$(mktemp -d "${TMPDIR:-/tmp}/anton-seaweed-maintenance.XXXXXX")"
readonly project="seaweed-maintenance-$$"
cleanup() {
    local status=$?
    local cleanup_failed=0
    if (( status != 0 )); then
        for replication in 000 001; do
            export REPLICATION="${replication}" CONFIG_FILE="${scratch_dir}/s3-${replication}.json"
            docker compose -p "${project}-${replication}" -f "${scratch_dir}/compose.yaml" logs --no-color s3 >&2 2>/dev/null || true
        done
    fi
    for replication in 000 001; do
        export REPLICATION="${replication}" CONFIG_FILE="${scratch_dir}/s3-${replication}.json"
        if [[ -f "${scratch_dir}/compose.yaml" ]]; then
            if ! docker compose -p "${project}-${replication}" -f "${scratch_dir}/compose.yaml" down --volumes --remove-orphans >/dev/null 2>&1; then
                cleanup_failed=1
            fi
            if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=${project}-${replication}")" || -n "$(docker volume ls -q --filter "label=com.docker.compose.project=${project}-${replication}")" || -n "$(docker network ls -q --filter "label=com.docker.compose.project=${project}-${replication}")" ]]; then
                cleanup_failed=1
            fi
        fi
    done
    rm -rf "${scratch_dir}"
    if (( cleanup_failed == 1 )); then
        log error "Fixture cleanup did not remove all of its containers, volumes, and networks" "project=${project}"
        status=1
    fi
    return "${status}"
}
trap cleanup EXIT

actual_version_output="$(docker run --rm "${image}" version 2>/dev/null)"
actual_version="$(printf '%s\n' "${actual_version_output}" | awk '$1 == "version" {print $3}')"
actual_revision="$(printf '%s\n' "${actual_version_output}" | awk '$1 == "version" {print $4}')"
if [[ "${actual_version}" != "${version}" || -z "${actual_revision}" || "${revision}" != "${actual_revision}"* ]]; then
    log error "SeaweedFS image does not match the selected version and pinned revision" "expected_version=${version}" "actual_version=${actual_version}" "expected_revision_prefix=${revision}" "actual_revision=${actual_revision}"
fi

cat >"${scratch_dir}/compose.yaml" <<'YAML'
services:
  master:
    image: ${SEAWEEDFS_IMAGE}
    command: ["master", "-ip=master", "-ip.bind=0.0.0.0", "-mdir=/data", "-defaultReplication=${REPLICATION}", "-volumeSizeLimitMB=8", "-metricsPort=0"]
    environment:
      WEED_MASTER_VOLUME_GROWTH_COPY_1: "1"
      WEED_MASTER_VOLUME_GROWTH_COPY_2: "1"
    volumes: ["master:/data"]
  filer:
    image: ${SEAWEEDFS_IMAGE}
    command: ["filer", "-master=master:9333", "-ip=filer", "-ip.bind=0.0.0.0", "-metricsPort=0"]
    depends_on: [master]
  s3:
    image: ${SEAWEEDFS_IMAGE}
    command: ["s3", "-filer=filer:8888", "-ip.bind=0.0.0.0", "-port=8333", "-port.iceberg=0", "-metricsPort=0", "-iam=false", "-config=/etc/sw/s3.json"]
    volumes: ["${CONFIG_FILE}:/etc/sw/s3.json:ro"]
    depends_on: [filer]
  volume-a:
    image: ${SEAWEEDFS_IMAGE}
    command: ["volume", "-dir=/data", "-max=20", "-mserver=master:9333", "-ip=volume-a", "-ip.bind=0.0.0.0", "-rack=default", "-port=8080"]
    volumes: ["volume-a:/data"]
    depends_on: [master]
  volume-b:
    image: ${SEAWEEDFS_IMAGE}
    command: ["volume", "-dir=/data", "-max=20", "-mserver=master:9333", "-ip=volume-b", "-ip.bind=0.0.0.0", "-rack=default", "-port=8080"]
    volumes: ["volume-b:/data"]
    depends_on: [master]
  volume-c:
    image: ${SEAWEEDFS_IMAGE}
    command: ["volume", "-dir=/data", "-max=20", "-mserver=master:9333", "-ip=volume-c", "-ip.bind=0.0.0.0", "-rack=default", "-port=8080"]
    volumes: ["volume-c:/data"]
    depends_on: [master]
volumes:
  master:
  volume-a:
  volume-b:
  volume-c:
networks:
  default:
    internal: true
YAML

readonly payload="${scratch_dir}/payload.bin"
dd if=/dev/urandom of="${payload}" bs=1M count=1 status=none
readonly expected_digest="$(sha256sum "${payload}" | awk '{print $1}')"

client() {
    local case_project="$1" operation="$2" key="$3"
    docker run --rm -i --platform linux/amd64 --network "${case_project}_default" -v "${payload}:/payload:ro" "${python_image}" python - "${operation}" "${key}" <<'PY'
import datetime, hashlib, hmac, json, sys, time, urllib.error, urllib.request

operation, key = sys.argv[1:]
access, secret, region, service = "fixture", "fixture-secret", "us-east-1", "s3"
host = "s3:8333"
if operation == "READY":
    try:
        urllib.request.urlopen("http://" + host + "/", timeout=2).read()
    except urllib.error.HTTPError:
        pass
    print("ready")
    sys.exit(0)
if operation == "LOOKUP":
    with urllib.request.urlopen(f"http://master:9333/dir/lookup?volumeId={key}", timeout=5) as response:
        print(json.dumps(json.load(response), sort_keys=True))
    sys.exit(0)
if operation == "STATUS":
    with urllib.request.urlopen("http://master:9333/dir/status", timeout=5) as response:
        print(json.dumps(json.load(response), sort_keys=True))
    sys.exit(0)
if operation == "OWNERS":
    metadata_url = "http://filer:8888/buckets/maintenance-proof/" + key + "?metadata=true"
    with urllib.request.urlopen(metadata_url, timeout=5) as response:
        metadata = json.load(response)
    owners = []
    for chunk in metadata.get("chunks", []):
        volume_id = chunk["file_id"].split(",", 1)[0]
        with urllib.request.urlopen(f"http://master:9333/dir/lookup?volumeId={volume_id}", timeout=5) as response:
            lookup = json.load(response)
        owners.append({"file_id": chunk["file_id"], "volume_id": volume_id, "locations": lookup.get("locations", [])})
    print(json.dumps(owners, sort_keys=True))
    sys.exit(0)
path = "/maintenance-proof/" + key
bucket_create = False
if operation == "CREATE_BUCKET":
    path = "/maintenance-proof"
    operation = "PUT"
    bucket_create = True
body = open("/payload", "rb").read() if operation == "PUT" and not bucket_create else b""
payload_hash = hashlib.sha256(body).hexdigest()
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
date = now[:8]
canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{now}\n"
signed_headers = "host;x-amz-content-sha256;x-amz-date"
canonical_request = "\n".join((operation, path, "", canonical_headers, signed_headers, payload_hash))
scope = f"{date}/{region}/{service}/aws4_request"
string_to_sign = "\n".join(("AWS4-HMAC-SHA256", now, scope, hashlib.sha256(canonical_request.encode()).hexdigest()))
def sign(key, value): return hmac.new(key, value.encode(), hashlib.sha256).digest()
signing_key = sign(sign(sign(sign(("AWS4" + secret).encode(), date), region), service), "aws4_request")
signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
authorization = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
request = urllib.request.Request("http://" + host + path, data=body if operation == "PUT" else None, method=operation, headers={"Host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": now, "Authorization": authorization})
try:
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=10) as response:
        data = response.read()
        elapsed = time.monotonic() - started
        if operation == "GET":
            digest = hashlib.sha256(data).hexdigest()
            print(f"status={response.status} bytes={len(data)} sha256={digest} elapsed_s={elapsed:.3f}")
        else:
            print(f"status={response.status} elapsed_s={elapsed:.3f}")
except urllib.error.HTTPError as exc:
    print(f"http_status={exc.code} body={exc.read().decode(errors='replace')[:500]} elapsed_s={time.monotonic() - started:.3f}", file=sys.stderr)
    sys.exit(1)
except (urllib.error.URLError, TimeoutError) as exc:
    print(f"request_failed={exc} elapsed_s={time.monotonic() - started:.3f}", file=sys.stderr)
    sys.exit(1)
PY
}

exercise_outages() {
    local case_project="$1" policy="$2" owner_list="$3" first_cold_index="$4" replica_count="$5"
    local outage_index=0 owner cold_key cold_owners cold_owner_list chunk_count copy_count warm_result cold_result put_result fresh_result recovered recover_deadline result
    for owner in ${owner_list}; do
        outage_index=$((outage_index + 1))
        cold_key="cold-$((first_cold_index + outage_index - 1)).bin"
        cold_owners="$(client "${case_project}" OWNERS "${cold_key}")"
        local warm_owners
        warm_owners="$(client "${case_project}" OWNERS warm.bin)"
        python3 - "${warm_owners}" "${cold_owners}" <<'PY'
import json, sys
warm, cold = (json.loads(value) for value in sys.argv[1:])
if len(warm) != 1 or len(cold) != 1:
    raise SystemExit("Warm and cold controls must each have exactly one chunk")
if warm[0]["volume_id"] != cold[0]["volume_id"]:
    raise SystemExit("Warm and cold controls must exercise the same volume")
if warm[0]["file_id"] == cold[0]["file_id"]:
    raise SystemExit("Warm and cold controls must have different file IDs")
print(f'same_volume_controls=true vid={cold[0]["volume_id"]} warm_fid={warm[0]["file_id"]} cold_fid={cold[0]["file_id"]}')
PY
        printf 'withdrawal_object=%s chunk_owners=%s\n' "${cold_key}" "${cold_owners}"
        chunk_count="$(printf '%s' "${cold_owners}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
        [[ "${chunk_count}" == "1" ]] || log error "Expected one chunk for the withdrawal object" "object=${cold_key}" "chunks=${chunk_count}"
        copy_count="$(printf '%s' "${cold_owners}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]["locations"]))')"
        [[ "${copy_count}" == "${replica_count}" ]] || log error "Withdrawal object copy count differs from expected" "object=${cold_key}" "copies=${copy_count}" "expected=${replica_count}"
        cold_owner_list="$(printf '%s' "${cold_owners}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(" ".join(dict.fromkeys(location["url"].split(":")[0] for item in data for location in item["locations"])))')"
        [[ " ${cold_owner_list} " == *" ${owner} "* ]] || log error "Withdrawal target does not own this exact cold object" "object=${cold_key}" "server=${owner}" "owners=${cold_owner_list}"

        if [[ "${policy}" == "001" ]]; then
            refresh_gateways "${case_project}" "${cold_key}" "${owner}"
        fi
        docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" stop --timeout 1 "${owner}" >/dev/null
        warm_result="$(client "${case_project}" GET warm.bin 2>&1)" || true
        cold_result="$(client "${case_project}" GET "${cold_key}" 2>&1)" || true
        local fresh_key="fresh-during-${owner}-${policy}.bin" fresh_owners fresh_owner_count fresh_owner_list
        put_result="$(client "${case_project}" PUT "${fresh_key}" 2>&1)" || true
        if [[ "${put_result}" == *"status=200"* ]]; then
            fresh_result="$(client "${case_project}" GET "${fresh_key}" 2>&1)" || true
            fresh_owners="$(client "${case_project}" OWNERS "${fresh_key}")"
            fresh_owner_count="$(printf '%s' "${fresh_owners}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]["locations"]))')"
            fresh_owner_list="$(printf '%s' "${fresh_owners}" | python3 -c 'import json,sys; print(" ".join(dict.fromkeys(location["url"].split(":")[0] for location in json.load(sys.stdin)[0]["locations"])))')"
        else
            fresh_result="not_read_because_put_failed"
            fresh_owners="[]"
            fresh_owner_count=0
            fresh_owner_list=""
        fi
        printf 'policy=%s after_withdrawal=%s warm_GET={%s} cold_GET={%s} fresh_PUT={%s} fresh_GET={%s} fresh_chunk_owners=%s\n' "${policy}" "${owner}" "${warm_result}" "${cold_result}" "${put_result}" "${fresh_result}" "${fresh_owners}"
        for result in "${warm_result}" "${fresh_result}"; do
            [[ "${result}" != *"sha256="* || "${result}" == *"sha256=${expected_digest}"* ]] || log error "S3 returned bytes with an unexpected digest" "policy=${policy}" "server=${owner}" "result=${result}"
        done
        if [[ "${policy}" == "001" ]]; then
            [[ "${warm_result}" == *"sha256=${expected_digest}"* ]] || log error "Replicated warm object read did not return the expected bytes" "server=${owner}" "result=${warm_result}"
        fi
        [[ "${put_result}" == *"status=200"* && "${fresh_result}" == *"sha256=${expected_digest}"* ]] || log error "Fresh S3 PUT+GET did not preserve exact bytes" "policy=${policy}" "server=${owner}"
        [[ "${fresh_owner_count}" == "${replica_count}" ]] || log error "Fresh S3 write did not create the expected number of copies" "policy=${policy}" "server=${owner}" "owners=${fresh_owners}" "expected=${replica_count}"
        [[ " ${fresh_owner_list} " != *" ${owner} "* ]] || log error "Fresh S3 write unexpectedly depends on the withdrawn volume server" "policy=${policy}" "server=${owner}" "owners=${fresh_owners}"
        if [[ "${policy}" == "001" && "${cold_result}" != *"sha256=${expected_digest}"* ]]; then log error "Replicated cold GET failed during a volume-server withdrawal" "server=${owner}" "result=${cold_result}"; fi
        if [[ "${policy}" == "000" && "${cold_result}" == *"sha256=${expected_digest}"* ]]; then log error "Unreplicated cold GET unexpectedly passed after its owner was withdrawn" "server=${owner}"; fi

        docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" start "${owner}" >/dev/null
        recovered=0
        recover_deadline=$((SECONDS + 30))
        while (( SECONDS < recover_deadline )); do
            if client "${case_project}" OWNERS "${cold_key}" 2>/dev/null | rg -q "${owner}:8080"; then recovered=1; break; fi
            sleep 1
        done
        (( recovered == 1 )) || log error "Volume server did not rejoin before recovery deadline" "policy=${policy}" "server=${owner}"
        if [[ "${policy}" == "001" ]]; then
            wait_filer_two_locations "${case_project}" "${cold_key}" "${owner}-recovered"
        fi
    done
}

migrate_existing_volume() {
    local case_project="$1" volume_id="$2" original_file_id="$3" owner_list="$4" source target
    local configure="volume.configure.replication -volumeId=${volume_id} -replication=001"
    local mark_source_readonly mark_source_writable mark_target_writable
    source="${owner_list%% *}"
    target=""
    for candidate in volume-a volume-b volume-c; do
        if [[ " ${owner_list} " != *" ${candidate} "* ]]; then target="${candidate}"; break; fi
    done
    [[ -n "${source}" && -n "${target}" ]] || log error "Could not identify an unowned target server for exact-volume copy" "owners=${owner_list}"

    local source_before target_before source_after target_after copy_result command_result readonly_status source_vif_ro target_vif_ro lookup lookup_ready writable_status
    source_before="$(volume_file_hashes "${case_project}" "${source}" "${volume_id}")"
    target_before="$(volume_file_hashes "${case_project}" "${target}" "${volume_id}")"
    [[ "${source_before}" != "{}" && "${target_before}" == "{}" ]] || log error "Copy preflight requires source files and an empty target volume slot" "source=${source}" "target=${target}" "source_files=${source_before}" "target_files=${target_before}"
    printf 'migration_preflight volume=%s source=%s target=%s source_before=%s target_before=%s\n' "${volume_id}" "${source}" "${target}" "${source_before}" "${target_before}"

    # Quiesce all file APIs before marking and copying this exact volume.
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" stop --timeout 1 s3 >/dev/null
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" stop --timeout 1 filer >/dev/null
    # Planned maintenance starts from the production target default. Keep the
    # master data volume, but restart the process with default replication 001.
    export REPLICATION=001
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" up -d --no-deps --force-recreate --wait --wait-timeout 60 master >/dev/null
    local master_deadline=$((SECONDS + 30)) master_ready=0
    while (( SECONDS < master_deadline )); do
        if docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" exec -T master weed shell -master=localhost:9333 <<<"volume.list -v=5" >/dev/null 2>&1; then master_ready=1; break; fi
        sleep 1
    done
    (( master_ready == 1 )) || log error "Master did not recover after switching default replication to 001" "volume_id=${volume_id}"
    printf 'migration_default_replication=001 master_data_volume_retained=true\n'
    mark_source_readonly="volume.mark -node=${source}:8080 -volumeId=${volume_id} -readonly"
    command_result="$(printf 'lock\n%s\nunlock\n' "${mark_source_readonly}" | docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" exec -T master weed shell -master=localhost:9333 2>&1)" || log error "Could not mark source read-only under the master lock" "volume_id=${volume_id}" "result=${command_result}"
    source_vif_ro="$(volume_vif_readonly "${case_project}" "${source}" "${volume_id}")"
    [[ "${source_vif_ro}" == "true" ]] || log error "Source .vif did not persist the read-only marker before restart" "vif=${source_vif_ro}"
    printf 'migration_readonly_marked=source_vif=%s\n' "${source_vif_ro}"
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" restart "${source}" >/dev/null
    local readonly_deadline=$((SECONDS + 30)) readonly_ready=0
    while (( SECONDS < readonly_deadline )); do
        source_vif_ro="$(volume_vif_readonly "${case_project}" "${source}" "${volume_id}" 2>/dev/null || true)"
        readonly_status="$(volume_list_status "${case_project}" readonly "${volume_id}" 2>/dev/null || true)"
        if [[ "${source_vif_ro}" == "true" && "${readonly_status}" == *"ReadOnly:true"* ]]; then readonly_ready=1; break; fi
        sleep 1
    done
    (( readonly_ready == 1 )) || log error "Read-only marker did not persist in source .vif and master after restart" "vif=${source_vif_ro}" "master=${readonly_status}"
    printf 'migration_readonly_after_restart=source_vif=%s master=%s\n' "${source_vif_ro}" "${readonly_status}"

    source_before="$(volume_file_hashes "${case_project}" "${source}" "${volume_id}")"
    printf 'migration_source_before_copy=%s\n' "${source_before}"
    copy_result="$(printf 'lock\n%s\nvolume.copy -volumeId=%s -source=%s:8080 -target=%s:8080\nunlock\n' "${configure}" "${volume_id}" "${source}" "${target}" | docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" exec -T master weed shell -master=localhost:9333 2>&1)" || log error "Exact volume copy command failed" "volume_id=${volume_id}" "result=${copy_result}"
    printf 'migration_copy=%s\n' "${copy_result}"
    [[ "${copy_result}" != *"Error:"* && "${copy_result}" != *"error:"* ]] || log error "Exact volume copy command failed" "volume_id=${volume_id}" "result=${copy_result}"
    source_after="$(volume_file_hashes "${case_project}" "${source}" "${volume_id}")"
    target_after="$(volume_file_hashes "${case_project}" "${target}" "${volume_id}")"
    [[ "${target_after}" == "${source_after}" ]] || log error "Copied .dat/.idx/.vif files differ from source" "volume_id=${volume_id}" "source_files=${source_after}" "target_files=${target_after}"
    printf 'migration_file_hashes_match=true volume=%s source_after=%s target_after=%s\n' "${volume_id}" "${source_after}" "${target_after}"
    source_vif_ro="$(volume_vif_readonly "${case_project}" "${source}" "${volume_id}")"
    target_vif_ro="$(volume_vif_readonly "${case_project}" "${target}" "${volume_id}")"
    [[ "${source_vif_ro}" == "true" && "${target_vif_ro}" == "true" ]] || log error "Both copies must remain read-only until their hashes match" "source_vif=${source_vif_ro}" "target_vif=${target_vif_ro}"

    local post_deadline=$((SECONDS + 30)) post_migration="" post_ready=0
    while (( SECONDS < post_deadline )); do
        lookup="$(client "${case_project}" LOOKUP "${volume_id}" 2>/dev/null || true)"
        if [[ "${lookup}" == *"${source}:8080"* && "${lookup}" == *"${target}:8080"* ]]; then post_ready=1; break; fi
        sleep 1
    done
    (( post_ready == 1 )) || log error "Master did not register both copied volume owners before deadline" "volume_id=${volume_id}" "lookup=${lookup}"
    printf 'migration_readonly_after_copy=source_vif=%s target_vif=%s lookup=%s\n' "${source_vif_ro}" "${target_vif_ro}" "${lookup}"
    mark_source_writable="volume.mark -node=${source}:8080 -volumeId=${volume_id} -writable"
    mark_target_writable="volume.mark -node=${target}:8080 -volumeId=${volume_id} -writable"
    command_result="$(printf 'lock\n%s\n%s\nunlock\n' "${mark_source_writable}" "${mark_target_writable}" | docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" exec -T master weed shell -master=localhost:9333 2>&1)" || log error "Could not reopen both verified replicas" "volume_id=${volume_id}" "result=${command_result}"
    [[ "${command_result}" != *"Error:"* && "${command_result}" != *"error:"* ]] || log error "Master rejected the writable marks" "volume_id=${volume_id}" "result=${command_result}"
    source_vif_ro="$(volume_vif_readonly "${case_project}" "${source}" "${volume_id}")"
    target_vif_ro="$(volume_vif_readonly "${case_project}" "${target}" "${volume_id}")"
    writable_status="$(volume_list_status "${case_project}" writable "${volume_id}")"
    [[ "${source_vif_ro}" == "false" && "${target_vif_ro}" == "false" ]] || log error "Both replicas must be writable before reopening file APIs" "volume_id=${volume_id}" "source_vif_read_only=${source_vif_ro}" "target_vif_read_only=${target_vif_ro}" "command=${command_result}"
    local assignment_deadline=$((SECONDS + 30)) assignment_status="" assignment_ready=0 source_sizes target_sizes source_dat_bytes target_dat_bytes volume_limit_bytes=8388608
    source_sizes="$(volume_file_sizes "${case_project}" "${source}" "${volume_id}")"
    target_sizes="$(volume_file_sizes "${case_project}" "${target}" "${volume_id}")"
    source_dat_bytes="$(printf '%s' "${source_sizes}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((v for k,v in d.items() if k.endswith(".dat")), 0))')"
    target_dat_bytes="$(printf '%s' "${target_sizes}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((v for k,v in d.items() if k.endswith(".dat")), 0))')"
    while (( SECONDS < assignment_deadline )); do
        assignment_status="$(client "${case_project}" STATUS status 2>/dev/null || true)"
        if printf '%s' "${assignment_status}" | python3 -c 'import json,sys; d=json.load(sys.stdin); vid=int(sys.argv[1]); layouts=d["Topology"]["Layouts"]; sys.exit(0 if any(x.get("replication")=="001" and x.get("collection")=="maintenance-proof" and vid in x.get("writables",[]) for x in layouts) else 1)' "${volume_id}" 2>/dev/null; then
            assignment_ready=1
            break
        fi
        sleep 1
    done
    (( source_dat_bytes < volume_limit_bytes && target_dat_bytes < volume_limit_bytes )) || log error "Migrated VID reached the fixture volume size limit" "volume_id=${volume_id}" "source_dat_bytes=${source_dat_bytes}" "target_dat_bytes=${target_dat_bytes}" "volume_limit_bytes=${volume_limit_bytes}"
    (( assignment_ready == 1 )) || log error "Migrated VID was not assigned to a writable 001 layout before the deadline" "volume_id=${volume_id}" "source_vif_read_only=${source_vif_ro}" "target_vif_read_only=${target_vif_ro}" "source_dat_bytes=${source_dat_bytes}" "target_dat_bytes=${target_dat_bytes}" "volume_limit_bytes=${volume_limit_bytes}" "dir_status=${assignment_status}" "volume_list=${writable_status}"
    printf 'migration_writable_after_equality=source_vif_read_only=%s target_vif_read_only=%s master_001_writables_contains_vid=true source_dat_bytes=%s target_dat_bytes=%s volume_limit_bytes=%s dir_status=%s volume_list=%s\n' "${source_vif_ro}" "${target_vif_ro}" "${source_dat_bytes}" "${target_dat_bytes}" "${volume_limit_bytes}" "${assignment_status}" "${writable_status}"
    # Restore filer/S3 only after both replicas are verified writable. The
    # object itself remains unread until its first-owner outage test.
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" start filer >/dev/null
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" start s3 >/dev/null
    local ready_deadline=$((SECONDS + 60)) ready=0
    while (( SECONDS < ready_deadline )); do
        if client "${case_project}" READY health >/dev/null 2>&1; then ready=1; break; fi
        sleep 1
    done
    (( ready == 1 )) || log error "S3 did not become ready after refreshing location cache" "replication=001"
    printf 'migration_gateway_restart=ready\n'
    post_migration="$(client "${case_project}" OWNERS cold-2.bin)"
    printf 'migrated_object_chunk_owners=%s\n' "${post_migration}"
    local migrated_file_id migrated_vid migrated_copy_count migrated_owner_list
    migrated_file_id="$(printf '%s' "${post_migration}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["file_id"])')"
    migrated_vid="$(printf '%s' "${post_migration}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["volume_id"])')"
    migrated_copy_count="$(printf '%s' "${post_migration}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]["locations"]))')"
    migrated_owner_list="$(printf '%s' "${post_migration}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(" ".join(dict.fromkeys(location["url"].split(":")[0] for item in data for location in item["locations"])))')"
    [[ "${migrated_file_id}" == "${original_file_id}" ]] || log error "Migration changed the original file ID" "before=${original_file_id}" "after=${migrated_file_id}"
    [[ "${migrated_vid}" == "${volume_id}" ]] || log error "Migration changed the original volume ID" "expected=${volume_id}" "actual=${migrated_vid}"
    [[ "${migrated_copy_count}" == "2" ]] || log error "Migration did not create exactly two volume-server copies" "copies=${migrated_copy_count}"
    exercise_outages "${case_project}" 001 "${migrated_owner_list}" 2 2
}

volume_file_hashes() {
    local case_project="$1" server="$2" volume_id="$3"
    docker run --rm -i --platform linux/amd64 -v "${case_project}_${server}:/volume:ro" "${python_image}" python - "${volume_id}" <<'PY'
import hashlib, json, pathlib, sys
volume_id = sys.argv[1]
files = {}
paths = list(pathlib.Path('/volume').rglob('*'))
for path in paths:
    if not path.is_file() or path.suffix not in {'.dat', '.idx', '.vif'}:
        continue
    if path.stem == volume_id or path.stem.endswith('_' + volume_id):
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(files, sort_keys=True))
PY
}

volume_file_sizes() {
    local case_project="$1" server="$2" volume_id="$3"
    docker run --rm -i --platform linux/amd64 -v "${case_project}_${server}:/volume:ro" "${python_image}" python - "${volume_id}" <<'PY'
import json, pathlib, sys
volume_id = sys.argv[1]
files = {}
for path in pathlib.Path('/volume').rglob('*'):
    if path.is_file() and path.suffix in {'.dat', '.idx', '.vif'} and (path.stem == volume_id or path.stem.endswith('_' + volume_id)):
        files[path.name] = path.stat().st_size
print(json.dumps(files, sort_keys=True))
PY
}

volume_vif_readonly() {
    local case_project="$1" server="$2" volume_id="$3"
    docker run --rm -i --platform linux/amd64 -v "${case_project}_${server}:/volume:ro" "${python_image}" python - "${volume_id}" <<'PY'
import json, pathlib, sys
volume_id = sys.argv[1]
matches = [path for path in pathlib.Path('/volume').rglob('*.vif') if path.stem == volume_id or path.stem.endswith('_' + volume_id)]
if len(matches) != 1:
    raise SystemExit(f'expected one .vif for volume {volume_id}, found {len(matches)}')
with matches[0].open() as stream:
    info = json.load(stream)
value = info.get('ReadOnly', info.get('readOnly'))
if not isinstance(value, bool):
    raise SystemExit(f'.vif has no boolean ReadOnly field: {info}')
print(str(value).lower())
PY
}

volume_list_status() {
    local case_project="$1" state="$2" volume_id="$3"
    printf 'volume.list -v=5 -%s -volumeId=%s\n' "${state}" "${volume_id}" |
        docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" exec -T master weed shell -master=localhost:9333 2>&1
}

filer_lookup() {
    local case_project="$1" volume_id="$2"
    docker run --rm --network "${case_project}_default" "${grpcurl_image}" \
        -plaintext -format json -d "{\"volumeIds\":[\"${volume_id}\"]}" \
        filer:18888 filer_pb.SeaweedFiler/LookupVolume 2>&1
}

wait_filer_two_locations() {
    local case_project="$1" key="$2" label="$3" owners metadata volume_id lookup deadline=$((SECONDS + 15))
    metadata="$(client "${case_project}" OWNERS "${key}")"
    volume_id="$(printf '%s' "${metadata}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["volume_id"])')"
    while (( SECONDS < deadline )); do
        lookup="$(filer_lookup "${case_project}" "${volume_id}" || true)"
        owners="$(printf '%s' "${lookup}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d.get("locationsMap", {}).get(sys.argv[1], {}).get("locations", [])))' "${volume_id}" 2>/dev/null || true)"
        if [[ "${owners}" == "2" ]]; then
            printf 'filer_lookup_gate=two_locations key=%s volume=%s label=%s response=%s\n' "${key}" "${volume_id}" "${label}" "${lookup}"
            return 0
        fi
        sleep 1
    done
    log error "Filer LookupVolume did not report two live locations before the owner hold" "key=${key}" "volume_id=${volume_id}" "label=${label}" "response=${lookup}"
}

refresh_gateways() {
    local case_project="$1" key="$2" owner="$3" warm_result ready_deadline ready=0
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" restart filer >/dev/null
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" up -d --wait --wait-timeout 60 filer >/dev/null
    wait_filer_two_locations "${case_project}" "${key}" "before-${owner}-withdrawal"
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" restart s3 >/dev/null
    ready_deadline=$((SECONDS + 60))
    while (( SECONDS < ready_deadline )); do
        if client "${case_project}" READY health >/dev/null 2>&1; then ready=1; break; fi
        sleep 1
    done
    (( ready == 1 )) || log error "Filer/S3 did not become ready before planned withdrawal" "server=${owner}"
    warm_result="$(client "${case_project}" GET warm.bin)"
    [[ "${warm_result}" == *"sha256=${expected_digest}"* ]] || log error "Gateway refresh could not read the exact warm object while all owners were healthy" "result=${warm_result}"
    printf 'gateway_refresh=ready key=%s owner=%s warm={%s} filer_two_locations=true s3_fresh_process=true\n' "${key}" "${owner}" "${warm_result}"
}

run_case() {
    local replication="$1"
    local case_project="${project}-${replication}"
    export REPLICATION="${replication}"
    cat >"${scratch_dir}/s3-${replication}.json" <<'JSON'
{"identities":[{"name":"local-fixture-admin","credentials":[{"accessKey":"fixture","secretKey":"fixture-secret"}],"actions":["Admin"]}]}
JSON
    export CONFIG_FILE="${scratch_dir}/s3-${replication}.json"
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" up -d --wait --wait-timeout 60
    local deadline=$((SECONDS + 60)) ready=0
    while (( SECONDS < deadline )); do
        if client "${case_project}" READY health >/dev/null 2>&1; then ready=1; break; fi
        sleep 1
    done
    (( ready == 1 )) || log error "S3 endpoint did not become ready" "replication=${replication}"
    client "${case_project}" CREATE_BUCKET bucket
    client "${case_project}" PUT warm.bin >/dev/null
    client "${case_project}" PUT cold-1.bin >/dev/null
    client "${case_project}" PUT cold-2.bin >/dev/null
    client "${case_project}" PUT cold-3.bin >/dev/null
    local warm_initial
    warm_initial="$(client "${case_project}" GET warm.bin)"
    [[ "${warm_initial}" == *"sha256=${expected_digest}"* ]] || log error "Initial S3 GET did not match uploaded bytes" "replication=${replication}" "result=${warm_initial}"

    local owners
    owners="$(client "${case_project}" OWNERS cold-1.bin)"
    printf 'replication=%s initial_sha256=%s\n' "${replication}" "${expected_digest}"
    printf 'cold_object_chunk_owners=%s\n' "${owners}"
    local chunk_count owner_count
    chunk_count="$(printf '%s' "${owners}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
    [[ "${chunk_count}" == "1" ]] || log error "Expected one chunk for the 1MiB object" "chunks=${chunk_count}"
    owner_count="$(printf '%s' "${owners}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)[0]["locations"]))')"
    if [[ "${replication}" == "000" && "${owner_count}" != "1" ]]; then log error "000 test object did not have exactly one volume-server copy" "owners=${owners}"; fi
    if [[ "${replication}" == "001" && "${owner_count}" != "2" ]]; then log error "001 test object did not have exactly two volume-server copies" "owners=${owners}"; fi
    local owner_list original_file_id original_volume_id
    original_file_id="$(printf '%s' "${owners}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["file_id"])')"
    original_volume_id="$(printf '%s' "${owners}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["volume_id"])')"
    owner_list="$(printf '%s' "${owners}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(" ".join(dict.fromkeys(location["url"].split(":")[0] for item in data for location in item["locations"])))')"
    [[ -n "${owner_list}" ]] || log error "Could not identify a volume server holding test data" "replication=${replication}"
    exercise_outages "${case_project}" "${replication}" "${owner_list}" 1 "${owner_count}"
    if [[ "${replication}" == "000" ]]; then
        local migration_owners migration_file_id migration_volume_id
        migration_owners="$(client "${case_project}" OWNERS cold-2.bin)"
        migration_file_id="$(printf '%s' "${migration_owners}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["file_id"])')"
        migration_volume_id="$(printf '%s' "${migration_owners}" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["volume_id"])')"
        [[ "${migration_volume_id}" == "${original_volume_id}" ]] || log error "Cold objects were allocated to different volume IDs" "cold-1=${original_volume_id}" "cold-2=${migration_volume_id}"
        migrate_existing_volume "${case_project}" "${migration_volume_id}" "${migration_file_id}" "$(printf '%s' "${migration_owners}" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(" ".join(dict.fromkeys(location["url"].split(":")[0] for item in data for location in item["locations"])))')"
    fi
    docker compose -p "${case_project}" -f "${scratch_dir}/compose.yaml" down --volumes --remove-orphans >/dev/null
}

run_case 000
run_case 001
