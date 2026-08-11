#!/bin/sh
set -eu

: "$${S3_ENDPOINT:?S3_ENDPOINT is required}"
: "$${ORDINARY_BUCKETS:?ORDINARY_BUCKETS is required}"
: "$${TABLE_BUCKETS:?TABLE_BUCKETS is required}"

created=0
present=0

log() {
  level="$1"
  message="$2"
  shift 2
  printf 'level=%s message="%s"' "$level" "$message"
  while [ "$#" -gt 0 ]; do
    printf ' %s' "$1"
    shift
  done
  printf '\n'
}

valid_bucket_name() {
  bucket="$1"
  length="$${#bucket}"
  if [ "$length" -lt 3 ] || [ "$length" -gt 63 ]; then
    return 1
  fi
  case "$bucket" in
    *[!a-z0-9.-]*|.*|*.|-*|*-|*..*) return 1 ;;
    *) return 0 ;;
  esac
}

table_bucket_arn() {
  bucket="$1"
  aws --endpoint-url="$S3_ENDPOINT" s3tables list-table-buckets \
    --query "tableBuckets[?name=='$bucket'].arn | [0]" \
    --output text
}

assert_ordinary_compatible() {
  bucket="$1"
  if ! valid_bucket_name "$bucket"; then
    log error "invalid bucket intent" "kind=ordinary" "bucket=$bucket" >&2
    return 1
  fi
  arn="$(table_bucket_arn "$bucket")"
  if [ -n "$arn" ] && [ "$arn" != "None" ]; then
    log error "bucket kind collision" "expected=ordinary" "actual=table" "bucket=$bucket" >&2
    return 1
  fi
}

assert_table_compatible() {
  bucket="$1"
  if ! valid_bucket_name "$bucket"; then
    log error "invalid bucket intent" "kind=table" "bucket=$bucket" >&2
    return 1
  fi
  arn="$(table_bucket_arn "$bucket")"
  if [ -n "$arn" ] && [ "$arn" != "None" ]; then
    return 0
  fi
  if aws --endpoint-url="$S3_ENDPOINT" s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    log error "bucket kind collision" "expected=table" "actual=ordinary" "bucket=$bucket" >&2
    return 1
  fi
}

ensure_ordinary_bucket() {
  bucket="$1"
  if ! valid_bucket_name "$bucket"; then
    log error "invalid bucket intent" "kind=ordinary" "bucket=$bucket" >&2
    return 1
  fi

  arn="$(table_bucket_arn "$bucket")"
  if [ -n "$arn" ] && [ "$arn" != "None" ]; then
    log error "bucket kind collision" "expected=ordinary" "actual=table" "bucket=$bucket" >&2
    return 1
  fi

  if aws --endpoint-url="$S3_ENDPOINT" s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    present=$((present + 1))
    log info "bucket present" "kind=ordinary" "bucket=$bucket"
    return 0
  fi

  aws --endpoint-url="$S3_ENDPOINT" s3 mb "s3://$bucket" >/dev/null
  aws --endpoint-url="$S3_ENDPOINT" s3api head-bucket --bucket "$bucket" >/dev/null
  created=$((created + 1))
  log info "bucket created" "kind=ordinary" "bucket=$bucket"
}

ensure_table_bucket() {
  bucket="$1"
  if ! valid_bucket_name "$bucket"; then
    log error "invalid bucket intent" "kind=table" "bucket=$bucket" >&2
    return 1
  fi

  arn="$(table_bucket_arn "$bucket")"
  if [ -n "$arn" ] && [ "$arn" != "None" ]; then
    aws --endpoint-url="$S3_ENDPOINT" s3tables get-table-bucket \
      --table-bucket-arn "$arn" >/dev/null
    present=$((present + 1))
    log info "bucket present" "kind=table" "bucket=$bucket"
    return 0
  fi

  if aws --endpoint-url="$S3_ENDPOINT" s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    log error "bucket kind collision" "expected=table" "actual=ordinary" "bucket=$bucket" >&2
    return 1
  fi

  aws --endpoint-url="$S3_ENDPOINT" s3tables create-table-bucket --name "$bucket" >/dev/null
  arn="$(table_bucket_arn "$bucket")"
  if [ -z "$arn" ] || [ "$arn" = "None" ]; then
    log error "created table bucket was not discoverable" "bucket=$bucket" >&2
    return 1
  fi
  aws --endpoint-url="$S3_ENDPOINT" s3tables get-table-bucket \
    --table-bucket-arn "$arn" >/dev/null
  created=$((created + 1))
  log info "bucket created" "kind=table" "bucket=$bucket"
}

# Fail before interpreting a missing bucket if endpoint access or credentials
# are unhealthy. This keeps connectivity and authorization failures distinct
# from idempotent create behavior.
aws --endpoint-url="$S3_ENDPOINT" s3api list-buckets >/dev/null
aws --endpoint-url="$S3_ENDPOINT" s3tables list-table-buckets >/dev/null

# Refuse every known kind collision before creating anything. The checks are
# repeated by the adapters below to remain safe if state changes mid-run.
for ordinary_bucket in $ORDINARY_BUCKETS; do
  for table_bucket in $TABLE_BUCKETS; do
    if [ "$ordinary_bucket" = "$table_bucket" ]; then
      log error "bucket declared with two kinds" "bucket=$ordinary_bucket" >&2
      exit 1
    fi
  done
done

for bucket in $ORDINARY_BUCKETS; do
  assert_ordinary_compatible "$bucket"
done

for bucket in $TABLE_BUCKETS; do
  assert_table_compatible "$bucket"
done

for bucket in $ORDINARY_BUCKETS; do
  ensure_ordinary_bucket "$bucket"
done

for bucket in $TABLE_BUCKETS; do
  ensure_table_bucket "$bucket"
done

log info "bucket provisioning complete" "created=$created" "present=$present"
