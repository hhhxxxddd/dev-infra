#!/usr/bin/env bash

dev_infra_resolve_python() {
  local install_root="$1" python_path script_root
  script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  if [[ -v DEV_INFRA_PYTHON ]]; then
    python_path="${DEV_INFRA_PYTHON}"
  elif [[ -e "${install_root}/.python" || -L "${install_root}/.python" ]]; then
    python_path="$(cat "${install_root}/.python")" || return 1
  else
    python_path="$(command -v python3.14 || true)"
  fi
  if [[ -z "${python_path}" ]] || ! "${python_path}" -I -S "${script_root}/check-python.py" linux; then
    echo "需要完整的 WSL 原生 Python 3.14；请通过 DEV_INFRA_PYTHON 指定外部解释器，失效的绑定不会自动回退。" >&2
    return 1
  fi
}
