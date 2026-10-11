"""Installer source verification using the selected external Python's standard library."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dev_infra.source import verify_source

try:
    print(verify_source(Path(sys.argv[1]))["channel"])
except OSError, ValueError:
    print("安装来源未经验证。", file=sys.stderr)
    raise SystemExit(1) from None
