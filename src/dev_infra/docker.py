"""Docker argv execution; Compose is the sole runtime adapter."""

import json
import os
import subprocess

from . import InfraError
from .catalog import SERVICES
from .instance import read_env


def compose_is_query(arguments: list[str]) -> bool:
    """Recognize read-only Compose commands without executing or inspecting Docker."""
    queries = {
        "config",
        "convert",
        "events",
        "help",
        "images",
        "logs",
        "ls",
        "port",
        "ps",
        "top",
        "version",
        "wait",
    }
    valued_options = {
        "--ansi",
        "--env-file",
        "--file",
        "-f",
        "--parallel",
        "--profile",
        "--progress",
        "--project-directory",
        "--project-name",
        "-p",
    }
    switches = {"--all-resources", "--compatibility"}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in ("--help", "-h"):
            return True
        if argument in valued_options:
            index += 2
        elif (
            argument.partition("=")[0] in valued_options
            and "=" in argument
            or argument in switches
            or argument.startswith(("-f", "-p"))
            and not argument.startswith("--")
        ):
            index += 1
        elif argument.startswith("-"):
            return False
        else:
            # Only an immediate help flag belongs unambiguously to this subcommand.
            # `exec redis some-command --help` can still execute project code.
            options = arguments[index + 1 :]
            if options[:1] in (["--help"], ["-h"]):
                return True
            if argument in ("config", "convert") and any(
                option == "--output"
                or option.startswith("--output=")
                or option.startswith("-o")
                and not option.startswith("--")
                for option in options
            ):
                return False
            if argument == "wait" and any(
                option.partition("=")[0] == "--down-project" for option in options
            ):
                return False
            return argument in queries
    return True


def managed_volume_service(metadata: dict, root) -> str | None:
    """Docker labels prove ownership; names and historical ledgers do not."""
    labels = metadata.get("Labels") or {}
    service = labels.get("io.dev-infra.service")
    if (
        labels.get("io.dev-infra.managed") == "true"
        and labels.get("io.dev-infra.instance") == str(root)
        and service in SERVICES
    ):
        return service
    return None


class Docker:
    def __init__(self, instance):
        self.instance = instance

    def run(self, *arguments: str, check: bool = True, capture: bool = True, timeout: int = 30):
        try:
            result = subprocess.run(
                ["docker", *arguments],
                env={**os.environ, **self.instance.values},
                cwd=self.instance.root,
                check=False,
                capture_output=capture,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise InfraError("command_timeout") from None
        if check and result.returncode:
            raise InfraError(f"docker_failed|{(result.stderr or '').strip() or result.returncode}")
        return result

    def compose_argv(self, *arguments: str) -> list[str]:
        command = [
            "docker",
            "compose",
            "--env-file",
            str(self.instance.root / "versions.env"),
            "--env-file",
            str(
                self.instance.env_path
                if self.instance.env_path.exists()
                else self.instance.root / ".env.example"
            ),
        ]
        if self.instance.overrides_path.exists():
            command.extend(["--env-file", str(self.instance.overrides_path)])
        return [
            *command,
            "-f",
            str(self.instance.root / "compose.yaml"),
            "--profile",
            "optional",
            *arguments,
        ]

    def compose(self, *arguments: str, **options):
        return self.run(*self.compose_argv(*arguments)[1:], **options)

    def available(self) -> bool:
        try:
            return self.run("info", check=False).returncode == 0
        except OSError, InfraError:
            return False

    def require(self) -> None:
        if not self.available():
            raise InfraError("docker_unavailable")
        self.compose("version")

    def config(self) -> dict:
        return json.loads(self.compose("config", "--format", "json").stdout)

    def containers(self) -> list[dict]:
        ids = self.compose("ps", "--all", "--quiet").stdout.split()
        return json.loads(self.run("inspect", *ids).stdout) if ids else []

    def service_containers(self) -> dict[str, dict]:
        return {
            c["Config"]["Labels"].get("com.docker.compose.service"): c for c in self.containers()
        }

    def up(self, targets: list[str], wait: int, *, recreate: bool = False) -> None:
        extra = ["--force-recreate"] if recreate else []
        self.compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            str(wait),
            *extra,
            *targets,
            capture=True,
            timeout=wait + 60,
        )
        if "s3" in targets:
            self.compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/bin/sh",
                "s3-client",
                "-eu",
                "-c",
                'rc alias set local http://s3:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY" --region "$S3_REGION" --bucket-lookup path >/dev/null; if ! rc ls "local/${S3_BUCKET}/" >/dev/null 2>&1; then rc mb "local/${S3_BUCKET}"; fi',
                capture=True,
                timeout=wait,
            )

    def ensure_volumes(self, targets: list[str]) -> None:
        ledger = self.instance.read_state("volumes.json")
        for name in targets:
            volume = self.instance.values[SERVICES[name].volume_key]
            inspection = self.run("volume", "inspect", volume, check=False)
            if inspection.returncode:
                self.run(
                    "volume",
                    "create",
                    "--label",
                    "io.dev-infra.managed=true",
                    "--label",
                    f"io.dev-infra.service={name}",
                    "--label",
                    f"io.dev-infra.instance={self.instance.root}",
                    "--label",
                    f"io.dev-infra.scope={SERVICES[name].scope(self.instance.values[SERVICES[name].version_key])}",
                    volume,
                )
                # Docker may return a concurrently created volume unchanged.
                # Inspect the actual labels rather than claiming it from create's exit code.
                inspection = self.run("volume", "inspect", volume)
            metadata = json.loads(inspection.stdout)[0]
            owned = managed_volume_service(metadata, self.instance.root) == name
            previous = ledger.get(volume)
            scope = (metadata.get("Labels") or {}).get("io.dev-infra.scope")
            if not scope and isinstance(previous, dict):
                scope = previous.get("scope")
            ledger[volume] = {
                "service": name,
                "scope": scope,
                "ownership": "managed" if owned else "external",
            }
        self.instance.save_state("volumes.json", ledger)

    def data_issues(self, targets: list[str], containers=None) -> dict[str, str]:
        baseline = read_env(self.instance.root / "versions.env")
        ledger = self.instance.read_state("volumes.json")
        containers = self.service_containers() if containers is None else containers
        issues = {}
        for name in targets:
            service = SERVICES[name]
            volume = self.instance.values[service.volume_key]
            inspection = self.run("volume", "inspect", volume, check=False)
            if inspection.returncode:
                continue
            metadata = json.loads(inspection.stdout)[0]
            old_scope = (metadata.get("Labels") or {}).get("io.dev-infra.scope")
            if isinstance(ledger.get(volume), dict):
                old_scope = ledger[volume].get("scope", old_scope)
            if not old_scope and baseline[service.volume_key] == volume:
                old_scope = service.scope(baseline[service.version_key])
            container = containers.get(name)
            if container and any(m.get("Name") == volume for m in container.get("Mounts", [])):
                old_scope = service.scope(
                    container["Config"]["Image"].split("@", 1)[0].rsplit(":", 1)[-1]
                )
            if name == "postgres" and volume == "dev-infra-postgres17-data":
                old_scope = "17"
            if old_scope and old_scope != service.scope(self.instance.values[service.version_key]):
                issues[name] = "migration_required"
        return issues

    def validate_data(self, targets: list[str]) -> None:
        issues = self.data_issues(targets)
        if issues:
            raise InfraError(next(iter(issues.values())))

    def volume_users(self, volume: str) -> list[str]:
        return self.run(
            "ps", "-a", "--filter", f"volume={volume}", "--format", "{{.Names}}"
        ).stdout.splitlines()

    def image(self, reference: str) -> dict | None:
        result = self.run("image", "inspect", reference, check=False)
        return json.loads(result.stdout)[0] if result.returncode == 0 else None
