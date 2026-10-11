#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 sudo bash scripts/install.sh。" >&2
  exit 1
fi
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
install_root=/opt/dev-infra
[[ "$(realpath -m "${install_root}")" == /opt/dev-infra ]] || { echo "安装目录指向了其他位置。" >&2; exit 1; }
origin="$(git -C "${source_root}" remote get-url origin)"
[[ "${origin}" =~ ^(git@github.com:|https://github.com/)hhhxxxddd/dev-infra(\.git)?$ ]] || { echo "仓库来源未经验证。" >&2; exit 1; }
command -v rsync >/dev/null || { echo "缺少 rsync。" >&2; exit 1; }
python_path="${DEV_INFRA_PYTHON:-}"
if [[ -z "${python_path}" && -f "${install_root}/.python" ]]; then
  IFS= read -r python_path <"${install_root}/.python"
fi
if [[ -z "${python_path}" ]]; then
  python_path="$(command -v python3.14 || true)"
fi
if [[ -z "${python_path}" ]] || ! "${python_path}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'; then
  echo "需要 Python 3.14；可通过 DEV_INFRA_PYTHON 指定 WSL 原生解释器。" >&2
  exit 1
fi
python_path="$("${python_path}" -c 'import sys; from pathlib import Path; print(Path(sys.executable).resolve())')"
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
    ledger.setdefault(volume, {"service": service.name, "scope": service.scope(current.values[service.version_key])})
current.save_state("volumes.json", ledger)
PY
fi
rsync -a --delete \
  --exclude '.git/' --exclude '__pycache__/' --exclude '.ruff_cache/' \
  --exclude '.venv/' --exclude 'host/' --exclude '.python' --exclude '*.egg-info/' --exclude 'dist/' --exclude 'build/' \
  --exclude '.env' --exclude 'versions.local.env' --exclude 'backup/' --exclude '.state/' \
  "${source_root}/" "${install_root}/"
if [[ ! -f "${install_root}/.env" ]]; then
  install -m 0600 "${install_root}/.env.example" "${install_root}/.env"
fi
chmod 0755 "${install_root}/dev-infra"
chmod 0644 "${install_root}"/config/mysql/my.cnf "${install_root}"/config/postgres/postgresql.conf \
  "${install_root}"/config/redis/redis.conf "${install_root}"/config/kafka/kafka.env
printf '%s\n' "${source_root}" >"${install_root}/.source"
printf '%s\n' "${python_path}" >"${install_root}/.python"
chmod 0600 "${install_root}/.source" "${install_root}/.python" "${install_root}/.env"
ln -sfn "${install_root}/dev-infra" /usr/local/bin/dev-infra
echo "dev-infra 已安装；运行 dev-infra check 检查环境。"
