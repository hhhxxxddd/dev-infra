"""Offline release verification through actual native entrypoints, without deployment."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .source import extract_package
from .validation import validate


def smoke(archive: Path, destination: Path) -> dict:
    archive = archive.resolve()
    entries = [
        line.split()
        for line in (archive.parent / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    ]
    checksums = [parts[0] for parts in entries if len(parts) == 2 and parts[1] == archive.name]
    if len(checksums) != 1 or hashlib.sha256(archive.read_bytes()).hexdigest() != checksums[0]:
        raise ValueError("Release ZIP checksum failed")
    receipt = extract_package(archive, destination, checksums[0])
    documentation = validate(destination, "dev_infra")
    (destination / ".python").write_text(
        str(Path(sys.executable).resolve()) + "\n", encoding="utf-8"
    )
    if os.name == "nt":
        shell = shutil.which("pwsh")
        if shell is None:
            raise ValueError("PowerShell 7 is required for the native package smoke check")
        entry = [shell, "-NoProfile", "-File", str(destination / "scripts/dev-infra.ps1")]
    else:
        entry = ["bash", str(destination / "dev-infra")]
    environment = {**os.environ, "PYTHONUTF8": "1"}
    environment.pop("DEV_INFRA_TRANSPORT_LANGUAGE", None)
    prefix = [*entry, "--config", str(destination.parent / "missing-smoke-preferences.toml")]
    outputs = []
    for arguments in (["-v"], ["help"], ["config", "--json"]):
        result = subprocess.run(
            [*prefix, *arguments],
            env=environment,
            cwd=destination,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise ValueError("Native package entrypoint smoke check failed")
        outputs.append(result.stdout)
    if (
        outputs[0].strip() != "dev-infra " + receipt["version"]
        or "self" not in outputs[1]
        or not isinstance(json.loads(outputs[2]), dict)
    ):
        raise ValueError("Native package output smoke check failed")
    if (destination.parent / "missing-smoke-preferences.toml").exists():
        raise ValueError("A read-only package query unexpectedly created preferences")
    return {
        "state": "complete",
        "version": receipt["version"],
        "files": len(receipt["files"]),
        "native_entrypoint": True,
        "documentation": documentation,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m dev_infra.package_smoke <release.zip>")
    with tempfile.TemporaryDirectory(prefix="dev-infra-package-smoke-") as temporary:
        result = smoke(Path(sys.argv[1]), Path(temporary) / "package")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
