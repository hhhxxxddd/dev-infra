"""Instance declarations and durable local image overrides."""

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import InfraError
from .catalog import SERVICES, VERSION_KEYS

VERSION = re.compile(r"^v?\d+(?:\.\d+){0,2}(?:@sha256:[0-9a-f]{64})?$")
STATE_FORMAT_VERSION = 1
VERSIONED_STATES = {"volumes.json", "last-upgrade.json"}


def validate_state(name: str, value) -> None:
    """Validate persisted records without treating references as ownership proof."""
    if not isinstance(value, dict):
        raise InfraError(f"invalid_state|{name}")
    if name == "volumes.json":
        for volume, record in value.items():
            if not isinstance(volume, str) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", volume
            ):
                raise InfraError(f"invalid_state|{name}")
            if isinstance(record, str) and record in SERVICES:
                continue
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("service"), str)
                or record.get("service") not in SERVICES
                or record.get("scope") is not None
                and not isinstance(record["scope"], str)
                or record.get("ownership") not in (None, "managed", "external")
            ):
                raise InfraError(f"invalid_state|{name}")
    elif name == "last-upgrade.json" and value:
        if value.get("state") not in ("running", "error", "complete", "unchanged"):
            raise InfraError(f"invalid_state|{name}")
        for key in ("stage", "active_service", "started_at", "updated_at", "finished_at"):
            if value.get(key) is not None and not isinstance(value[key], str):
                raise InfraError(f"invalid_state|{name}")
        for key in ("services_selected", "completed_steps"):
            records = value.get(key, [])
            if not isinstance(records, list) or any(not isinstance(item, str) for item in records):
                raise InfraError(f"invalid_state|{name}")
        for key, fields in (
            ("images", ("version",)),
            ("backups", ("service", "state", "path")),
            ("service_results", ("service", "state", "target")),
        ):
            records = value.get(key, [])
            if not isinstance(records, list) or any(
                not isinstance(record, dict)
                or any(not isinstance(record.get(field, ""), str) for field in fields)
                for record in records
            ):
                raise InfraError(f"invalid_state|{name}")
        error = value.get("error")
        if error is not None and (
            not isinstance(error, dict)
            or any(not isinstance(error.get(key, ""), str) for key in ("type", "code", "message"))
        ):
            raise InfraError(f"invalid_state|{name}")


def read_env(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        return result
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in result:
            raise InfraError(f"invalid_env|{path}:{number}")
        value = value.strip()
        if value.startswith('"'):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise InfraError(f"invalid_env|{path}:{number}") from exc
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0]
        if not isinstance(value, str) or any(c in value for c in ("\n", "\r", "\x00")):
            raise InfraError(f"invalid_env|{path}:{number}")
        result[key] = value
    return result


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Instance:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.env_path = self.root / ".env"
        self.overrides_path = self.root / "versions.local.env"
        self.state = self.root / ".state"
        defaults = {**read_env(self.root / ".env.example"), **read_env(self.root / "versions.env")}
        local = read_env(self.env_path)
        if set(local) - set(defaults):
            raise InfraError("invalid_env|unknown field")
        self.values = {**defaults, **local}
        self.overrides = read_env(self.overrides_path)
        if set(self.overrides) - VERSION_KEYS:
            raise InfraError("invalid_env|versions.local.env")
        self.values.update(self.overrides)
        for key in VERSION_KEYS:
            if not VERSION.fullmatch(self.values.get(key, "")):
                raise InfraError(f"invalid_env|{key}")
        for key, value in self.values.items():
            if key.endswith("_PORT") and (not value.isdecimal() or not 1 <= int(value) <= 65535):
                raise InfraError(f"invalid_env|{key}")
        ports = [v for k, v in self.values.items() if k.endswith("_PORT")]
        if len(ports) != len(set(ports)):
            raise InfraError("invalid_env|duplicate ports")
        for service in SERVICES.values():
            if not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", self.values.get(service.volume_key, "")
            ):
                raise InfraError(f"invalid_env|{service.volume_key}")

        volume_names = [self.values[service.volume_key] for service in SERVICES.values()]
        if len(volume_names) != len(set(volume_names)):
            raise InfraError("invalid_env|duplicate volumes")
        postgres_major = int(
            self.values["POSTGRES_VERSION"].split("@", 1)[0].lstrip("v").split(".", 1)[0]
        )
        self.values["POSTGRES_DATA_MOUNT"] = (
            "/var/lib/postgresql" if postgres_major >= 18 else "/var/lib/postgresql/data"
        )

    def initialize(self) -> None:
        if not self.env_path.exists():
            atomic_write(self.env_path, (self.root / ".env.example").read_text(encoding="utf-8"))

    def signature(self) -> dict:
        names = (".env", ".env.example", "versions.env", "versions.local.env", "compose.yaml")
        return {
            name: [path.stat().st_mtime_ns, path.stat().st_size] if path.exists() else None
            for name in names
            for path in [self.root / name]
        }

    def save_versions(self, changes: dict[str, str]) -> None:
        self.overrides.update(changes)
        atomic_write(
            self.overrides_path,
            "# 本机升级结果；self update 保留此文件。\n"
            + "".join(f"{k}={v}\n" for k, v in sorted(self.overrides.items())),
        )
        self.values.update(changes)

    def save_state(self, name: str, value: dict) -> None:
        validate_state(name, value)
        if name in VERSIONED_STATES:
            # Do not replace an unknown or damaged record with an empty new ledger.
            self.read_state(name)
            value = {
                "format": "dev-infra.state",
                "format_version": STATE_FORMAT_VERSION,
                "payload": value,
            }
        atomic_write(self.state / name, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def read_state(self, name: str) -> dict:
        path = self.state / name
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise InfraError(f"invalid_state|{name}") from None
        if isinstance(value, dict) and value.get("format") == "dev-infra.state":
            version = value.get("format_version")
            if type(version) is not int:
                raise InfraError(f"invalid_state|{name}")
            if version != STATE_FORMAT_VERSION:
                raise InfraError(f"unsupported_state_version|{name}")
            value = value.get("payload")
        # Unversioned local records remain readable; queries never migrate them.
        validate_state(name, value)
        return value

    @contextmanager
    def lock(self):
        import fcntl

        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "operation.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise InfraError("busy") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
