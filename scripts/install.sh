#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo bash scripts/install.sh。" >&2
  exit 1
fi
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
install_root="${DEV_INFRA_INSTALL_ROOT:-/opt/dev-infra}"
command_root="${DEV_INFRA_COMMAND_ROOT:-/usr/local/bin}"
[[ "${install_root}" == /* && "${install_root}" != / && "$(realpath -m "${install_root}")" == "${install_root}" && "${command_root}" == /* && "${command_root}" != / ]] || { echo "安装目录必须是有效的绝对路径。" >&2; exit 1; }
[[ "${install_root}" == "${source_root}" || ( "${source_root}" != "${install_root}/"* && "${install_root}" != "${source_root}/"* ) ]] || { echo "安装目录必须独立于源码目录。" >&2; exit 1; }
for target in "${install_root}" "${install_root}/src" "${install_root}/scripts" "${install_root}/config" "${install_root}/init" "${install_root}/docs" "${install_root}/.state" "${install_root}/.python" "${install_root}/.source" "${install_root}/.release.json" "${install_root}/dev-infra" "${install_root}/compose.yaml" "${install_root}/versions.env" "${install_root}/.env.example" "${install_root}/README.md" "${install_root}/README.en.md" "${install_root}/LICENSE" "${install_root}/AGENTS.md" "${install_root}/pyproject.toml"; do
  [[ ! -L "${target}" ]] || { echo "安装目标不允许符号链接。" >&2; exit 1; }
done
command -v rsync >/dev/null || { echo "缺少 rsync。" >&2; exit 1; }
# shellcheck source=scripts/python-runtime.sh
source "${source_root}/scripts/python-runtime.sh"
python_path="$(dev_infra_resolve_python "${install_root}")"
channel="$("${python_path}" -I -S "${source_root}/scripts/verify-source.py" "${source_root}")"
mkdir -p "${install_root}/.state"
exec 9>"${install_root}/.state/operation.lock"
flock -n 9 || { echo "另一项中间件操作正在执行。" >&2; exit 1; }
if [[ -f "${install_root}/versions.env" && -f "${install_root}/.env.example" ]]; then
  PYTHONPATH="${source_root}/src" "${python_path}" - "${install_root}" <<'PY'
import sys
from pathlib import Path
from dev_infra.catalog import SERVICES
from dev_infra.instance import Instance
current = Instance(Path(sys.argv[1]))
ledger = current.read_state("volumes.json")
for service in SERVICES.values():
    volume = current.values[service.volume_key]
    # Deployment remembers declarations for visibility; it cannot prove volume ownership.
    ledger.setdefault(volume, {"service": service.name, "scope": service.scope(current.values[service.version_key]), "ownership": "external"})
current.save_state("volumes.json", ledger)
PY
fi
if [[ "${install_root}" != "${source_root}" ]]; then
  for directory in src/dev_infra scripts config init docs; do
    mkdir -p "${install_root}/${directory}"
    rsync -a --delete --exclude '__pycache__/' --exclude '.ruff_cache/' --exclude '.venv/' \
      --exclude '*.egg-info/' --exclude '*.pyc' --exclude '*.pyo' --exclude '*.local.*' \
      --exclude '.env' --exclude '.python' --exclude '.source' --exclude 'versions.local.env' \
      --exclude '.state/' --exclude 'backup/' --exclude 'backups/' --exclude 'host/' --exclude 'dist/' --exclude 'build/' \
      "${source_root}/${directory}/" "${install_root}/${directory}/"
  done
  for name in dev-infra compose.yaml versions.env .env.example README.md README.en.md LICENSE AGENTS.md pyproject.toml; do
    install -m 0644 "${source_root}/${name}" "${install_root}/${name}"
  done
  if [[ "${channel}" == release ]]; then
    install -m 0644 "${source_root}/.release.json" "${install_root}/.release.json"
  fi
fi
if [[ ! -f "${install_root}/.env" ]]; then
  install -m 0600 "${install_root}/.env.example" "${install_root}/.env"
fi
chmod 0755 "${install_root}/dev-infra"
chmod 0644 "${install_root}"/config/mysql/my.cnf "${install_root}"/config/postgres/postgresql.conf \
  "${install_root}"/config/redis/redis.conf "${install_root}"/config/kafka/kafka.env
if [[ "${channel}" == git ]]; then
  printf '%s\n' "${source_root}" >"${install_root}/.source"
  chmod 0600 "${install_root}/.source"
  rm -f -- "${install_root}/.release.json"
else
  rm -f -- "${install_root}/.source"
fi
printf '%s\n' "${python_path}" >"${install_root}/.python"
chmod 0600 "${install_root}/.python" "${install_root}/.env"
mkdir -p "${command_root}"
ln -sfn "${install_root}/dev-infra" "${command_root}/dev-infra"
echo "dev-infra 已安装；运行 dev-infra check 检查环境。"
