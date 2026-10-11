"""Validate an externally managed native controller interpreter without importing the app."""

import sys
from pathlib import Path


def check(platform: str) -> Path:
    if sys.platform != platform or sys.version_info[:2] != (3, 14):
        raise RuntimeError(f"需要原生 {platform} Python 3.14。")
    import hashlib
    import ssl
    import tomllib
    import zlib

    ssl.create_default_context()
    hashlib.sha256(b"dev-infra").digest()
    tomllib.loads('language = "zh"')
    zlib.decompress(zlib.compress(b"dev-infra"))
    executable = Path(sys.executable).resolve(strict=True)
    if not executable.is_file():
        raise RuntimeError("Python 解释器路径无效。")
    return executable


if __name__ == "__main__":
    try:
        print(check(sys.argv[1]))
    except (IndexError, OSError, ImportError, RuntimeError) as exc:
        print(f"Python 解释器校验失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
