"""Reviewed Git sources and integrity-checked release payloads, without deployment."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from . import InfraError

UPSTREAM = "hhhxxxddd/dev-infra"
SCHEMA_VERSION = 1
RECEIPT = ".release.json"
ROOT_FILES = (
    "dev-infra",
    "compose.yaml",
    "versions.env",
    ".env.example",
    "README.md",
    "README.en.md",
    "LICENSE",
    "AGENTS.md",
    "pyproject.toml",
)
DIRECTORIES = ("src/dev_infra", "scripts", "config", "init", "docs")
REQUIRED = (
    *ROOT_FILES,
    "src/dev_infra/__init__.py",
    "src/dev_infra/__main__.py",
    "src/dev_infra/catalog.py",
    "src/dev_infra/cli.py",
    "src/dev_infra/data.py",
    "src/dev_infra/docker.py",
    "src/dev_infra/instance.py",
    "src/dev_infra/operations.py",
    "src/dev_infra/package_smoke.py",
    "src/dev_infra/planning.py",
    "src/dev_infra/presentation.py",
    "src/dev_infra/registry.py",
    "src/dev_infra/release.py",
    "src/dev_infra/settings.py",
    "src/dev_infra/source.py",
    "src/dev_infra/validation.py",
    "scripts/install.ps1",
    "scripts/install.sh",
    "scripts/dev-infra.ps1",
    "scripts/dev-infra.py",
    "scripts/check-python.py",
    "scripts/python-runtime.ps1",
    "scripts/python-runtime.sh",
    "scripts/verify-source.ps1",
    "scripts/verify-source.py",
    "scripts/uninstall.ps1",
    "scripts/uninstall.sh",
    "config/mysql/my.cnf",
    "config/postgres/postgresql.conf",
    "config/redis/redis.conf",
    "config/kafka/kafka.env",
    "init/mysql/10-native-auth.sh",
    "init/postgres/README.md",
)
EXCLUDED = {
    ".git",
    ".env",
    ".python",
    ".source",
    "versions.local.env",
    ".state",
    "backup",
    "backups",
    "host",
    "__pycache__",
    ".ruff_cache",
    ".venv",
    "dist",
    "build",
}
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


def safe_name(name: str) -> bool:
    """Portable file paths: no traversal, aliases, Windows devices or separators."""
    if not isinstance(name, str) or not name or str(PurePosixPath(name)) != name:
        return False
    if PurePosixPath(name).is_absolute() or any(ord(c) < 32 or c in '\\<>:"|?*' for c in name):
        return False
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
    }
    return all(
        part not in {".", ".."}
        and not part.endswith((".", " "))
        and part.split(".", 1)[0].upper() not in reserved
        for part in name.split("/")
    )


def allowed_name(name: str) -> bool:
    if not safe_name(name):
        return False
    parts = PurePosixPath(name).parts
    if any(part in EXCLUDED or part.endswith(".egg-info") for part in parts):
        return False
    if name.endswith((".pyc", ".pyo")) or ".local." in parts[-1]:
        return False
    return name in ROOT_FILES or any(name.startswith(directory + "/") for directory in DIRECTORIES)


def payload_paths(root: Path) -> dict[str, Path]:
    root = root.resolve()
    paths = [root / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        folder = root / directory
        if folder.is_symlink():
            raise InfraError("unverified_source")
        paths.extend(folder.rglob("*") if folder.is_dir() else [])
    result = {}
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        if not allowed_name(name):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise InfraError("unverified_source")
        if path.is_file():
            result[name] = path
    return result


def source_version(root: Path) -> str:
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = metadata["project"]["version"]
    match = re.search(
        r'^__version__ = "([^"]+)"$',
        (root / "src/dev_infra/__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"\d+\.\d+\.\d+", version)
        or match is None
        or match[1] != version
    ):
        raise InfraError("unverified_source")
    return version


def verify_package(root: Path) -> dict:
    """Check content integrity; official download checksums establish its channel."""
    root = root.resolve()
    receipt_path = root / RECEIPT
    try:
        if receipt_path.is_symlink():
            raise InfraError("unverified_source")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        provenance = receipt["provenance"]
        files = receipt["files"]
        if (
            type(receipt.get("schema_version")) is not int
            or receipt.get("schema_version") != SCHEMA_VERSION
            or receipt.get("repository") != UPSTREAM
            or receipt.get("version") != source_version(root)
            or not isinstance(provenance, dict)
            or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", provenance.get("commit", ""))
            or type(provenance.get("dirty")) is not bool
            or not isinstance(files, dict)
            or not set(REQUIRED).issubset(files)
            or any(not allowed_name(name) for name in files)
            or len({name.casefold() for name in files}) != len(files)
        ):
            raise InfraError("unverified_source")
        actual = payload_paths(root)
        if set(actual) != set(files):
            raise InfraError("unverified_source")
        for name, expected in files.items():
            if (
                not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or hashlib.sha256(actual[name].read_bytes()).hexdigest() != expected
            ):
                raise InfraError("unverified_source")
        return receipt
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise InfraError("unverified_source") from exc


def verify_source(root: Path) -> dict:
    root = root.resolve()
    if not (root / ".git").exists():
        return {"channel": "release", "receipt": verify_package(root)}
    prefix = ["git", "-c", f"safe.directory={root}", "-C", str(root)]
    origin = subprocess.run(
        [*prefix, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    checkout = subprocess.run(
        [*prefix, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if (
        origin.returncode
        or checkout.returncode
        or Path(checkout.stdout.strip()).resolve() != root
        or not re.fullmatch(
            r"(?:git@github\.com:|https://github\.com/)hhhxxxddd/dev-infra(?:\.git)?",
            origin.stdout.strip(),
        )
        or not (root / "scripts/install.sh").is_file()
    ):
        raise InfraError("unverified_source")
    payload_paths(root)
    return {"channel": "git"}


def extract_package(archive: Path, destination: Path, expected_checksum: str | None = None) -> dict:
    """Validate every member before extraction; destination must be new or empty."""
    if destination.is_symlink():
        raise InfraError("unverified_source")
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise InfraError("unverified_source")
    if (
        expected_checksum is not None
        and hashlib.sha256(archive.read_bytes()).hexdigest() != expected_checksum
    ):
        raise InfraError("unverified_source")
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        names = [member.filename for member in members]
        if (
            len({name.casefold() for name in names}) != len(names)
            or sum(member.file_size for member in members) > MAX_PACKAGE_BYTES
        ):
            raise InfraError("unverified_source")
        for member in members:
            mode = stat.S_IFMT(member.external_attr >> 16)
            if (
                not safe_name(member.filename)
                or not (allowed_name(member.filename) or member.filename == RECEIPT)
                or member.is_dir()
                or mode not in (0, stat.S_IFREG)
            ):
                raise InfraError("unverified_source")
        package.extractall(destination)
    return verify_package(destination)


def _read_url(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "dev-infra-release"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise InfraError("unverified_source")
    return content


def download_release(destination: Path) -> Path:
    """Only use stable assets and checksum files from the official GitHub repository."""
    try:
        release = json.loads(
            _read_url(f"https://api.github.com/repos/{UPSTREAM}/releases/latest", 1024 * 1024)
        )
        tag = release["tag_name"]
        if (
            not isinstance(tag, str)
            or not re.fullmatch(r"v\d+\.\d+\.\d+", tag)
            or release.get("draft")
            or release.get("prerelease")
        ):
            raise InfraError("unverified_source")
        name = f"dev-infra-{tag[1:]}.zip"
        base = f"https://github.com/{UPSTREAM}/releases/download/{tag}/"
        entries = [
            line.split()
            for line in _read_url(base + "SHA256SUMS", 1024 * 1024).decode("ascii").splitlines()
        ]
        expected = [
            parts[0]
            for parts in entries
            if len(parts) == 2 and parts[1] == name and re.fullmatch(r"[0-9a-f]{64}", parts[0])
        ]
        if len(expected) != 1:
            raise InfraError("unverified_source")
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / name
        archive.write_bytes(_read_url(base + name, MAX_PACKAGE_BYTES))
        root = destination / "package"
        receipt = extract_package(archive, root, expected[0])
        if receipt["version"] != tag[1:]:
            raise InfraError("unverified_source")
        return root
    except urllib.error.HTTPError as exc:
        unavailable = exc.code == 404
        exc.close()
        raise InfraError(
            "release_unavailable" if unavailable else "release_download_failed"
        ) from exc
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, InfraError):
            raise
        raise InfraError("release_download_failed") from exc
