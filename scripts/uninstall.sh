#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo bash scripts/uninstall.sh" >&2
  exit 1
fi

rm -f /usr/local/bin/dev-infra
echo "已移除 /usr/local/bin/dev-infra。"
echo "为保护本机配置、备份和数据，/opt/dev-infra 未删除。"
