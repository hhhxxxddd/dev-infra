#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash scripts/install.sh" >&2
  exit 1
fi

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
install_root=/opt/dev-infra

command -v rsync >/dev/null 2>&1 || {
  echo "缺少 rsync，请先执行：apt install rsync" >&2
  exit 1
}

mkdir -p "${install_root}" "${install_root}/backup"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'backup/' \
  "${source_root}/" "${install_root}/"

if [[ ! -f "${install_root}/.env" ]]; then
  install -m 0600 "${install_root}/.env.example" "${install_root}/.env"
  echo "已创建本机配置 ${install_root}/.env"
fi

chmod 0755 "${install_root}/dev-infra" "${install_root}"/bin/*
ln -sfn "${install_root}/dev-infra" /usr/local/bin/dev-infra

echo "dev-infra 已安装到 ${install_root}"
echo "运行 dev-infra doctor 检查环境，运行 dev-infra help 查看命令。"
