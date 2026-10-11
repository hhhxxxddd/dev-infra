"""Build complete reproducible archives; publishing and bucket updates are separate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

from . import ROOT, __version__
from .source import (
    MAX_PACKAGE_BYTES,
    RECEIPT,
    REQUIRED,
    ROOT_FILES,
    SCHEMA_VERSION,
    UPSTREAM,
    payload_paths,
    source_version,
    verify_source,
)


def provenance(root: Path, *, tag: str | None, official: bool) -> dict:
    prefix = ["git", "-c", f"safe.directory={root.resolve()}", "-C", str(root)]

    def git(*arguments):
        result = subprocess.run(
            [*prefix, *arguments], capture_output=True, text=True, timeout=30, check=False
        )
        if result.returncode:
            raise ValueError("Release provenance requires a Git checkout")
        return result.stdout.strip()

    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=all"))
    if official:
        if tag is None or dirty or git("rev-parse", f"{tag}^{{commit}}") != commit:
            raise ValueError(
                "Official releases require a clean checkout at the matching version tag"
            )
        verify_source(root)
    return {"commit": commit, "dirty": dirty}


def payload_files(root: Path) -> dict[str, bytes]:
    files = {}
    for name, path in payload_paths(root).items():
        content = path.read_bytes()
        if (
            path.suffix
            in {
                ".py",
                ".ps1",
                ".sh",
                ".yaml",
                ".yml",
                ".toml",
                ".md",
                ".json",
                ".conf",
                ".cnf",
                ".env",
                ".txt",
                ".service",
                ".cmd",
                ".bat",
            }
            or name in ROOT_FILES
        ):
            content = content.replace(b"\r\n", b"\n")
        files[name] = content
    if not set(REQUIRED).issubset(files):
        raise ValueError("Release payload is missing required deployment files")
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError("Release payload contains case-insensitive path aliases")
    return files


def scoop_manifest(version: str, checksum: str) -> dict:
    base = f"https://github.com/{UPSTREAM}/releases/download/v{version}"
    return {
        "version": version,
        "description": "Shared local development middleware through a native WSL backend",
        "homepage": f"https://github.com/{UPSTREAM}",
        "license": "MIT",
        "depends": ["main/pwsh"],
        "url": f"{base}/dev-infra-{version}.zip",
        "hash": checksum,
        "bin": [["scripts/dev-infra.ps1", "dev-infra"]],
        "installer": {
            "script": '& pwsh -NoProfile -File "$dir\\scripts\\install.ps1" -AppRoot "$dir" -NoPath; if ($LASTEXITCODE -ne 0) { throw "dev-infra installation failed" }'
        },
        "checkver": "github",
        "autoupdate": {
            "url": f"https://github.com/{UPSTREAM}/releases/download/v$version/dev-infra-$version.zip",
            "hash": {
                "url": f"https://github.com/{UPSTREAM}/releases/download/v$version/SHA256SUMS"
            },
        },
    }


def build(root: Path, output: Path, tag: str | None = None, *, official: bool = False) -> dict:
    root = root.resolve()
    version = source_version(root)
    if version != __version__ or (tag is not None and tag != "v" + version):
        raise ValueError("Release tag, pyproject version and controller version must match")
    origin = provenance(root, tag=tag, official=official)
    if official:
        release_notes(root, tag, origin["commit"])
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "repository": UPSTREAM,
        "version": version,
        "provenance": origin,
    }
    files = payload_files(root)
    receipt["files"] = {
        name: hashlib.sha256(content).hexdigest() for name, content in files.items()
    }
    files[RECEIPT] = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
        raise ValueError("Release payload exceeds the supported package size")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"dev-infra-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        for name, content in sorted(files.items()):
            item = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_STORED
            item.create_system = 3
            mode = 0o755 if name == "dev-infra" or name.endswith(".sh") else 0o644
            item.external_attr = (0o100000 | mode) << 16
            package.writestr(item, content)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(
        f"{checksum}  {archive.name}\n", encoding="ascii", newline="\n"
    )
    (output / "dev-infra.json").write_text(
        json.dumps(scoop_manifest(version, checksum), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "version": version,
        "archive": str(archive),
        "sha256": checksum,
        "provenance": receipt["provenance"],
    }


def smoke(archive: Path, destination: Path) -> dict:
    from .package_smoke import smoke as smoke_package

    return smoke_package(archive, destination)


def release_notes(root: Path, tag: str, commit: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", commit
    ):
        raise ValueError("Release notes require a version tag and a concrete commit")
    root = root.resolve()
    path = root / "docs/releases" / f"{tag}.md"
    content = path.read_text(encoding="utf-8")

    def replace(match):
        target = match[1]
        if urllib.parse.urlsplit(target).scheme or target.startswith("#"):
            return match[0]
        relative, separator, fragment = urllib.parse.unquote(target).partition("#")
        destination = (path.parent / relative).resolve()
        if not destination.is_relative_to(root) or not destination.is_file():
            raise ValueError("Release note links must point to repository files")
        url = f"https://github.com/{UPSTREAM}/blob/{commit}/" + urllib.parse.quote(
            destination.relative_to(root).as_posix()
        )
        return "](" + url + (separator + fragment if separator else "") + ")"

    return re.sub(r"\]\(([^)]+)\)", replace, content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--official", action="store_true")
    parser.add_argument("--smoke", type=Path, help="Verify and smoke-test an existing ZIP offline")
    args = parser.parse_args()
    if args.smoke:
        if args.tag or args.official:
            parser.error("--smoke cannot be combined with --tag or --official")
        with tempfile.TemporaryDirectory(prefix="dev-infra-release-smoke-") as temporary:
            value = smoke(args.smoke.resolve(), Path(temporary) / "package")
    else:
        value = build(ROOT, args.output, args.tag, official=args.official)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
