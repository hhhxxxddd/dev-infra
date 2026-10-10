#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash scripts/install.sh" >&2
  exit 1
fi

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
install_root=/opt/dev-infra

for dependency in rsync curl jq; do
  command -v "${dependency}" >/dev/null 2>&1 || {
    echo "缺少 ${dependency}，请先执行：apt install rsync curl jq" >&2
    exit 1
  }
done

mkdir -p "${install_root}" "${install_root}/backup"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '.env' \
  --exclude 'backup/' \
  "${source_root}/" "${install_root}/"

if [[ ! -f "${install_root}/.env" ]]; then
  install -m 0600 "${install_root}/.env.example" "${install_root}/.env"
  echo "已创建本机配置 ${install_root}/.env"
fi

chmod 0755 "${install_root}/dev-infra" "${install_root}"/bin/*
# Windows checkouts can report mode 0777. MySQL ignores world-writable configs.
chmod 0644 "${install_root}"/config/mysql/my.cnf \
  "${install_root}"/config/postgres/postgresql.conf \
  "${install_root}"/config/redis/redis.conf "${install_root}"/config/kafka/kafka.env
ln -sfn "${install_root}/dev-infra" /usr/local/bin/dev-infra

echo "dev-infra 已安装到 ${install_root}"
echo "运行 dev-infra doctor 检查环境，运行 dev-infra help 查看命令。"
