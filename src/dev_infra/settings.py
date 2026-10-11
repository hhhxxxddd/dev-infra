"""Validated, user-local preferences; no writes during queries."""

import json
import os
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import InfraError

TEMPLATE = """# dev-infra 本机偏好；端口和账号使用 config edit --instance 配置。
language = "zh"
editor = []

[wsl]
distro = "Ubuntu"

[operation]
wait_timeout = 240
backup = true
"""


def user_home() -> Path:
    if os.name != "nt" and os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        import pwd

        return Path(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir)
    return Path.home()


def default_path() -> Path:
    if os.name == "nt":
        return user_home() / ".config/dev-infra/config.toml"
    base = (
        user_home() / ".config"
        if os.environ.get("SUDO_USER")
        else Path(os.environ.get("XDG_CONFIG_HOME", user_home() / ".config"))
    )
    return base / "dev-infra/config.toml"


@dataclass
class Settings:
    path: Path
    language: str = "zh"
    editor: tuple[str, ...] = ()
    distro: str = "Ubuntu"
    wait_timeout: int = 240
    backup: bool = True

    def data(self) -> dict:
        return {
            "language": self.language,
            "editor": list(self.editor),
            "wsl": {"distro": self.distro},
            "operation": {"wait_timeout": self.wait_timeout, "backup": self.backup},
        }


def load(path: Path | None = None) -> Settings:
    settings = Settings((path or default_path()).expanduser().resolve())
    if not settings.path.exists():
        return settings
    try:
        raw = tomllib.loads(settings.path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise InfraError(f"invalid_config|{exc}") from exc
    if set(raw) - {"language", "editor", "wsl", "operation"}:
        raise InfraError("invalid_config|unknown field")
    if raw.get("language", "zh") not in ("zh", "en"):
        raise InfraError("invalid_config|language")
    settings.language = raw.get("language", "zh")
    editor = raw.get("editor", [])
    if not isinstance(editor, list) or not all(isinstance(v, str) and v for v in editor):
        raise InfraError("invalid_config|editor")
    settings.editor = tuple(editor)
    wsl = raw.get("wsl", {})
    operation = raw.get("operation", {})
    if (
        not isinstance(wsl, dict)
        or set(wsl) - {"distro"}
        or not isinstance(wsl.get("distro", "Ubuntu"), str)
        or not wsl.get("distro", "Ubuntu").strip()
    ):
        raise InfraError("invalid_config|wsl.distro")
    if not isinstance(operation, dict) or set(operation) - {"wait_timeout", "backup"}:
        raise InfraError("invalid_config|operation")
    settings.distro = wsl.get("distro", "Ubuntu")
    settings.wait_timeout = operation.get("wait_timeout", 240)
    settings.backup = operation.get("backup", True)
    if (
        type(settings.wait_timeout) is not int
        or not 1 <= settings.wait_timeout <= 3600
        or type(settings.backup) is not bool
    ):
        raise InfraError("invalid_config|operation")
    return settings


def editor(settings: Settings) -> list[str]:
    if settings.editor:
        return list(settings.editor)
    for key in ("VISUAL", "EDITOR"):
        if os.environ.get(key):
            value = os.environ[key]
            if os.name == "nt" and Path(value).is_file():
                return [value]
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes

                shell = ctypes.WinDLL("shell32", use_last_error=True)
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
                shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
                kernel.LocalFree.argtypes = [wintypes.HLOCAL]
                kernel.LocalFree.restype = wintypes.HLOCAL
                count = ctypes.c_int()
                arguments = shell.CommandLineToArgvW(value, ctypes.byref(count))
                if not arguments:
                    raise InfraError("invalid_config|editor")
                try:
                    return [arguments[index] for index in range(count.value)]
                finally:
                    kernel.LocalFree(arguments)
            return shlex.split(value)
    return ["notepad.exe" if os.name == "nt" else "vi"]


def edit(path: Path, settings: Settings, initial: str) -> None:
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(initial, encoding="utf-8")
        path.chmod(0o600)
    argv = [*editor(settings), str(path)]
    if os.name != "nt" and os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        import pwd

        identity = pwd.getpwnam(os.environ["SUDO_USER"])
        if path == settings.path:
            os.chown(path, identity.pw_uid, identity.pw_gid)
            for directory in missing:
                os.chown(directory, identity.pw_uid, identity.pw_gid)
            argv = ["sudo", "-H", "-u", identity.pw_name, "--", *argv]
    result = subprocess.run(argv, check=False)
    if result.returncode:
        raise InfraError(f"editor_failed|{result.returncode}")


def render(settings: Settings) -> str:
    return (
        TEMPLATE.partition("\n")[2]
        .replace('language = "zh"', f"language = {json.dumps(settings.language)}")
        .replace("editor = []", f"editor = {json.dumps(list(settings.editor))}")
        .replace('distro = "Ubuntu"', f"distro = {json.dumps(settings.distro)}")
        .replace("wait_timeout = 240", f"wait_timeout = {settings.wait_timeout}")
        .replace("backup = true", f"backup = {str(settings.backup).lower()}")
    )
