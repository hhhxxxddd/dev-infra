#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSIONS_FILE="${ROOT_DIR}/versions.env"
ENV_FILE="${ROOT_DIR}/.env"
COMPOSE_FILE="${ROOT_DIR}/compose.yaml"

CORE_SERVICES=(mysql postgres redis kafka)
EXTRA_SERVICES=(s3 mailpit)
ALL_SERVICES=("${CORE_SERVICES[@]}" "${EXTRA_SERVICES[@]}")

ensure_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    echo "已从 .env.example 创建 ${ENV_FILE}"
  fi
}

load_env() {
  [[ "${1:-}" == --read-only ]] || ensure_env
  local preferences_file="${ENV_FILE}"
  [[ -f "${preferences_file}" ]] || preferences_file="${ROOT_DIR}/.env.example"
  set -a
  # shellcheck disable=SC1090
  source "${VERSIONS_FILE}"
  # shellcheck disable=SC1090
  source "${preferences_file}"
  set +a
}

dc() {
  local preferences_file="${ENV_FILE}"
  [[ -f "${preferences_file}" ]] || preferences_file="${ROOT_DIR}/.env.example"
  docker compose \
    --env-file "${VERSIONS_FILE}" \
    --env-file "${preferences_file}" \
    -f "${COMPOSE_FILE}" "$@"
}

dc_all() {
  dc --profile optional "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "未找到 docker。请启动 Docker Desktop，并启用 Ubuntu 的 WSL 集成。" >&2
    exit 1
  }
  docker info >/dev/null 2>&1 || {
    echo "无法连接 Docker Engine。请先启动 Docker Desktop。" >&2
    exit 1
  }
  docker compose version >/dev/null 2>&1 || {
    echo "未找到 Docker Compose。" >&2
    exit 1
  }
}

service_is_known() {
  local expected="$1" candidate
  for candidate in "${ALL_SERVICES[@]}"; do
    [[ "${candidate}" == "${expected}" ]] && return 0
  done
  return 1
}

append_unique() {
  # shellcheck disable=SC2178
  local -n output_ref=$1
  local candidate="$2" current
  for current in "${output_ref[@]}"; do
    [[ "${current}" == "${candidate}" ]] && return 0
  done
  output_ref+=("${candidate}")
}

resolve_services() {
  local output_name=$1
  # shellcheck disable=SC2178
  local -n output_ref=$1
  shift
  local requested=("$@") item candidate
  local expanded=()

  ((${#requested[@]})) || requested=(all)
  output_ref=()

  for item in "${requested[@]}"; do
    case "${item}" in
      all) expanded=("${ALL_SERVICES[@]}") ;;
      core) expanded=("${CORE_SERVICES[@]}") ;;
      extra|optional) expanded=("${EXTRA_SERVICES[@]}") ;;
      *)
        if ! service_is_known "${item}"; then
          echo "未知服务或分组：${item}" >&2
          echo "可用服务：${ALL_SERVICES[*]}；分组：core extra all" >&2
          exit 2
        fi
        expanded=("${item}")
        ;;
    esac
    for candidate in "${expanded[@]}"; do
      append_unique "${output_name}" "${candidate}"
    done
  done
}

ensure_volumes() {
  local services=("$@") service volume
  ((${#services[@]})) || services=("${ALL_SERVICES[@]}")

  for service in "${services[@]}"; do
    case "${service}" in
      mysql) volume="${MYSQL_DATA_VOLUME}" ;;
      postgres) volume="${POSTGRES_DATA_VOLUME}" ;;
      redis) volume="${REDIS_DATA_VOLUME}" ;;
      kafka) volume="${KAFKA_DATA_VOLUME}" ;;
      s3) volume="${S3_DATA_VOLUME}" ;;
      mailpit) volume="${MAILPIT_DATA_VOLUME}" ;;
      *) continue ;;
    esac
    if ! docker volume inspect "${volume}" >/dev/null 2>&1; then
      docker volume create "${volume}" >/dev/null
      echo "已创建数据卷 ${volume}"
    fi
  done
}

is_running() {
  [[ -n "$(dc ps --status running -q "$1" 2>/dev/null)" ]]
}

service_requested() {
  local expected="$1" candidate
  shift
  for candidate in "$@"; do
    [[ "${candidate}" == "${expected}" ]] && return 0
  done
  return 1
}

ensure_s3_bucket() {
  service_requested s3 "$@" || return 0

  echo "正在确认 S3 Bucket：${S3_BUCKET}"
  # Variables in this block are intentionally expanded inside s3-client.
  # shellcheck disable=SC2016
  dc run --rm --no-deps --entrypoint /bin/sh s3-client -eu -c '
    rc alias set local http://s3:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY" \
      --region "$S3_REGION" --bucket-lookup path >/dev/null
    if ! rc ls "local/${S3_BUCKET}/" >/dev/null 2>&1; then
      rc mb "local/${S3_BUCKET}"
    fi
  '
}

service_description() {
  case "$1" in
    mysql) echo "MySQL 关系型数据库" ;;
    postgres) echo "PostgreSQL 关系型数据库" ;;
    redis) echo "Redis 缓存与键值存储" ;;
    kafka) echo "Kafka 事件流与消息平台" ;;
    s3) echo "RustFS S3 兼容对象存储" ;;
    mailpit) echo "Mailpit 开发邮件捕获器" ;;
  esac
}

service_endpoint() {
  case "$1" in
    mysql) echo "${BIND_HOST}:${MYSQL_PORT}" ;;
    postgres) echo "${BIND_HOST}:${POSTGRES_PORT}" ;;
    redis) echo "${BIND_HOST}:${REDIS_PORT}" ;;
    kafka) echo "${KAFKA_ADVERTISED_HOST}:${KAFKA_PORT}" ;;
    s3) echo "http://${BIND_HOST}:${S3_PORT}" ;;
    mailpit) echo "http://${BIND_HOST}:${MAILPIT_UI_PORT}" ;;
  esac
}

service_state() {
  local container_id
  container_id="$(dc ps --all -q "$1" 2>/dev/null | head -n 1)"
  if [[ -z "${container_id}" ]]; then
    echo "未创建"
    return
  fi
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
    "${container_id}" 2>/dev/null || echo "未知"
}

print_service_table() {
  local services=("$@") service
  ((${#services[@]})) || services=("${ALL_SERVICES[@]}")

  printf '%-10s %-12s %-31s %s\n' "服务" "状态" "地址" "用途"
  printf '%-10s %-12s %-31s %s\n' "----------" "------------" "-------------------------------" "------------------------"
  for service in "${services[@]}"; do
    printf '%-10s %-12s %-31s %s\n' \
      "${service}" "$(service_state "${service}")" "$(service_endpoint "${service}")" \
      "$(service_description "${service}")"
  done
}

print_service_catalog() {
  local state="$1"
  shift
  local services=("$@") service
  ((${#services[@]})) || services=("${ALL_SERVICES[@]}")

  printf '%-10s %-12s %-31s %s\n' "服务" "状态" "地址" "用途"
  printf '%-10s %-12s %-31s %s\n' "----------" "------------" "-------------------------------" "------------------------"
  for service in "${services[@]}"; do
    printf '%-10s %-12s %-31s %s\n' \
      "${service}" "${state}" "$(service_endpoint "${service}")" "$(service_description "${service}")"
  done
}

print_service_info() {
  case "$1" in
    mysql)
      cat <<EOF
MySQL
  地址：mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@${BIND_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}
  root：root / ${MYSQL_ROOT_PASSWORD}
  说明：dev 使用 mysql_native_password，便于兼容旧客户端。
EOF
      ;;
    postgres)
      cat <<EOF
PostgreSQL
  地址：postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${BIND_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}
EOF
      ;;
    redis)
      cat <<EOF
Redis
  地址：redis://${BIND_HOST}:${REDIS_PORT}
  认证：无密码
EOF
      ;;
    kafka)
      cat <<EOF
Kafka
  Bootstrap Server：${KAFKA_ADVERTISED_HOST}:${KAFKA_PORT}
  协议：PLAINTEXT，无 TLS/SASL
EOF
      ;;
    s3)
      cat <<EOF
RustFS S3
  API：http://${BIND_HOST}:${S3_PORT}
  Console：http://${BIND_HOST}:${S3_ADMIN_PORT}/rustfs/console/index.html
  Access Key：${S3_ACCESS_KEY}
  Secret Key：${S3_SECRET_KEY}
  Bucket：${S3_BUCKET}
  Region：${S3_REGION}
EOF
      ;;
    mailpit)
      cat <<EOF
Mailpit
  SMTP：${BIND_HOST}:${MAILPIT_SMTP_PORT}（无认证、无 TLS）
  UI：http://${BIND_HOST}:${MAILPIT_UI_PORT}
EOF
      ;;
  esac
}

print_connections() {
  local services=("$@") service
  ((${#services[@]})) || services=("${ALL_SERVICES[@]}")
  for service in "${services[@]}"; do
    print_service_info "${service}"
    echo
  done
}
